"""各项指标（FCP/LCP/CLS/TBT/TTI）的纯函数计算。

约定：
- 所有时间均为对齐零点后的毫秒；时间段一律含开始、不含结束。
- 长任务：时长超过 50 毫秒的主线程任务。
- FCP/LCP/CLS 只看主框架事件；网络请求不分框架。
"""

from __future__ import annotations

from pageperf.events import Event

LONG_TASK_MS = 50.0
QUIET_WINDOW_MS = 5000.0
MAX_IN_FLIGHT = 2
INPUT_EXCLUSION_MS = 500.0
SESSION_GAP_MS = 1000.0
SESSION_WINDOW_MS = 5000.0


def _first_user_input(events: list[Event]) -> float | None:
    inputs = [e.ts for e in events if e.type == "user_input"]
    return min(inputs) if inputs else None


def _long_tasks(events: list[Event]) -> list[tuple[float, float]]:
    """所有长任务的 [start, end) 区间，按开始时间排序。"""
    tasks = [
        (e.ts, e.end)
        for e in events
        if e.type == "main_thread_task"
        and e.end is not None
        and e.end - e.ts > LONG_TASK_MS
    ]
    tasks.sort()
    return tasks


def _request_intervals(
    events: list[Event], recording_end: float
) -> list[tuple[float, float]]:
    """每个请求的在飞区间 [start, end)；录制结束时未结束的请求算到录制结束。"""
    ends: dict[str, float] = {}
    for e in events:
        if e.type == "request_end" and e.request_id is not None:
            ends[e.request_id] = e.ts
    intervals = [
        (e.ts, ends.get(e.request_id, recording_end))
        for e in events
        if e.type == "request_start" and e.request_id is not None
    ]
    intervals.sort()
    return intervals


def compute_fcp(events: list[Event]) -> float | None:
    """主框架首次内容绘制的时间；没有则为 None。"""
    paints = [
        e.ts
        for e in events
        if e.type == "first_contentful_paint" and e.frame == "main"
    ]
    return min(paints) if paints else None


def compute_lcp(events: list[Event]) -> float | None:
    """第一次用户输入之前面积最大的候选（面积相同取较早）的时间。"""
    first_input = _first_user_input(events)
    candidates = [
        e
        for e in events
        if e.type == "largest_contentful_paint_candidate" and e.frame == "main"
    ]
    if first_input is not None:
        candidates = [e for e in candidates if e.ts < first_input]
    if not candidates:
        return None
    best = max(candidates, key=lambda e: (e.area or 0.0, -e.ts))
    return best.ts


def compute_cls(events: list[Event]) -> float:
    """会话窗口分组后的最大分组分值和；没有偏移为 0。"""
    first_inputs = sorted(e.ts for e in events if e.type == "user_input")

    def excluded(ts: float) -> bool:
        # 某次用户输入之后 500 毫秒以内（含 500 毫秒）的偏移不计。
        return any(t < ts <= t + INPUT_EXCLUSION_MS for t in first_inputs)

    shifts = sorted(
        (e.ts, e.score or 0.0)
        for e in events
        if e.type == "layout_shift" and e.frame == "main" and not excluded(e.ts)
    )
    if not shifts:
        return 0.0

    best = 0.0
    group_sum = 0.0
    group_start = shifts[0][0]
    prev_ts = shifts[0][0]
    for ts, score in shifts:
        if ts - prev_ts < SESSION_GAP_MS and ts - group_start < SESSION_WINDOW_MS:
            group_sum += score
        else:
            best = max(best, group_sum)
            group_sum = score
            group_start = ts
        prev_ts = ts
    return max(best, group_sum)


def _busy_intervals(
    events: list[Event], recording_end: float
) -> list[tuple[float, float]]:
    """安静窗口不允许出现的区间：长任务执行中，或在飞请求超过 2 个。"""
    busy: list[tuple[float, float]] = list(_long_tasks(events))

    # 扫描线在飞请求数，找出 > MAX_IN_FLIGHT 的时间段。
    changes: list[tuple[float, int]] = []
    for start, end in _request_intervals(events, recording_end):
        changes.append((start, 1))
        changes.append((end, -1))
    # 同一时刻先处理结束（-1）再处理开始（+1）：含开始、不含结束。
    changes.sort(key=lambda item: (item[0], item[1]))
    count = 0
    open_since: float | None = None
    for ts, delta in changes:
        prev = count
        count += delta
        if prev <= MAX_IN_FLIGHT < count:
            open_since = ts
        elif prev > MAX_IN_FLIGHT >= count and open_since is not None:
            busy.append((open_since, ts))
            open_since = None
    if open_since is not None:
        busy.append((open_since, recording_end))

    busy.sort()
    merged: list[list[float]] = []
    for start, end in busy:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def compute_tti(
    events: list[Event], fcp: float, recording_end: float
) -> float | None:
    """从 FCP 起找起点最早的 5 秒安静窗口；找不到返回 None。"""
    window_start = fcp
    for start, end in _busy_intervals(events, recording_end):
        if end <= window_start:
            continue
        if start >= window_start + QUIET_WINDOW_MS:
            break
        window_start = end
    if window_start + QUIET_WINDOW_MS > recording_end:
        return None
    # 结束时刻落在 FCP 到窗口起点之间的最后一个长任务的结束时刻。
    ends = [e for s, e in _long_tasks(events) if fcp <= e <= window_start]
    return max(ends) if ends else fcp


def compute_tbt(
    events: list[Event], fcp: float, tti: float | None, recording_end: float
) -> float:
    """FCP 到 TTI（TTI 缺失时到录制结束）之间，长任务超出 50 毫秒的部分之和。"""
    upper = tti if tti is not None else recording_end
    total = 0.0
    for start, end in _long_tasks(events):
        clipped_start = max(start, fcp)
        clipped_end = min(end, upper)
        clipped = clipped_end - clipped_start
        if clipped > LONG_TASK_MS:
            total += clipped - LONG_TASK_MS
    return total
