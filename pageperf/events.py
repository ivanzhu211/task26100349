"""事件记录文件的解析与零点对齐。

记录文件是子进程写在本地磁盘上的 JSON 文件：一个事件数组（也兼容 JSONL，
即每行一个事件对象）。所有时间单位均为毫秒。整份文件不保证按时间排序。

事件类型：
- navigation_start                        导航开始（frame 区分主/子框架）
- first_contentful_paint                  首次内容绘制
- largest_contentful_paint_candidate      最大内容绘制候选（带 area）
- layout_shift                            布局偏移（带 score）
- main_thread_task                        主线程任务（ts 为开始，end 为结束）
- request_start / request_end             网络请求发出/结束（request_id 关联）
- user_input                              用户输入
- recording_end                           录制结束
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    """一条已归一化的事件。时间均已减去零点（最后一次主框架导航开始）。"""

    type: str
    ts: float
    frame: str | None = None
    end: float | None = None
    area: float | None = None
    score: float | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class EventStream:
    """对齐零点后的完整事件流，按 (ts, end) 排序。"""

    events: tuple[Event, ...] = field(default_factory=tuple)

    @property
    def recording_end(self) -> float | None:
        for event in self.events:
            if event.type == "recording_end":
                return event.ts
        return None


def _read_raw_events(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError("事件记录文件必须是事件数组")
        return data
    return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def _zero_point(raw_events: list[dict[str, Any]]) -> float:
    """零点：最后一次主框架导航开始的时间。没有主框架导航时为 0。"""
    mains = [
        float(raw["ts"])
        for raw in raw_events
        if raw.get("type") == "navigation_start" and raw.get("frame") == "main"
    ]
    return max(mains) if mains else 0.0


def _to_event(raw: dict[str, Any], zero: float) -> Event | None:
    """把原始记录归一化为 Event；发生在零点之前的事件返回 None。"""
    event_type = raw.get("type")
    if not event_type:
        return None
    ts = raw.get("ts")
    if ts is None:
        return None
    ts = float(ts) - zero
    end = raw.get("end")
    end = float(end) - zero if end is not None else None
    # 零点之前发生的事件一律丢弃：时间段事件要求起点在零点或之后。
    if ts < 0:
        return None
    return Event(
        type=str(event_type),
        ts=ts,
        frame=raw.get("frame"),
        end=end,
        area=float(raw["area"]) if raw.get("area") is not None else None,
        score=float(raw["score"]) if raw.get("score") is not None else None,
        request_id=str(raw["request_id"]) if raw.get("request_id") is not None else None,
    )


def load_events(path: str) -> EventStream:
    """从磁盘读取事件记录文件，返回对齐零点后的有序事件流。"""
    raw_events = _read_raw_events(path)
    zero = _zero_point(raw_events)
    events = [event for raw in raw_events if (event := _to_event(raw, zero))]
    events.sort(key=lambda e: (e.ts, e.end if e.end is not None else e.ts))
    return EventStream(events=tuple(events))
