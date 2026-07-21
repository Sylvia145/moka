# 有界 Worker 调度设计

## 问题与目标

仅限制运行线程会把压力转移到无限 pending 列表。本设计为本地 Worker 增加 `max_concurrent_workers`（默认 2）和 `max_pending_tasks`（默认 16），并以会话持久化指标说明资源边界与失败原因。

## 数据流

`spawn/continue -> admission 锁 -> started | queued | rejected -> worker thread -> terminal transition -> capacity release -> 启动 FIFO 队首`。

## Admission 与 Backpressure

- active 小于 `max_workers`：接受并启动。
- 否则 pending 小于 `max_pending`：接受并入队。
- 否则：持久化 `rejected`，返回 `worker_queue_full`、实时 `running/pending` 和容量上限；不激活 `delegated_review`。

拒绝而非阻塞或静默丢弃，父 Agent 可据此缩小委派或继续只读分析。

## 状态与竞争

运行状态为 `starting/running/stopping/queued`；终态为 `completed/failed/timed_out/stopped/canceled/rejected`。`transition_terminal` 是完成和 timeout 的单次提交入口：先提交者写入原因与 actor，后到者不覆盖终态且累加重复迁移指标。已终止任务的 watcher 必须早退。

## 指标与测试

指标写入 `session.workers.metrics`：accepted、queued、rejected、完成分类、重复终态提交、未处理线程异常、队列等待次数/总时长/最大时长；`to_dict()` 同时提供实时 running/pending。

测试覆盖并发上限、FIFO 入队、pending 满结构化拒绝、完成释放容量、timeout 释放容量、cancel queued、completion-timeout 竞争、旧 watcher 和通知去重。
