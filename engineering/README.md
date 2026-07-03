# Moka 工程迭代记录

本目录记录 Moka 面向可靠 Agent Runtime 的增量开发。内容只保留可复现的工程事实：设计选择、实现、测试、指标和实际问题；原始 trace、敏感配置及临时排障材料保留在被忽略的 `.local-notes/engineering/`、`artifacts/` 和 `.pico/` 中。

## 本轮结论

三项代码迭代已完成并通过组合回归：轨迹评测、受策略约束的 stdio MCP、可靠 worker。固定 12 题 harness 可复现通过；一次真实模型冒烟因认证失败未形成能力指标，详见 [INC-0004](incidents/INC-0004-live-provider-auth-block.md)。

## 记录导航

1. `00-baseline.md`：建立与后续功能相关的可信基线。
2. `iterations/01-agent-evaluation.md`：基于 trace 的轨迹评测与回归报告。
3. `iterations/02-mcp-gateway.md`：受权限和审计约束的 stdio MCP 工具接入。
4. `iterations/03-worker-runtime.md`：具备超时、取消、结果合同和 worktree 隔离的 worker。

每一阶段完成时，会在相应文档中补充实际测试命令、运行结果、指标、提交和残留限制。
