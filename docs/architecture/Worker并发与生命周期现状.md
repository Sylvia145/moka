# Worker 并发与生命周期现状

## 已确认

- 父 Agent 经 `pico.tools.agents.tool_agent` 调用 `WorkerManager.spawn`；`send_message` 进入 `continue_task`，`task_stop` 进入 `stop_task`。
- `WorkerManager` 是唯一的 Worker 会话状态入口：`session["workers"]` 持久化任务、admission 信息和累计指标；后台任务保存在进程内 `_tasks`。
- 后台路径由 `worker_background.admit_background_task` 在 `WorkerManager._lock`（`RLock`）内作 admission。它按 active 数和 pending 数原子决定 `starting`、`queued` 或 `rejected`。
- `worker_execution.run_worker` 启动子 Runtime、生成交接产物、写通知；`_watch_timeout` 仅在仍为 `running` 时请求协作式停止。
- 终态由 `WorkerManager.transition_terminal` 提交；完成与超时竞争时，后到者只增加 `duplicate_terminal_transition`，不会覆盖先到者，也不会发送第二次通知。
- 会话事件通过 `SessionEventBus` 持久化，包含 `worker_submitted`、`worker_queued`、`worker_rejected`、`worker_started`、`worker_finished` 和 `worker_timed_out`。
- `clear_session` 和 `resume_session` 会先调用 `shutdown_workers`，再重建 `WorkerManager`；旧 timeout watcher 找不到旧条目会安全退出。

## 共享状态与锁

| 状态 | 读写者 | 保护方式 |
| --- | --- | --- |
| `session.workers.items` | admission、执行线程、timeout watcher、停止路径 | `WorkerManager._lock` |
| `_tasks` 与待执行 prompt | WorkerManager、队首启动 | 当前进程内，由 manager 生命周期隔离 |
| `_notifications` | Worker 生产、Engine/CLI/TUI 消费 | `queue.Queue` |
| 会话文件与事件文件 | manager、SessionEventBus | 追加式事件；会话由 `_save` 持久化 |

## 当前指标

`WorkerManager.to_dict()["metrics"]` 提供 `accepted`、`queued`、`rejected`、`completed`、`failed`、`timed_out`、`canceled`、`duplicate_terminal_transition`、`unhandled_thread_exception`、队列等待时间统计及实时 `running/pending` 容量快照。

## 待确认 / 未完成

- Python 线程不能被安全强杀；timeout/cancel 依赖 `abort_current_turn` 的协作式响应。
- resume 目前重建 manager，不会重启已持久化的 terminal Worker；对遗留 `RUNNING` 执行实体的恢复策略尚未独立建模。
- handoff 目前由 Worker 结果契约生成；需要为跨重启场景补充独立稳定幂等键和专项测试。
