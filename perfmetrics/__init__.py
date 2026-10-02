"""页面性能指标计算库。

用法::

    from perfmetrics import compute_metrics

    metrics = compute_metrics("/path/to/events.jsonl")
    # metrics.fcp / metrics.lcp / metrics.cls / metrics.tti / metrics.tbt
"""

from .events import EventLog, parse_event_log
from .metrics import Metrics
from .pipeline import compute_metrics, compute_metrics_from_log, normalize

__all__ = [
    "EventLog",
    "Metrics",
    "parse_event_log",
    "compute_metrics",
    "compute_metrics_from_log",
    "normalize",
]
