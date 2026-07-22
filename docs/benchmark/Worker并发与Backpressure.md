# Worker 并发与 Backpressure 指标记录

> 对应手册 Phase 7。由 `scripts/worker_concurrency_fault_injection.py` 生成。
> 目标不是 QPS，而是：**资源边界可控、状态不乱、失败可解释**。

## 复现方式

```bash
PYTHONIOENCODING=utf-8 uv run python scripts/worker_concurrency_fault_injection.py
```

## 最近一次记录（2026-08-29）

| 场景 | accepted | queued | rejected | completed | failed | timed_out | canceled | dup_terminal | unhandled_exc | running | pending | wait_avg_ms | wait_max_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A 单 Worker | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| B 达到 max_workers | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0 |
| C pending 满 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| D timeout | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E cancel queued | 2 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 0 |
| F cancel running | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| G completion-timeout race | 1 | 0 | 0 | 0 | 0 | 1 | 0 | **1** | 0 | 0 | 0 | 0 | 0 |
| H session reset race | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| I resume | 2 | 1 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 313.0 | 313.0 |
| J duplicate notification/handoff | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## 场景含义与判定

- **A 单 Worker**：单任务从 admission 到 completed，`accepted=1`、`completed=1`。
- **B 达到 max_workers**：`max_concurrent_workers=1` 时第二个任务进入 `queued`，采样显示 `running=1/pending=1`，未越界。
- **C pending 满**：`max_pending_workers=0` 时新任务 `rejected`，返回 `worker_queue_full` 结构化错误，无阻塞无丢任务。
- **D timeout**：运行中任务超预算后 `timed_out`；容量释放。
- **E cancel queued**：`queued → canceled`，队列 slot 释放，不启动。
- **F cancel running**：`running → canceled`，协作停止生效。
- **G completion-timeout race**：watcher 先到点提交 `timed_out`，工作线程晚返回的终态提交被拒并记 `dup_terminal=1`——这是**预期行为**，证明终态只提交一次。
- **H session reset race**：旧 watcher 在新 session 中找不到条目，静默退出，指标归零，无 `unknown worker` 异常。
- **I resume**：持久化的 `queued` 重新入队并完成（`completed=1`），孤儿 `running` 无本地实体标记 `failed=1`；队列等待 313ms。
- **J duplicate notification/handoff**：`completed=1`，重复 `publish_terminal_notification` 被幂等键拦截，实际只投递 1 条通知；写 Worker 的 `change_handoff.idempotency_key` 稳定。

## 结论

- `unhandled_exc` 全为 0：无未处理线程异常。
- `dup_terminal` 除 G（故意制造的 race）外全为 0：终态单次提交，没有第二次覆盖。
- 所有场景的 `running/pending` 均未超过 `max_workers / max_pending_tasks`，资源边界可控。

## 历史记录

> 首次运行 2026-08-29（A–J 全部通过）即为上述表格。
