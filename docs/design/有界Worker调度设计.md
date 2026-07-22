# 有界 Worker 调度设计

> 对应手册 Phase 1。本设计已落地，本文是设计回溯：说明"为什么这样设计"以及当前实现与后续阶段的合同。

## 1. 问题

父 Agent 委派子 Worker 时，模型可以无限创建后台任务。仅限制运行线程数量会把压力转移到无限增长的 pending 列表：要么无限堆积内存，要么静默丢任务，要么无限阻塞父 Agent。需要一个**有界、可解释、可审计**的本地调度器：

- 运行中任务数受 `max_workers` 上限约束。
- 等待任务数受 `max_pending_tasks` 上限约束。
- 队列满时**显式拒绝**，返回结构化错误，而不是阻塞、重试或丢弃。
- 每个任务都有可追踪的状态机，终态只能提交一次。
- 超时、取消、完成之间存在竞争，必须保证只有一个终态胜出。

## 2. 当前实现

不引入 Redis / Kafka / 数据库。调度器是进程内实现，分布在以下模块：

| 模块 | 职责 |
| --- | --- |
| `pico/core/worker_manager.py` | `WorkerManager`：会话内 worker 状态入口、`spawn`/`continue_task`/`stop_task`/`to_dict`/`metrics` |
| `pico/core/worker_background.py` | admission、queue、capacity release、timeout watcher、shutdown、worktree 创建/清理 |
| `pico/core/worker_state.py` | 状态机常量和 `transition_worker_state`（CAS 风格单次提交）、指标记录 |
| `pico/core/worker_execution.py` | `run_worker`：子 Runtime 执行、终态提交、handoff/result 契约 |
| `pico/core/worker_tasks.py` | `WorkerTask` 数据对象、会话 items 索引、外部返回载荷 |
| `pico/core/worker_recovery.py` | resume 后的任务重建策略 |

配置（`pico/core/runtime.py`，均有默认值）：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `max_concurrent_workers` | `2` | 同时运行的 Worker 上限 |
| `max_pending_tasks` | `16` | 等待队列上限 |
| `worker_timeout_seconds` | `60` | 单个 Worker 的执行预算 |
| `max_pending_workers` | 兼容别名 | 早期试验接口别名，等价于 `max_pending_tasks` |

## 3. 目标数据流

```text
spawn / continue_task
        │
        ▼
   new_task（创建会话条目 + 提前建 worktree）
        │
        ▼
  admit_background_task（_lock 临界区）
        │
   ┌────┴─────────┬───────────────┐
   ▼              ▼               ▼
 started       queued          rejected
   │              │               │
   ▼              ▼               ▼
worker thread   FIFO 队首      清理 worktree
   │          等待 capacity     返回结构化错误
   ▼              │
run_worker        │
   │   ◄──────────┘（terminal → start_next_queued）
   ▼
transition_terminal（唯一终态入口）
   │
   ▼
capacity release + notification（幂等键）+ handoff（幂等键）
```

## 4. Scheduler 数据结构

- `session["workers"]`：跨进程持久化的字典，含 `next_id` 与 `items`。
  - `items`：每个 Worker 的持久化记录，含 `id`、`description`、`status`、`write_scope`、`worktree_path`、`base_commit`、`created_at`、`timeout_seconds`、`admission`、`execution_sequence`、`change_handoff`、`result`、`notification_delivery_keys` 等。
- `manager._tasks`：进程内 `WorkerTask` 对象（含存活 thread），仅当前进程可见。
- `manager._lock`：`threading.RLock`，admission、状态迁移、指标更新共用同一临界区。
- `manager._notifications`：`queue.Queue`，Worker 生产、Engine/CLI/TUI 消费。
- `manager.state["metrics"]`：累计指标（accepted/queued/rejected/…/queue wait）。

## 5. Worker 状态机

```text
idle ──► starting ──► running ──► completed
          │            │  └─────► failed
          │            │  └─────► timed_out（timeout watcher）
          │            │  └─────► canceled（task_stop / session shutdown）
          │            │  └─────► stopped（协作停止后线程返回）
          └──► queued ──┴─► starting
                    │
                    └─► canceled
任意未启动路径 ──► rejected
```

- 运行态：`starting / running / stopping`。
- 终态：`completed / failed / timed_out / stopped / canceled / rejected`。
- `transition_worker_state(manager, worker_id, expected_states, new_state, *, reason, actor)` 是**唯一终态提交入口**：只在 `expected_states` 命中时迁移；终态不可被第二次覆盖（后到者记 `duplicate_terminal_transition` 并返回 `None`）；每次迁移记录旧状态、新状态、原因、actor 到 `last_transition`，并发送 `worker_state_transition` 事件。

## 6. Admission

`admit_background_task` 在 `_lock` 内原子决策，防止并发 submit 绕过上限：

```text
active < max_workers      → starting，立即启动
active ≥ max_workers 且
  pending < max_pending   → queued，记录 prompt 等待
pending ≥ max_pending     → rejected
```

- 决策结果写入 `item["admission"]`（action、outcome、admitted_at、started_at、execution_sequence）。
- 事件：`worker_submitted` / `worker_queued` / `worker_started` / `worker_rejected`。
- 同步 fallback（无 `model_client_factory` 时）：worker 在父线程串行执行，天然无并发，通过 `_mark_starting` 走同一状态机，不绕过终态提交。

## 7. Pending Queue

- FIFO：`start_next_queued` 按 `manager._tasks` 插入顺序取第一个 `queued` 任务。
- 队列等待时间以 `queued_monotonic` 记录，启动时计入 `queue_wait_ms_avg / max`。
- queued 任务在 session 中持久化，resume 后可重建执行实体（见第 12 节）。

## 8. Capacity Release

- 完成/失败/超时/取消都会在 terminal transition 后调用 `start_next_queued`。
- `start_next_queued` 在 `_lock` 内先查 `active < max_workers`，再原子迁移队首 `queued → starting`，随后在锁外启动线程，避免持锁执行模型调用。
- 释放容量不依赖外部信号，全部收敛到这一个入口。

## 9. Backpressure

队列满时不得阻塞、无限重试或静默丢任务。返回结构化载荷：

```json
{
  "task_id": "agent_3",
  "status": "rejected",
  "error": {
    "code": "worker_queue_full",
    "retryable": true,
    "running": 1,
    "pending": 16,
    "max_workers": 2,
    "max_pending": 16
  }
}
```

- 被拒绝的**写 Worker 不进入 `delegated_review`**：只有委派真正被接受（queued/started）才锁住父 Agent。
- 被拒绝任务提前创建的 worktree 立即清理（`remove_worktree`），失败通过 `worker_worktree_remove_failed` 事件暴露。

## 10. Timeout

- 每个 Worker 启动时附带一个 `_watch_timeout` 监视线程，`timeout_seconds` 由 admission 参数或全局配置决定。
- Python 线程不能安全强杀：watcher 到点后先**验证当前状态仍为 `running`**，再请求协作式停止（`request_stop` → 子 Runtime `abort_current_turn`）。
- watcher 以 `{running} → timed_out` 提交终态；已终止（或已被 session reset 清理）的 watcher 只能安全早退，不得抛 `unknown worker`。
- timeout 是**系统判定超预算**，与外部取消语义区分。

## 11. Cancellation

- `task_stop`（外部主动取消）与 `clear_session`/`resume` 的 `shutdown_workers` 都走同一套语义。
- running/starting：请求协作停止 + `{starting, running} → canceled`。
- queued：`cancel_queued_worker` 单一入口：`{queued} → canceled`、清 pending prompt、清理 worktree、发 `worker_canceled`、幂等通知；会话关闭时不释放队首，外部取消时释放队首。
- 已取消 Worker 的工作线程随后返回时，终态已是 `canceled`，`run_worker` 的第二次终态提交被拒绝，不回写 result，不发第二次通知。

## 12. Resume

- `resume_session` 先 `shutdown_workers` 停掉旧执行实体，再重建 `WorkerManager`。
- `recover_workers_after_resume`：
  - `queued` → `restore_queued_task` 重建执行实体并重新入队，等待容量。
  - `starting / running / stopping` → 本地执行实体（线程）已随旧进程消失，标记 `failed`（reason=`resume_execution_entity_missing`），不假装仍在运行。
  - 终态（completed/failed/timed_out/canceled/rejected）→ **不重启**，保持终态与结果契约。
- `session["workers"]` 随会话持久化，天然包含 resume 所需的字段（含 `started_at`、`admission`、`base_commit`、`change_handoff`）。

## 13. Race Condition 清单

| 竞争 | 处理 | 锁/机制 |
| --- | --- | --- |
| completion vs timeout | 后到者提交终态被拒，记 duplicate | `transition_worker_state` CAS |
| completion vs cancel | 同上 | 同上 |
| cancel vs timeout | 同上 | 同上 |
| session reset vs old watcher | 旧条目被丢，watcher 找不到条目安全早退 | `_find_item` 判空 |
| resume vs old worker state | 先 shutdown 旧实体，再重建；active 无实体即 failed | `recover_workers_after_resume` |
| notification duplicate | 按 `worker_id:execution_sequence:terminal` 幂等键去重 | `publish_terminal_notification` |
| handoff duplicate | 按 `worker_id:execution_sequence:handoff` 幂等键 | `build_change_handoff` |
| 并发 submit 绕过上限 | 原子 admission | `_lock` 临界区 |

## 14. 替代方案

- **有界队列 + 拒绝**（采用）：资源边界可控、失败可解释；父 Agent 可缩小委派或继续只读分析。
- **阻塞**：父 Agent 卡住，无法自我调整；违背"协作式"定位。
- **丢弃/降级**：静默丢任务违反可审计交付原则。
- **caller-runs**：在无后台执行器时恰好用同步 fallback 实现；作为主路径会让父 Agent 退化成串行。
- **concurrent.futures.ThreadPoolExecutor**：提供线程池与 Future，但队列无界、拒绝语义要自己叠加，且与现有 session/checkpoint/通知体系割裂；最终选择在 `WorkerManager` 内维护有界队列，保持状态单一来源。
- **信号强杀 / 子进程隔离**：进程级 kill 可终止 shell/子进程，但线程路径必须协作式停止；当前采用协作式为主。

## 15. 并发状态评审（Phase 4：六项共享状态）

| 状态 | 谁读 | 谁写 | 跨线程 | 锁 | 重复调用会怎样 |
| --- | --- | --- | --- | --- | --- |
| `session["workers"]["items"]` | admission、工作线程、watcher、stop、resume、`to_dict`/`metrics` | admission 写 status/admission；工作线程写 result/handoff；watcher 写 timed_out；stop/shutdown 写 canceled | 是（主线程 + 工作线程 + watcher） | `_lock` | 状态迁移经 `transition_worker_state` CAS；重复终态提交被拒并记 duplicate |
| pending queue（queued items + `_tasks`） | `start_next_queued`、`metrics` | `admit_background_task` 入队；`cancel_queued_worker` 取消 | 是 | `_lock`（决策原子）；FIFO 扫描在锁内 | 无 queued 时 `start_next_queued` 幂等早退；重复 cancel 终态已存在，提交被拒 |
| `session["workers"]`（会话级 worker_state） | resume、`to_dict`、report | 各路径经 `_save` 持久化 | 跨进程（session 文件） | `_lock` 保护进程内镜像；文件由 `session_store` 原子替换 | 重复读幂等；resume 时终态不重启、queued 重建、active 无实体标记 failed |
| notifications（`_notifications` 队列） | drain（协调者独占） | `publish_terminal_notification` | 是（生产/消费分离） | `queue.Queue` + `_lock` 维护 delivery_keys | 幂等键 `<id>:<seq>:terminal` 在 pending/delivered 去重，重复发布返回 False |
| handoff store（`change_handoff`） | 父 Agent review、report 生成 | `run_worker` 在工作线程写 | 工作线程写、父线程读 | `committed.update` 在 `_lock` 内 | 每执行轮次 `idempotency_key=<id>:<seq>:handoff` 唯一；不覆盖历史 |
| capacity counter（running/pending） | admission、`metrics_snapshot` | 不独立存储，实时从 items 的 status 派生 | 是 | 只读派生，无独立写入 | 重复读幂等，无副作用；admission 决策在 `_lock` 内取数 |

评审结论：没有第二套状态；所有跨线程写入都经 `transition_worker_state` 或 `_lock` 保护；终态、通知、handoff 都有幂等键，重复调用安全。

## 16. 测试方案

- `max_workers=2` 时同时提交 3 个任务，第 3 个进入 `queued`。
- pending 满后新任务 `rejected`，返回结构化错误。
- Worker 完成自动释放 slot 并启动队首（FIFO）。
- `running → timed_out`、`queued → canceled`、`running → canceled`。
- completion vs timeout 竞争只有一个终态；通知幂等。
- cancel 后线程晚返回不回写 result、不重复完成。
- session reset 后旧 watcher 静默退出。
- resume 不重启 terminal worker；queued 重新入队；孤儿 running 标记 failed。
- 被拒绝的写 Worker 不进入 `delegated_review`，且清理其 worktree。
- 全量回归见 `tests/test_agent_workers_acceptance.py`。
