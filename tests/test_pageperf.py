"""按统一口径手算的对照测试。"""

from __future__ import annotations

import json
import random

import pytest

from pageperf import compute_metrics_from_file, load_events
from pageperf.events import Event, EventStream
from pageperf.metrics import compute_cls


def _write(tmp_path, events, name="record.json"):
    path = tmp_path / name
    path.write_text(json.dumps(events), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 场景一：带重定向（多次主框架导航）且事件乱序的记录
#
# 绝对时间线（毫秒），零点 = 最后一次主框架导航 = 200：
#   100  主框架导航（重定向前）          -> 零点前，丢弃
#   150  主框架 FCP（重定向前的绘制）     -> 零点前，丢弃
#   180  主框架布局偏移 0.5              -> 零点前，丢弃
#   150  请求 r1 发出，600 结束          -> 发出在零点前，整个丢弃
#   200  主框架导航（零点）
#   250  子框架导航
#   300  主框架 FCP                      -> FCP = 100
#   350  主框架 LCP 候选 area=100        -> rel 150
#   400  主框架 LCP 候选 area=250        -> rel 200（面积并列最大，较早者胜）
#   420  子框架 LCP 候选 area=999        -> 非主框架，忽略
#   430  主框架 LCP 候选 area=250        -> rel 230（并列但较晚，落选）
#   500  用户输入                        -> rel 300
#   560  主框架偏移 0.3                  -> rel 360，在输入后 500ms 内，不计
#   600  主框架 LCP 候选 area=500        -> rel 400，在首次输入之后，不参与 LCP
#   900  主框架偏移 0.1                  -> rel 700 ┐ 同组（间隔 100 < 1000，
#   1000 主框架偏移 0.2                  -> rel 800 ┘ 距组首 100 < 5000）和 0.3
#   2600 主框架偏移 0.25                 -> rel 2400 ┐ 间隔 1600 >= 1000，另起一组
#   2700 主框架偏移 0.25                 -> rel 2500 ┘ 和 0.5 -> CLS = 0.5
#   任务：rel 50-120（长，70ms）、rel 300-360（长，60ms）、rel 500-530（30ms，非长）
#   请求：r2 rel 200-700、r3 rel 250-450、r4（子框架）rel 260-500
#         rel 260-450 在飞 3 个 > 2 -> 忙碌区间 (260, 450)
#   录制结束 rel 8000
#
# 手算：FCP=100，LCP=200，CLS=0.5
#   TTI：忙碌区间 (50,120)、(260,450)。w=100 -> 120 -> 450，窗口 [450,5450) 完整。
#         结束时刻落在 [100,450] 的长任务：120、360 -> TTI = 360
#   TBT：[100,360) 内，(50,120) 截为 20ms 不计；(300,360) 截为 60ms，计 10 -> TBT=10
# ---------------------------------------------------------------------------

CASE1_EVENTS = [
    {"type": "navigation_start", "frame": "main", "ts": 100},
    {"type": "first_contentful_paint", "frame": "main", "ts": 150},
    {"type": "layout_shift", "frame": "main", "ts": 180, "score": 0.5},
    {"type": "request_start", "request_id": "r1", "ts": 150},
    {"type": "request_end", "request_id": "r1", "ts": 600},
    {"type": "navigation_start", "frame": "main", "ts": 200},
    {"type": "navigation_start", "frame": "sub", "ts": 250},
    {"type": "first_contentful_paint", "frame": "main", "ts": 300},
    {"type": "largest_contentful_paint_candidate", "frame": "main", "ts": 350, "area": 100},
    {"type": "largest_contentful_paint_candidate", "frame": "main", "ts": 400, "area": 250},
    {"type": "largest_contentful_paint_candidate", "frame": "sub", "ts": 420, "area": 999},
    {"type": "largest_contentful_paint_candidate", "frame": "main", "ts": 430, "area": 250},
    {"type": "user_input", "ts": 500},
    {"type": "layout_shift", "frame": "main", "ts": 560, "score": 0.3},
    {"type": "largest_contentful_paint_candidate", "frame": "main", "ts": 600, "area": 500},
    {"type": "layout_shift", "frame": "main", "ts": 900, "score": 0.1},
    {"type": "layout_shift", "frame": "main", "ts": 1000, "score": 0.2},
    {"type": "layout_shift", "frame": "main", "ts": 2600, "score": 0.25},
    {"type": "layout_shift", "frame": "main", "ts": 2700, "score": 0.25},
    {"type": "main_thread_task", "ts": 250, "end": 320},
    {"type": "main_thread_task", "ts": 500, "end": 560},
    {"type": "main_thread_task", "ts": 700, "end": 730},
    {"type": "request_start", "request_id": "r2", "ts": 400},
    {"type": "request_end", "request_id": "r2", "ts": 900},
    {"type": "request_start", "request_id": "r3", "ts": 450},
    {"type": "request_end", "request_id": "r3", "ts": 650},
    {"type": "request_start", "request_id": "r4", "ts": 460},
    {"type": "request_end", "request_id": "r4", "ts": 700},
    {"type": "recording_end", "ts": 8200},
]


def test_redirect_and_unordered(tmp_path):
    shuffled = CASE1_EVENTS[:]
    random.Random(42).shuffle(shuffled)
    metrics = compute_metrics_from_file(_write(tmp_path, shuffled))
    assert metrics.fcp == 100
    assert metrics.lcp == 200
    assert metrics.cls == pytest.approx(0.5)
    assert metrics.tti == 360
    assert metrics.tbt == pytest.approx(10)


def test_pre_zero_request_is_dropped(tmp_path):
    """零点前发出、零点后结束的请求要整个丢弃（r1 不参与在飞统计）。"""
    stream = load_events(_write(tmp_path, CASE1_EVENTS))
    starts = [e.request_id for e in stream.events if e.type == "request_start"]
    assert starts == ["r2", "r3", "r4"]


# ---------------------------------------------------------------------------
# 场景二：网络比 CPU 晚安静，且有请求到录制结束都没结束
#
# 零点 = 1000。FCP rel 500。
#   长任务：rel 600-800、900-960、2500-2560 -> CPU 在 2560 后就安静了
#   请求：r1 rel 600-3000，r2 rel 700-3500，r3 rel 800 发出后永不结束
#         rel 800-3000 在飞 3 个 > 2 -> 网络忙碌到 3000，晚于 CPU
#   录制结束 rel 8000
#
# 手算：忙碌区间合并为 (600,3000)。w=500 -> 3000，窗口 [3000,8000) 完整。
#   结束时刻落在 [500,3000] 的长任务：800、960、2560 -> TTI = 2560
#   TBT：[500,2560) 内 (600,800) 计 150，(900,960) 计 10，(2500,2560) 计 10
#         -> TBT = 170；LCP = 700；CLS = 0
# ---------------------------------------------------------------------------

CASE2_EVENTS = [
    {"type": "navigation_start", "frame": "main", "ts": 1000},
    {"type": "first_contentful_paint", "frame": "main", "ts": 1500},
    {"type": "largest_contentful_paint_candidate", "frame": "main", "ts": 1700, "area": 100},
    {"type": "main_thread_task", "ts": 1600, "end": 1800},
    {"type": "main_thread_task", "ts": 1900, "end": 1960},
    {"type": "main_thread_task", "ts": 3500, "end": 3560},
    {"type": "request_start", "request_id": "r1", "ts": 1600},
    {"type": "request_end", "request_id": "r1", "ts": 4000},
    {"type": "request_start", "request_id": "r2", "ts": 1700},
    {"type": "request_end", "request_id": "r2", "ts": 4500},
    {"type": "request_start", "request_id": "r3", "ts": 1800},
    {"type": "recording_end", "ts": 9000},
]


def test_network_quiets_after_cpu_with_unfinished_request(tmp_path):
    metrics = compute_metrics_from_file(_write(tmp_path, CASE2_EVENTS))
    assert metrics.fcp == 500
    assert metrics.lcp == 700
    assert metrics.cls == 0
    assert metrics.tti == 2560
    assert metrics.tbt == pytest.approx(170)


def test_no_quiet_window_means_missing_tti(tmp_path):
    """场景二基础上再加一个 rel 4000-4100 的长任务：窗口被顶到 [4100,9100)，
    超出录制结束 8000 -> TTI 缺失，TBT 统计到录制结束。"""
    events = CASE2_EVENTS + [{"type": "main_thread_task", "ts": 5000, "end": 5100}]
    metrics = compute_metrics_from_file(_write(tmp_path, events))
    assert metrics.tti is None
    # [500, 8000)：150 + 10 + 10 + (4000,4100) 计 50 = 220
    assert metrics.tbt == pytest.approx(220)


# ---------------------------------------------------------------------------
# 缺失语义
# ---------------------------------------------------------------------------

def test_missing_fcp_cascades(tmp_path):
    """没有 FCP 时 LCP/TTI/TBT 都缺失（None），CLS 仍正常计算。"""
    events = [
        {"type": "navigation_start", "frame": "main", "ts": 0},
        {"type": "layout_shift", "frame": "main", "ts": 100, "score": 0.4},
        {"type": "largest_contentful_paint_candidate", "frame": "main", "ts": 200, "area": 10},
        {"type": "main_thread_task", "ts": 100, "end": 300},
        {"type": "recording_end", "ts": 10000},
    ]
    metrics = compute_metrics_from_file(_write(tmp_path, events))
    assert metrics.fcp is None
    assert metrics.lcp is None
    assert metrics.tti is None
    assert metrics.tbt is None
    assert metrics.cls == pytest.approx(0.4)


def test_lcp_missing_when_no_candidate_before_first_input(tmp_path):
    events = [
        {"type": "navigation_start", "frame": "main", "ts": 0},
        {"type": "first_contentful_paint", "frame": "main", "ts": 100},
        {"type": "user_input", "ts": 200},
        {"type": "largest_contentful_paint_candidate", "frame": "main", "ts": 300, "area": 10},
        {"type": "recording_end", "ts": 10000},
    ]
    metrics = compute_metrics_from_file(_write(tmp_path, events))
    assert metrics.lcp is None


# ---------------------------------------------------------------------------
# CLS 分组规则单元测试
# ---------------------------------------------------------------------------

def _shift(ts, score):
    return Event(type="layout_shift", ts=float(ts), frame="main", score=score)


def test_cls_session_window_5s_limit():
    # 间隔 900ms 的链式偏移：前 6 个同组（和 0.6）；
    # 5400 距上一次 900 < 1000，但距组首 0 为 5400 >= 5000 -> 另起一组
    events = [_shift(t, 0.1) for t in range(0, 5400, 900)] + [_shift(5400, 0.4)]
    assert compute_cls(events) == pytest.approx(0.6)


def test_cls_gap_1s_limit():
    # 间隔恰好 1000 不满足“不到 1 秒” -> 另起一组
    events = [_shift(0, 0.3), _shift(1000, 0.3)]
    assert compute_cls(events) == pytest.approx(0.3)


def test_cls_input_exclusion_boundary():
    # 输入后恰好 500ms（含）不计；501ms 计
    events = [Event(type="user_input", ts=1000.0), _shift(1500, 0.9), _shift(1501, 0.2)]
    assert compute_cls(events) == pytest.approx(0.2)
