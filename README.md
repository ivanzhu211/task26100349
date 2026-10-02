# task26100349

页面性能指标计算库 `perfmetrics`：监控平台抓取任务在无头浏览器子进程退出后，
读取其写在本地磁盘的事件记录文件（JSON Lines），按统一口径计算
FCP / LCP / CLS / TBT / TTI 并直接返回，由上层负责入库。

## 用法

```python
from perfmetrics import compute_metrics

metrics = compute_metrics("/path/to/events.jsonl")
# metrics.fcp / metrics.lcp / metrics.cls / metrics.tti / metrics.tbt
# 缺失的指标为 None（不是 0）；时间单位毫秒，零点为最后一次主框架导航开始
```

## 事件记录格式

每行一个 JSON 对象，不要求按时间排序。事件类型：

- `navigation_start`：`ts`, `frame`（`"main"`/`"sub"`）
- `first_contentful_paint`：`ts`, `frame`
- `largest_contentful_paint_candidate`：`ts`, `frame`, `area`
- `layout_shift`：`ts`, `frame`, `score`
- `task`：`start`, `end`
- `request_start` / `request_end`：`ts`, `request_id`
- `user_input`：`ts`, `frame`
- `recording_end`：`ts`

## 计算口径

- 以最后一次主框架导航开始为零点，之前的事件（含零点前发出的请求）一律丢弃。
- FCP/LCP/CLS 的指标事件只看主框架；网络请求不分框架；时间段含开始不含结束。
- LCP：第一次用户输入前面积最大的候选（同面积取较早）；无候选则缺失。
- CLS：输入后 500ms 内（含）的偏移不计；其余按 1s 间隔 / 5s 窗口分组，取分值和最大的一组。
- TTI：FCP 后起点最早的 5s 安静窗口（无长任务执行、在飞请求 ≤2、完整落在录制结束前），
  取 FCP 到窗口起点间最后一个长任务的结束时刻，无则取 FCP；找不到窗口则缺失。
- TBT：FCP 到 TTI（缺失则到录制结束）之间，任务落在区间内那一截超过 50ms 的部分求和。
- 无 FCP 时 LCP/TTI/TBT 均缺失。

## 测试

```bash
python3 -m pytest
```
