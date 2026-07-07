# ADR-002：Worker 只生成待审阅交接单，不自动合并

## 决策

写 Worker 在 detached Git worktree 内执行，并在结果合同中输出 change handoff：base commit、变更路径、diff 摘要、验证证据、错误码、风险与 `review_required`。

## 取舍

| 方案 | 结论 |
| --- | --- |
| 直接写主工作区 | 拒绝：失败或并发任务会污染发布候选仓库。 |
| Worker 自动 merge | 拒绝：发布阻塞项和配置风险仍需人工决策，自动 merge 超出授权。 |
| worktree + 人工审阅交接单 | 采用：副作用隔离，可复核，可将采纳责任保留给发布负责人。 |

## 残留限制

本轮不实现自动冲突解决、远程 PR 创建或审批流；交接单只提供决定所需的最小证据。
