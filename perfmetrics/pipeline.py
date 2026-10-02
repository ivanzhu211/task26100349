"""对外入口：读取事件记录文件，按统一口径计算全部指标。"""

from __future__ import annotations

from .events import (
    MAIN_FRAME,
    EventLog,
    FirstContentfulPaint,
    LayoutShift,
    LcpCandidate,
    MainThreadTask,
    NavigationStart,
    RecordingEnd,
    RequestEnd,
    RequestStart,
    UserInput,
    parse_event_log,
)
from .metrics import (
    Metrics,
    compute_cls,
    compute_fcp,
    compute_lcp,
    compute_tbt,
    compute_tti,
)


def normalize(log: EventLog) -> EventLog:
    """以最后一次主框架导航开始为零点。

    零点之前发生的事件一律丢弃（包括零点前发出、零点后结束的请求，
    以及零点前开始的主线程任务），保留的事件时间平移到新零点。
    """
    main_navs = [n.ts for n in log.navigations if n.frame == MAIN_FRAME]
    if not main_navs:
        raise ValueError("事件记录中没有主框架导航开始事件，无法确定零点")
    zero = max(main_navs)

    out = EventLog()
    out.navigations = [
        NavigationStart(ts=n.ts - zero, frame=n.frame)
        for n in log.navigations
        if n.ts >= zero
    ]
    out.fcps = [
        FirstContentfulPaint(ts=e.ts - zero, frame=e.frame)
        for e in log.fcps
        if e.ts >= zero
    ]
    out.lcp_candidates = [
        LcpCandidate(ts=e.ts - zero, frame=e.frame, area=e.area)
        for e in log.lcp_candidates
        if e.ts >= zero
    ]
    out.layout_shifts = [
        LayoutShift(ts=e.ts - zero, frame=e.frame, score=e.score)
        for e in log.layout_shifts
        if e.ts >= zero
    ]
    out.tasks = [
        MainThreadTask(start=t.start - zero, end=t.end - zero)
        for t in log.tasks
        if t.start >= zero
    ]
    out.request_starts = [
        RequestStart(ts=e.ts - zero, request_id=e.request_id)
        for e in log.request_starts
        if e.ts >= zero
    ]
    out.request_ends = [
        RequestEnd(ts=e.ts - zero, request_id=e.request_id)
        for e in log.request_ends
        if e.ts >= zero
    ]
    out.user_inputs = [
        UserInput(ts=e.ts - zero, frame=e.frame)
        for e in log.user_inputs
        if e.ts >= zero
    ]
    if log.recording_end is not None:
        if log.recording_end.ts < zero:
            raise ValueError("录制结束早于最后一次主框架导航开始，记录无效")
        out.recording_end = RecordingEnd(ts=log.recording_end.ts - zero)
    return out


def compute_metrics_from_log(log: EventLog) -> Metrics:
    """对已解析（未归一化）的事件集合计算指标。"""
    normalized = normalize(log)
    fcp = compute_fcp(normalized)
    lcp = compute_lcp(normalized) if fcp is not None else None
    cls = compute_cls(normalized)
    tti = compute_tti(normalized, fcp)
    tbt = compute_tbt(normalized, fcp, tti)
    return Metrics(fcp=fcp, lcp=lcp, cls=cls, tti=tti, tbt=tbt)


def compute_metrics(path: str) -> Metrics:
    """读取事件记录文件并计算指标，结果直接返回给上层。"""
    return compute_metrics_from_log(parse_event_log(path))
