"""事件类型定义与事件记录文件解析。

事件记录文件为 JSON Lines 格式：每行一个 JSON 对象，至少包含
``type`` 字段。文件不保证按时间排序。

支持的事件类型：

- ``navigation_start``: 导航开始。字段: ``ts``, ``frame`` ("main"/"sub")
- ``first_contentful_paint``: 首次内容绘制。字段: ``ts``, ``frame``
- ``largest_contentful_paint_candidate``: LCP 候选。字段: ``ts``, ``frame``, ``area``
- ``layout_shift``: 布局偏移。字段: ``ts``, ``frame``, ``score``
- ``task``: 主线程任务。字段: ``start``, ``end``
- ``request_start`` / ``request_end``: 网络请求发出/结束。字段: ``ts``, ``request_id``
- ``user_input``: 用户输入。字段: ``ts``, ``frame``
- ``recording_end``: 录制结束。字段: ``ts``

时间单位一律为毫秒。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


MAIN_FRAME = "main"


@dataclass(frozen=True)
class NavigationStart:
    ts: float
    frame: str


@dataclass(frozen=True)
class FirstContentfulPaint:
    ts: float
    frame: str


@dataclass(frozen=True)
class LcpCandidate:
    ts: float
    frame: str
    area: float


@dataclass(frozen=True)
class LayoutShift:
    ts: float
    frame: str
    score: float


@dataclass(frozen=True)
class MainThreadTask:
    start: float
    end: float


@dataclass(frozen=True)
class RequestStart:
    ts: float
    request_id: str


@dataclass(frozen=True)
class RequestEnd:
    ts: float
    request_id: str


@dataclass(frozen=True)
class UserInput:
    ts: float
    frame: str


@dataclass(frozen=True)
class RecordingEnd:
    ts: float


Event = (
    NavigationStart
    | FirstContentfulPaint
    | LcpCandidate
    | LayoutShift
    | MainThreadTask
    | RequestStart
    | RequestEnd
    | UserInput
    | RecordingEnd
)


@dataclass
class EventLog:
    """解析后的事件集合（未做零点归一化）。"""

    navigations: list[NavigationStart] = field(default_factory=list)
    fcps: list[FirstContentfulPaint] = field(default_factory=list)
    lcp_candidates: list[LcpCandidate] = field(default_factory=list)
    layout_shifts: list[LayoutShift] = field(default_factory=list)
    tasks: list[MainThreadTask] = field(default_factory=list)
    request_starts: list[RequestStart] = field(default_factory=list)
    request_ends: list[RequestEnd] = field(default_factory=list)
    user_inputs: list[UserInput] = field(default_factory=list)
    recording_end: Optional[RecordingEnd] = None


_EVENT_TYPES = {
    "navigation_start",
    "first_contentful_paint",
    "largest_contentful_paint_candidate",
    "layout_shift",
    "task",
    "request_start",
    "request_end",
    "user_input",
    "recording_end",
}


def _require(raw: dict, key: str, lineno: int):
    if key not in raw:
        raise ValueError(f"第 {lineno} 行事件缺少字段 {key!r}: {raw!r}")
    return raw[key]


def parse_event_log(path: str) -> EventLog:
    """从本地事件记录文件解析出事件集合。"""
    log = EventLog()
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            etype = _require(raw, "type", lineno)
            if etype not in _EVENT_TYPES:
                raise ValueError(f"第 {lineno} 行未知事件类型: {etype!r}")

            if etype == "navigation_start":
                log.navigations.append(
                    NavigationStart(
                        ts=float(_require(raw, "ts", lineno)),
                        frame=str(_require(raw, "frame", lineno)),
                    )
                )
            elif etype == "first_contentful_paint":
                log.fcps.append(
                    FirstContentfulPaint(
                        ts=float(_require(raw, "ts", lineno)),
                        frame=str(_require(raw, "frame", lineno)),
                    )
                )
            elif etype == "largest_contentful_paint_candidate":
                log.lcp_candidates.append(
                    LcpCandidate(
                        ts=float(_require(raw, "ts", lineno)),
                        frame=str(_require(raw, "frame", lineno)),
                        area=float(_require(raw, "area", lineno)),
                    )
                )
            elif etype == "layout_shift":
                log.layout_shifts.append(
                    LayoutShift(
                        ts=float(_require(raw, "ts", lineno)),
                        frame=str(_require(raw, "frame", lineno)),
                        score=float(_require(raw, "score", lineno)),
                    )
                )
            elif etype == "task":
                start = float(_require(raw, "start", lineno))
                end = float(_require(raw, "end", lineno))
                if end < start:
                    raise ValueError(f"第 {lineno} 行任务 end 早于 start: {raw!r}")
                log.tasks.append(MainThreadTask(start=start, end=end))
            elif etype == "request_start":
                log.request_starts.append(
                    RequestStart(
                        ts=float(_require(raw, "ts", lineno)),
                        request_id=str(_require(raw, "request_id", lineno)),
                    )
                )
            elif etype == "request_end":
                log.request_ends.append(
                    RequestEnd(
                        ts=float(_require(raw, "ts", lineno)),
                        request_id=str(_require(raw, "request_id", lineno)),
                    )
                )
            elif etype == "user_input":
                log.user_inputs.append(
                    UserInput(
                        ts=float(_require(raw, "ts", lineno)),
                        frame=str(_require(raw, "frame", lineno)),
                    )
                )
            elif etype == "recording_end":
                log.recording_end = RecordingEnd(ts=float(_require(raw, "ts", lineno)))
    return log
