# Worker 并发与生命周期现状

> 对应手册 Phase 0。基于真实代码的调用链追踪，区分"已确认"与"待确认/未解决"。

## 1. 完整生命周期调用链

```text
父 Agent 委派
  pico.tools.agents.tool_agent
    └─ runtime.run_tool("agent", ...)
         └─ WorkerManager.spawn(description, prompt, subagent_type, write_scope, timeout_seconds)
              ├─ new_task()
              │    ├─ WorkerManager._lock 内分配 next_id
              │    ├─ create_worktree()：写 Worker + git 仓库时建 .worktrees/<worker_id>
              │    └─ build_child_runtime()：构造子 Pico（含 model_client_factory）
              ├─ can_run_background()？   （有无 model_client_factory）
              │    └─ 无 → 同步 fallback：_mark_starting + run_worker（父线程串行）
              └─ admit_background_task()（_lock 临界区）
                   ├─ started → _start_background() → 工作线程 run_worker + watcher 线程
                   ├─ queued  → task.state 存 prompt，等待容量
                   └─ rejected→ remove_worktree()，返回 worker_queue_full 结构化错误

后台执行
  run_worker()（工作线程，pico-worker-<id>）
    ├─ {starting}→{running}
    ├─ task.runtime.ask(prompt)   ← 模型调用（协作式可中断）
    ├─ collect_worker_artifacts() + build_change_handoff()（含 idempotency_key）
    └─ {running, stopping}→terminal（completed/failed/stopped/timed_out）

Timeout
  _watch_timeout()（watcher 线程，每任务一个）
    ├─ 到点后 _find_item() 判空（session reset 后旧条目已丢 → 安全早退）
    ├─ 仅当仍为 running：request_stop() → abort_current_turn()
    └─ {running}→{timed_out}

Notification / Handoff
  publish_terminal_notification()：按 <id>:<execution_sequence>:terminal 幂等键
    └─ _notifications 队列 + worker_finished 事件
  change_handoff.idempotency_key = <id>:<execution_sequence>:handoff

Session 持久化
  session["workers"] 随 session_store.save() 保存（含 items/metrics/next_id）

Resume / Clear
  resume_runtime_session / clear_runtime_session
    ├─ shutdown_workers()：停旧线程、queued→canceled、清理 worktree
    ├─ 重建 WorkerManager
    └─ recover_workers_after_resume()
         ├─ queued      → restore_queued_task 重新入队
         ├─ active      → 无本地实体 → failed（resume_execution_entity_missing）
         └─ terminal    → 不重启
```

## 2. 线程与锁清单

| 线程 | 创建点 | 职责 |
| --- | --- | --- |
| 父 Agent 主线程 | Engine | 委派、`send_message`（`continue_task`）、`task_stop`（`stop_task`）、drain 通知 |
| 工作线程 `pico-worker-<id>` | `_start_background` | `run_worker` 执行子 Runtime |
| 超时 watcher 线程 | `_start_background`（每任务一个） | 到点请求协作停止、提交 `timed_out` |

| 锁/同步原语 | 覆盖范围 | 说明 |
| --- | --- | --- |
| `WorkerManager._lock`（RLock） | admission、状态迁移、指标、worktree 清理 | 唯一跨线程共享状态的保护点；可重入以支持嵌套调用 |
| `queue.Queue` `_notifications` | Worker 生产、Engine/CLI/TUI 消费 | drain 由协调者独占 |
| 会话文件 / 事件文件 | 跨进程 | 事件追加式写入；会话由 `_save` 原子替换 |
| 事件 `threading.Event`（测试用） | 测试夹具 | `BlockingModelClient` 控制启动/释放 |

## 3. 共享可变状态

| 状态 | 读写者 | 保护方式 |
| --- | --- | --- |
| `session["workers"]["items"]` | admission、工作线程、watcher、停止路径、resume | `_lock`；终态经 `transition_worker_state` |
| `session["workers"]["metrics"]` | 各路径累加 | `_lock`（`record_metric`） |
| `manager._tasks` | 管理器、队首启动、shutdown | 进程内，manager 生命周期隔离 |
| `task.stop_requested` / `task.state` | 停止路径、工作线程 | 进程内字段，watcher/stop 先置位再走状态机 |
| `item["notification_delivery_keys"]` | `publish_terminal_notification`、`drain_notifications` | `_lock` |

## 4. 关键问题逐项确认

**是否有并发上限？** 已确认。`max_concurrent_workers`（默认 2）限制运行数，`max_pending_tasks`（默认 16）限制队列数；admission 在 `_lock` 内原子决策，任意委派路径均不可绕过。

**是否有 queue？** 已确认。`queued` 状态 + FIFO `start_next_queued`；等待时长计入 `queue_wait_ms_avg/max`。

**completion/timeout/cancel 是否会竞争？** 会，且已处理。三者终态都经 `transition_worker_state` CAS 提交，后到者记 `duplicate_terminal_transition` 且不覆盖、不重发通知。

**session reset 后旧 watcher 如何处理？** 已确认。`clear_session`/`resume_session` 先 `shutdown_workers`；旧 watcher 到点后 `_find_item` 判空安全早退，不污染新 session。

**terminal state 是否可能重复写？** 已确认不可能。`transition_worker_state` 对终态做单次提交；work 线程晚返回、watcher 重触发、外部重复 stop 均被拒绝。

**notification/handoff 是否幂等？** 已确认。notification 用 `<id>:<execution_sequence>:terminal`，handoff 用 `<id>:<execution_sequence>:handoff`；`publish_terminal_notification` 检查 pending/delivered 键去重。

**resume 是否可能重复启动 Worker？** 已确认不可能。终态 Worker 不重启；queued 重新入队；残留 active 因无本地执行实体而标记 failed。

**被拒绝的写 Worker 是否锁住父 Agent？** 已确认不锁。只有 accepted（queued/started）才激活 `delegated_review`；被拒绝任务清理提前创建的 worktree。

## 5. 待确认 / 未解决

- Python 线程不能被安全强杀；timeout/cancel 依赖 `abort_current_turn` 协作式响应。若子 Runtime 内部有 shell/子进程，协作式中断不保证立即终止。
- resume 对"本地执行实体仍存活但会话被重建"的情形不做进程间探测——当前实现统一按"实体不存在"处理（标记 failed）。若未来支持多进程 Worker，需要真正的存活探测。
- 通知以进程内 `queue.Queue` 为传输；跨进程持久化的通知重放（session 事件重读）语义尚未建模。
- worktree 仅对"从未启动即终态"的 Worker 清理；已完成的写 Worker worktree 保留供 `delegated_review` 审核，手动回收流程未建模。
