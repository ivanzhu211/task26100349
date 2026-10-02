"""页面性能指标计算库：FCP / LCP / CLS / TBT / TTI。"""

from pageperf.core import Metrics, compute_metrics, compute_metrics_from_file
from pageperf.events import Event, EventStream, load_events

__all__ = [
    "Event",
    "EventStream",
    "Metrics",
    "compute_metrics",
    "compute_metrics_from_file",
    "load_events",
]
