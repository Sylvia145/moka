# Experiment 02：stdio 与 Streamable HTTP MCP 对照

- 日期：2026-08-12
- Provider：配置的 DeepSeek profile
- 业务场景：Billing API 发布治理，策略版本 `billing-release-v1`

## 对照目的

验证将发布策略 MCP 从本地 stdio 子进程切换为独立 HTTP 服务后，Moka 仍能保持相同的策略读取、Worker worktree 隔离、`pending_review` 交接和业务阻断判断。

## 确定性对照

HTTP Server 同时覆盖 JSON 与 SSE 工具发现。使用 ScriptedModelClient 的发布治理测试通过全部业务断言：策略读取、Worker 完成、报告只出现在 worktree、主工作区未改动、受保护文件未改动和交接单待审核。

## 真实模型结果

| Artifact | 结果 | 工具步数 | 说明 |
|---|---|---:|---|
| `20260812-release-governance-http-run1` | passed | 5 | 全部业务检查通过。 |
| `20260812-release-governance-http-run2` | passed | 9 | 全部业务检查通过；模型探索步骤更多。 |
| `20260812-release-governance-http-run3` | failed | 10 | Worker 已完成，但主 Agent 继续探索并在主工作区写报告；`main_workspace_unchanged` 拦截，达到步骤上限。 |

结果为 2/3，而非选择性报告为 3/3。失败不归因为远程 MCP：策略调用、Worker 和报告均成功；失败归类为模型未遵守委派后的职责边界。

## 委派所有权 guard 复测

在 Iteration 08 后，父 Agent 在 scoped write worker 启动后切换为
`delegated_review`。它不能再写主工作区，只有只读 MCP、读取和 worker
控制能力。三次真实 HTTP 复测的 raw artifact 分别为：

| Artifact | Result | Observation |
|---|---|---|
| `20260812-release-governance-http-guard-run1` | passed | Worker report and pending-review handoff completed; main workspace unchanged. |
| `20260812-release-governance-http-guard-run2` | failed | Guard denied parent write correctly; worker audit JSON hit a transient Windows file lock (INC-0011). |
| `20260812-release-governance-http-guard-run3` | passed | Same scenario passed after bounded RunStore retry was added. |
| `20260812-release-governance-http-guard-run4` | passed | Second post-retry run passed with the same business assertions. |

The guard removes the original model-boundary failure. The one retained failed
run is a Windows artifact-persistence failure, not a selected-away result.
After the retry change, the additional sample is 2/2 passed.

## 网络失败注入

对接收 `tools/call` 后延迟响应的服务端，Moka 返回 `mcp_outcome_unknown`，并断言服务端仅收到一次调用。该策略避免创建工单、触发发布等潜在写操作被网络重试重复执行。

## 结论

Moka 的 HTTP 传输已通过确定性协议测试和真实端到端验证。初始真实
dogfood 暴露了父 Agent 在委派后仍能写主工作区的职责边界缺口；Iteration 08
已将其收敛为运行时 `delegated_review` 权限策略，并保留 guard 前后的全部
artifact。当前限制是：MCP 的只读判断依赖服务端 `readOnlyHint` 注解，Bearer
Token 仍为预配置环境变量，未实现完整 OAuth Client 或自动合并 worker handoff。
