# 03：可靠 Worker Runtime

## 工程问题

现有 worker 能启动子 agent，但 timeout、并发队列、结构化交付和工作区隔离不足。并行写入时，主工作区可能受到冲突或半完成修改影响。

## 最小范围

- 状态：`queued`、`running`、`completed`、`failed`、`canceled`、`timed_out`；
- 并发限制、队列、协作式取消和 timeout；
- 结构化结果：摘要、changed paths、验证命令/结果、run 证据和错误码；
- 写 worker 使用 Git worktree，主工作区不被直接污染；
- 状态与结果进入 session、event 和 report。

## 非目标

不实现分布式队列、线程强杀、自动冲突解决、远程 worker 或崩溃后的自动续跑。

## 实际问题

结构化结果首次接入时，child task state 尚未创建就被读取，造成后台 worker 异常并让主 Agent 提前结束。详见 [INC-0003](../incidents/INC-0003-worker-result-state-order.md)。

写 worker 在 Git 仓库内且具备 write scope 时创建 `.worktrees/<worker-id>` 的 detached worktree；child runtime 的 workspace 指向该目录，session/report 仍由父 runtime 统一保存。非 Git fixture 和只读 Explore worker 保持原有路径，保证轻量测试与只读探索没有额外 Git 依赖。

## 验证证据

- `tests/test_agent_workers_acceptance.py`：14 passed（2026-08-11，19.32s）。
- 端到端 fixture 初始化 Git 仓库，写 worker 在 detached worktree 创建 `notes/worker.txt`；断言该文件存在于 worktree、主工作区不存在，并记录基线 commit。
- Windows 环境中后台 worker 创建的耗时约为 0.58s；异步验收阈值从 0.5s 调整为 1.0s，仍验证调用方不等待 worker 完成，避免把机器启动抖动误判为同步阻塞。
- 并发上限设为 1 的测试中，第 2 个后台 worker 先进入 `queued`；第 1 个 worker 完成后才开始第 2 个，最终两者均为 `completed`。

## 当前边界

worktree 由会话保留以便复核变更；本迭代不自动合并、清理或解决冲突。工作流由主 Agent 在审阅 diff 后显式决定是否采纳。

`runtime.py` 存在本迭代前已有的全文件 Ruff 存量告警；本次没有为清零告警而扩张重构范围。新增的 worker manager 和验收测试通过其专项 Ruff 检查。

在全量回归中，`worker_manager.py` 被架构预算测试发现超过 220 行。已将后台调度和 worktree 隔离拆分至 `worker_background.py`，manager 收敛到 204 行；详见 [INC-0005](../incidents/INC-0005-worker-manager-entropy-budget.md)。
