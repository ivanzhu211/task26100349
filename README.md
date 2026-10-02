# pageperf

页面性能指标计算库。监控平台的抓取任务在无头浏览器子进程退出后调用，
输入是子进程写在本地磁盘上的事件记录文件，指标直接返回，由上层负责入库。

## 使用

```python
from pageperf import compute_metrics_from_file

metrics = compute_metrics_from_file("/path/to/events.json")
# Metrics(fcp=..., lcp=..., cls=..., tbt=..., tti=...)
```

缺失的指标为 `None`（例如没有 FCP 时 LCP/TTI/TBT 均为 `None`），不会为 0。
时间单位均为毫秒，CLS 无单位。

## 记录文件格式

JSON 事件数组（也兼容 JSONL），不要求按时间排序。时间单位为毫秒。

| type | 说明 | 额外字段 |
| --- | --- | --- |
| `navigation_start` | 导航开始 | `frame`: `main`/`sub` |
| `first_contentful_paint` | 首次内容绘制 | `frame` |
| `largest_contentful_paint_candidate` | LCP 候选 | `frame`, `area` |
| `layout_shift` | 布局偏移 | `frame`, `score` |
| `main_thread_task` | 主线程任务 | `end`（`ts` 为开始） |
| `request_start` / `request_end` | 请求发出/结束 | `request_id` |
| `user_input` | 用户输入 | — |
| `recording_end` | 录制结束 | — |

## 计算口径

- 零点：最后一次主框架导航开始；此前的事件一律不算（含之前发出、之后结束的请求）。
- FCP/LCP/CLS 只看主框架；网络请求不分框架。时间段含开始、不含结束。
- 长任务：时长超过 50ms 的主线程任务；请求发出到结束算在飞，录制结束未结束的一直算在飞。
- LCP：首次用户输入之前面积最大的候选（面积相同取较早）；之前没有候选则缺失。
- CLS：用户输入后 500ms 内（含）的偏移不计；其余按“与上次相隔 <1s 且距组首 <5s”分组，
  取分值和最大的一组；无偏移为 0。
- TTI：从 FCP 起起点最早的 5s 安静窗口（完整落在录制结束前，窗口内无长任务执行、
  在飞请求始终 ≤2）；取结束时刻落在 FCP 到窗口起点之间的最后一个长任务的结束时刻，
  没有则为 FCP；找不到窗口则缺失。
- TBT：FCP 到 TTI（TTI 缺失时到录制结束）之间，长任务落在区间内那一截超过 50ms 的部分之和。

## 测试

```bash
python3 -m pytest
```
