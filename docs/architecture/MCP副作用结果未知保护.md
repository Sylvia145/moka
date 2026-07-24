# MCP 副作用结果未知保护

## 合同

对远程 MCP 的 `tools/call`，一旦请求已可能送达远端而客户端无法确认结果，Moka 不自动重试，并以 `mcp_outcome_unknown` 返回。该错误不表示远端未执行；调用方必须先核验外部状态，才可决定是否补偿或人工重试。

`initialize`、`notifications/initialized` 与 `tools/list` 不承载业务副作用，仍可按 `max_retries` 有限重试。`tools/call` 默认固定非重试；**除非** `max_idempotent_retries > 0`（opt-in，见 ADR-008），此时结果未知四类故障以相同 `Idempotency-Key` 头重试——仅在服务端按 key 去重时安全，服务端忽略该头则退化为重复副作用。

## 结果未知分类与证据

`McpStreamableHttpClient.call_tool()` 将以下底层失败统一映射为 `mcp_outcome_unknown`：

| 故障窗口 | 底层分类 | 远端执行可能性 |
| --- | --- | --- |
| 服务端已提交副作用，响应超时 | `mcp_http_timeout` | 可能已执行 |
| 服务端已提交副作用后断开连接 | `mcp_http_connect_failed` | 可能已执行 |
| 响应被截断或无法解析 | `mcp_invalid_response` | 可能已执行 |
| 服务端已提交副作用后返回 5xx | `mcp_http_server_error` | 可能已执行 |

异常对象保留 `cause_code` 供本地诊断；对 Agent、Trace 与指标的稳定错误码始终是 `mcp_outcome_unknown`，避免上层把传输细节误解释为“未执行”。原始异常通过异常链保留。

## 故障注入证据

`tests/test_mcp_http.py` 使用本地 `ThreadingHTTPServer`，在服务端记录副作用提交后分别注入四类故障窗口。每例均设置 `max_retries=3`，并断言：

- `tools/call` 仅收到 1 次请求；
- 服务端副作用提交记录仅 1 条，JSON-RPC 请求 ID 无重复；
- 客户端抛出 `McpOutcomeUnknownError`；
- Agent 工具元数据记录 `tool_error_code=mcp_outcome_unknown`。

相邻的只读对照测试让 `tools/list` 连续两次返回 5xx，配置 `max_retries=3` 后第三次成功，证明重试能力仍保留在无副作用调用，而非被全局关闭。

该证据为确定性的本地协议与传输故障测试，不代表真实第三方系统的幂等写入验证；若接入外部写服务，仍应在其预发布环境验证幂等键与补偿语义。

## 幂等键安全重试

默认契约之上，`McpServerConfig.max_idempotent_retries` 提供 opt-in 的幂等键安全重试（ADR-008）：开启后 `tools/call` 在结果未知四类故障时携带同一个 `Idempotency-Key` 头重试，服务端按 key 去重使副作用精确一次。每次逻辑调用生成独立的随机 key，只有该次调用的内部重试复用它，避免两次参数相同的合法写操作被误去重。重试仅限 `timeout/connect_failed/server_error/invalid_response`；`unauthorized/session_expired/redirect_blocked/response_too_large/remote_error` 为确定性拒绝，永不重试。完整 A–K 故障注入对照见 `docs/benchmark/MCP远程故障注入与幂等重试.md`。
