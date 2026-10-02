"""按统一口径手算值对齐的验收测试。"""

import json

import pytest

from perfmetrics import compute_metrics, compute_metrics_from_log
from perfmetrics.events import parse_event_log
from perfmetrics.pipeline import normalize


def write_log(tmp_path, events):
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    return str(path)


# ---------------------------------------------------------------------------
# 场景一：带重定向且事件乱序
#
# 绝对时间线（ms）：
#   1000 主框架导航#1（重定向前的旧页面）
#   1500 旧页面 FCP（应被丢弃）
#   1600 旧页面布局偏移 0.5（应被丢弃）
#   1700 旧页面 LCP 候选 area=9999（应被丢弃）
#   1800 请求 r1 发出（零点前，整条的应忽略）
#   2000 主框架导航#2 → 零点
#   2400-2600 长任务A → [400,600]
#   2620-2650 短任务  → [620,650]（30ms，不计 TBT）
#   2600 主框架 FCP → 600
#   2700 子框架 FCP（不参与 FCP）
#   2800-3300 请求 r2 → [800,1300]
#   2900 偏移 0.1 → 900
#   3000-3500 请求 r3 → [1000,1500]
#   3000 LCP 候选 area=500 → 1000
#   3100-3400 请求 r4 → [1100,1400]
#   3100 偏移 0.2 → 1100
#   3200-3600 请求 r5 → [1200,1600]
#   3200 子框架 LCP 候选 area=5000（不参与 LCP）
#   3400 LCP 候选 area=800 → 1400
#   3600 用户输入 → 1600
#   3650 偏移 0.9 → 1650（输入后 500ms 内，不计）
#   3800 LCP 候选 area=2000（输入之后，不参与）
#   4200 请求 r1 结束（起点已被丢弃，无配对，忽略）
#   7200 偏移 0.4 → 5200（与上一偏移相隔 4100ms ≥ 1s，另起一组）
#   8600 录制结束 → 6600
#
# 手算：FCP=600，LCP=1400，CLS=max(0.1+0.2, 0.4)=0.4，
#       安静窗口 [1400,6400]，TTI=900（最后结束的长任务A?B 中 B 结束于 900），
#       TBT=(200-50)=150（仅任务B落在 [600,900] 的部分）
# ---------------------------------------------------------------------------

SCENARIO1_EVENTS = [
    # 故意乱序
    {"type": "request_end", "ts": 3300, "request_id": "r2"},
    {"type": "navigation_start", "ts": 2000, "frame": "main"},
    {"type": "layout_shift", "ts": 1600, "frame": "main", "score": 0.5},
    {"type": "task", "start": 2700, "end": 2900},
    {"type": "first_contentful_paint", "ts": 2600, "frame": "main"},
    {"type": "request_start", "ts": 1800, "request_id": "r1"},
    {"type": "largest_contentful_paint_candidate", "ts": 3400, "frame": "main", "area": 800},
    {"type": "navigation_start", "ts": 1000, "frame": "main"},
    {"type": "recording_end", "ts": 8600},
    {"type": "request_start", "ts": 3000, "request_id": "r3"},
    {"type": "layout_shift", "ts": 7200, "frame": "main", "score": 0.4},
    {"type": "user_input", "ts": 3600, "frame": "main"},
    {"type": "largest_contentful_paint_candidate", "ts": 1700, "frame": "main", "area": 9999},
    {"type": "request_end", "ts": 4200, "request_id": "r1"},
    {"type": "first_contentful_paint", "ts": 1500, "frame": "main"},
    {"type": "task", "start": 2400, "end": 2600},
    {"type": "request_start", "ts": 2800, "request_id": "r2"},
    {"type": "layout_shift", "ts": 2900, "frame": "main", "score": 0.1},
    {"type": "largest_contentful_paint_candidate", "ts": 3000, "frame": "main", "area": 500},
    {"type": "request_start", "ts": 3100, "request_id": "r4"},
    {"type": "layout_shift", "ts": 3100, "frame": "main", "score": 0.2},
    {"type": "request_start", "ts": 3200, "request_id": "r5"},
    {"type": "largest_contentful_paint_candidate", "ts": 3200, "frame": "sub", "area": 5000},
    {"type": "first_contentful_paint", "ts": 2700, "frame": "sub"},
    {"type": "task", "start": 2620, "end": 2650},
    {"type": "request_end", "ts": 3500, "request_id": "r3"},
    {"type": "request_end", "ts": 3400, "request_id": "r4"},
    {"type": "request_end", "ts": 3600, "request_id": "r5"},
    {"type": "layout_shift", "ts": 3650, "frame": "main", "score": 0.9},
    {"type": "largest_contentful_paint_candidate", "ts": 3800, "frame": "main", "area": 2000},
]


def test_scenario1_redirect_and_unordered(tmp_path):
    metrics = compute_metrics(write_log(tmp_path, SCENARIO1_EVENTS))
    assert metrics.fcp == pytest.approx(600)
    assert metrics.lcp == pytest.approx(1400)
    assert metrics.cls == pytest.approx(0.4)
    assert metrics.tti == pytest.approx(900)
    assert metrics.tbt == pytest.approx(150)


def test_scenario1_normalize_drops_pre_zero_events(tmp_path):
    log = normalize(parse_event_log(write_log(tmp_path, SCENARIO1_EVENTS)))
    # 零点后保留的事件时间均已平移；零点前事件全部丢弃
    assert all(n.ts >= 0 for n in log.navigations)
    assert [f.ts for f in log.fcps] == [600, 700]
    assert all(s.ts >= 0 for s in log.layout_shifts)
    # 零点前发出的 r1 起点被丢弃，其结束事件无配对、不参与在飞计算
    assert all(r.request_id != "r1" for r in log.request_starts)


# ---------------------------------------------------------------------------
# 场景二：网络比 CPU 晚安静，且有请求到录制结束都未结束
#
# 时间线（ms，零点即唯一一次主导航 0）：
#   500   FCP
#   500-700 长任务（CPU 在 700 后就安静了）
#   600-3000  r1
#   800-3200  r2
#   1000-3400 r3
#   1200-3100 r4   → 在飞数 4 直到 3000；3100 起降为 2
#   4000      r5 发出，录制结束仍未结束（一直在飞，占 1 个额度）
#   9000  录制结束
#
# 手算：安静窗口最早起点 3100（[3100,8100] 完整落在 9000 前，
#       窗口内在飞峰值 2），TTI=700（长任务结束于 700），
#       TBT=200-50=150，LCP=600（无用户输入），CLS=0
# ---------------------------------------------------------------------------

SCENARIO2_EVENTS = [
    {"type": "navigation_start", "ts": 0, "frame": "main"},
    {"type": "first_contentful_paint", "ts": 500, "frame": "main"},
    {"type": "largest_contentful_paint_candidate", "ts": 600, "frame": "main", "area": 100},
    {"type": "task", "start": 500, "end": 700},
    {"type": "request_start", "ts": 600, "request_id": "r1"},
    {"type": "request_start", "ts": 800, "request_id": "r2"},
    {"type": "request_start", "ts": 1000, "request_id": "r3"},
    {"type": "request_start", "ts": 1200, "request_id": "r4"},
    {"type": "request_end", "ts": 3000, "request_id": "r1"},
    {"type": "request_end", "ts": 3100, "request_id": "r4"},
    {"type": "request_end", "ts": 3200, "request_id": "r2"},
    {"type": "request_end", "ts": 3400, "request_id": "r3"},
    {"type": "request_start", "ts": 4000, "request_id": "r5"},
    {"type": "recording_end", "ts": 9000},
]


def test_scenario2_network_quiets_after_cpu(tmp_path):
    metrics = compute_metrics(write_log(tmp_path, SCENARIO2_EVENTS))
    assert metrics.fcp == pytest.approx(500)
    assert metrics.lcp == pytest.approx(600)
    assert metrics.cls == pytest.approx(0.0)
    assert metrics.tti == pytest.approx(700)
    assert metrics.tbt == pytest.approx(150)


def test_no_fcp_makes_lcp_tti_tbt_missing(tmp_path):
    events = [
        {"type": "navigation_start", "ts": 0, "frame": "main"},
        {"type": "largest_contentful_paint_candidate", "ts": 600, "frame": "main", "area": 100},
        {"type": "task", "start": 100, "end": 300},
        {"type": "layout_shift", "ts": 200, "frame": "main", "score": 0.3},
        {"type": "recording_end", "ts": 9000},
    ]
    metrics = compute_metrics(write_log(tmp_path, events))
    assert metrics.fcp is None
    assert metrics.lcp is None
    assert metrics.tti is None
    assert metrics.tbt is None
    # CLS 不依赖 FCP，仍正常计算
    assert metrics.cls == pytest.approx(0.3)


def test_tti_missing_when_no_quiet_window(tmp_path):
    events = [
        {"type": "navigation_start", "ts": 0, "frame": "main"},
        {"type": "first_contentful_paint", "ts": 500, "frame": "main"},
        {"type": "task", "start": 500, "end": 6000},  # 长任务一直跑到录制结束附近
        {"type": "recording_end", "ts": 6500},
    ]
    metrics = compute_metrics(write_log(tmp_path, events))
    assert metrics.tti is None
    # TTI 缺失时 TBT 统计到录制结束：[500,6500] 内任务那截 5500ms → 5500-50
    assert metrics.tbt == pytest.approx(5450)


def test_missing_main_navigation_raises(tmp_path):
    events = [
        {"type": "navigation_start", "ts": 0, "frame": "sub"},
        {"type": "recording_end", "ts": 1000},
    ]
    with pytest.raises(ValueError, match="主框架导航"):
        compute_metrics(write_log(tmp_path, events))
