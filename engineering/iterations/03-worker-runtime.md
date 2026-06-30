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
