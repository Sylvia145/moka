# Worker 并发与 Backpressure 指标记录

运行或验收时从 `agent.worker_manager.to_dict()["metrics"]` 读取以下指标：

| 指标 | 含义 |
| --- | --- |
| `accepted` / `queued` / `rejected` | admission 结果 |
| `completed` / `failed` / `timed_out` / `canceled` | 已提交终态 |
| `duplicate_terminal_transition` | 竞争中被拒绝的第二次终态提交 |
| `queue_wait_ms_avg` / `queue_wait_ms_max` | 已从队列启动任务的等待时间 |
| `running` / `pending` | 采样瞬间的容量使用 |

验收重点不是 QPS，而是有界 admission、失败可解释和终态不可覆盖。针对 A–J 故障场景，记录上述快照、对应 session event 和是否存在未处理线程异常。
