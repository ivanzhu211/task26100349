"""各性能指标的计算逻辑。

输入为已归一化的事件集合（零点 = 最后一次主框架导航开始）。
约定：

- 时间段一律含开始、不含结束。
- FCP/LCP/CLS 的指标事件（绘制、候选、偏移）只看主框架；
  用户输入作为页面级交互信号，不分框架参与 LCP/CLS 的判定。
- 长任务：时长超过 50ms 的主线程任务。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .events import MAIN_FRAME, EventLog, MainThreadTask


LONG_TASK_THRESHOLD_MS = 50.0
QUIET_WINDOW_MS = 5000.0
MAX_IN_FLIGHT_REQUESTS = 2
CLS_INPUT_EXCLUSION_MS = 500.0
CLS_SESSION_GAP_MS = 1000.0
CLS_SESSION_WINDOW_MS = 5000.0


@dataclass(frozen=True)
class Metrics:
    """计算结果。缺失的指标为 None，绝不以 0 代替。"""

    fcp: Optional[float]
    lcp: Optional[float]
    cls: float
    tti: Optional[float]
    tbt: Optional[float]


def _first_input_ts(log: EventLog) -> Optional[float]:
    if not log.user_inputs:
        return None
    return min(inp.ts for inp in log.user_inputs)


def _long_tasks(log: EventLog) -> list[MainThreadTask]:
    return [
        t for t in log.tasks if t.end - t.start > LONG_TASK_THRESHOLD_MS
    ]


def _request_intervals(log: EventLog) -> list[tuple[float, Optional[float]]]:
    """把请求配对成 (发出, 结束) 区间；录制结束仍未结束的请求 end 为 None。"""
    starts: dict[str, list[float]] = {}
    for req in log.request_starts:
        starts.setdefault(req.request_id, []).append(req.ts)
    for pending in starts.values():
        pending.sort()

    intervals: list[tuple[float, Optional[float]]] = []
    for end_event in log.request_ends:
        pending = starts.get(end_event.request_id)
        if not pending:
            continue  # 零点前发出的请求已被丢弃，对应的结束事件无意义
        start = pending.pop()
        intervals.append((start, end_event.ts))
    for pending in starts.values():
        for start in pending:
            intervals.append((start, None))
    return intervals


def compute_fcp(log: EventLog) -> Optional[float]:
    """主框架最早的首次内容绘制时刻。"""
    main_fcps = [e.ts for e in log.fcps if e.frame == MAIN_FRAME]
    return min(main_fcps) if main_fcps else None


def compute_lcp(log: EventLog) -> Optional[float]:
    """第一次用户输入之前面积最大的 LCP 候选；面积相同取较早的。"""
    first_input = _first_input_ts(log)
    best_ts: Optional[float] = None
    best_area = 0.0
    for cand in log.lcp_candidates:
        if cand.frame != MAIN_FRAME:
            continue
        if first_input is not None and cand.ts >= first_input:
            continue
        if best_ts is None or cand.area > best_area:
            best_ts, best_area = cand.ts, cand.area
    return best_ts


def compute_cls(log: EventLog) -> float:
    """会话窗口分组后的最大布局偏移分值和。"""
    input_ts = sorted(inp.ts for inp in log.user_inputs)
    shifts = sorted(
        (s for s in log.layout_shifts if s.frame == MAIN_FRAME),
        key=lambda s: s.ts,
    )

    def excluded(ts: float) -> bool:
        # 某次输入之后 500ms 以内（含 500ms）的偏移不计
        for its in input_ts:
            if its < ts <= its + CLS_INPUT_EXCLUSION_MS:
                return True
            if its >= ts:
                break
        return False

    best = 0.0
    session_sum = 0.0
    session_start: Optional[float] = None
    prev_ts: Optional[float] = None
    for shift in shifts:
        if excluded(shift.ts):
            continue
        if (
            prev_ts is not None
            and shift.ts - prev_ts < CLS_SESSION_GAP_MS
            and shift.ts - session_start < CLS_SESSION_WINDOW_MS
        ):
            session_sum += shift.score
        else:
            session_sum = shift.score
            session_start = shift.ts
        prev_ts = shift.ts
        best = max(best, session_sum)
    return best


def compute_tti(log: EventLog, fcp: Optional[float]) -> Optional[float]:
    """从 FCP 起找起点最早的 5 秒安静窗口，反推 TTI。"""
    if fcp is None:
        return None
    recording_end = log.recording_end.ts if log.recording_end else float("inf")
    long_tasks = _long_tasks(log)
    intervals = _request_intervals(log)

    def window_is_quiet(start: float) -> bool:
        end = start + QUIET_WINDOW_MS
        if end > recording_end:
            return False
        for task in long_tasks:
            if task.start < end and task.end > start:
                return False
        # 在飞请求数只在请求发出/结束时变化，检查窗口内各分段峰值
        points = {start}
        for req_start, req_end in intervals:
            if req_start > start and req_start < end:
                points.add(req_start)
            if req_end is not None and start < req_end < end:
                points.add(req_end)
        for point in points:
            in_flight = sum(
                1
                for req_start, req_end in intervals
                if req_start <= point and (req_end is None or point < req_end)
            )
            if in_flight > MAX_IN_FLIGHT_REQUESTS:
                return False
        return True

    # 安静条件只可能在任务结束或请求结束时由不满足变为满足
    candidates = {fcp}
    for task in long_tasks:
        if task.end >= fcp:
            candidates.add(task.end)
    for _, req_end in intervals:
        if req_end is not None and req_end >= fcp:
            candidates.add(req_end)

    window_start: Optional[float] = None
    for start in sorted(candidates):
        if window_is_quiet(start):
            window_start = start
            break
    if window_start is None:
        return None

    ends = [t.end for t in long_tasks if fcp <= t.end <= window_start]
    return max(ends) if ends else fcp


def compute_tbt(
    log: EventLog, fcp: Optional[float], tti: Optional[float]
) -> Optional[float]:
    """FCP 到 TTI（缺失时到录制结束）之间，任务落在区间内那一截超过 50ms 的部分。"""
    if fcp is None:
        return None
    if tti is not None:
        interval_end = tti
    elif log.recording_end is not None:
        interval_end = log.recording_end.ts
    else:
        return None

    total = 0.0
    for task in log.tasks:
        overlap = min(task.end, interval_end) - max(task.start, fcp)
        if overlap > LONG_TASK_THRESHOLD_MS:
            total += overlap - LONG_TASK_THRESHOLD_MS
    return total
