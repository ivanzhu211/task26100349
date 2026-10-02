"""对外入口：从事件记录文件计算全部指标。"""

from __future__ import annotations

from dataclasses import dataclass

from pageperf.events import EventStream, load_events
from pageperf.metrics import (
    compute_cls,
    compute_fcp,
    compute_lcp,
    compute_tbt,
    compute_tti,
)


@dataclass(frozen=True)
class Metrics:
    """计算结果，单位毫秒（CLS 无单位）。缺失的指标为 None，不能当成 0。"""

    fcp: float | None
    lcp: float | None
    cls: float
    tbt: float | None
    tti: float | None


def compute_metrics(stream: EventStream) -> Metrics:
    """对已对齐零点的事件流计算全部指标。"""
    events = list(stream.events)
    fcp = compute_fcp(events)
    cls = compute_cls(events)
    if fcp is None:
        # 没有 FCP 时，LCP、TTI、TBT 都缺失。
        return Metrics(fcp=None, lcp=None, cls=cls, tbt=None, tti=None)
    recording_end = stream.recording_end
    lcp = compute_lcp(events)
    if recording_end is None:
        # 记录缺少录制结束事件：TTI 无法确定，TBT 也没有可用的上界。
        return Metrics(fcp=fcp, lcp=lcp, cls=cls, tbt=None, tti=None)
    tti = compute_tti(events, fcp, recording_end)
    tbt = compute_tbt(events, fcp, tti, recording_end)
    return Metrics(fcp=fcp, lcp=lcp, cls=cls, tbt=tbt, tti=tti)


def compute_metrics_from_file(path: str) -> Metrics:
    """读取子进程写出的事件记录文件并计算全部指标。"""
    return compute_metrics(load_events(path))
