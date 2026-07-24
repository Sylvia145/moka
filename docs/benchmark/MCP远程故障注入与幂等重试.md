# MCP 远程故障注入与幂等重试

> 最近一次运行：2026-08-30。该报告来自本地 `ThreadingHTTPServer` 的确定性故障注入，不依赖第三方 MCP 或生产凭据。

## 目的

验证远程 streamable-HTTP MCP 在读操作与带副作用 `tools/call` 上使用不同的失败语义：默认写操作不重试；当服务端明确支持 `Idempotency-Key` 去重时，调用方可以选择启用有限重试。

## 复现

```powershell
uv run python scripts/mcp_http_fault_injection.py
```

## 结果

| 场景 | 故障窗口 | 幂等重试 | 服务端调用数 | 副作用提交数 | 客户端结果 |
| --- | --- | --- | ---: | ---: | --- |
| A | `tools/list` 正常响应 | 关闭 | 0 | 0 | 成功，读调用 1 次 |
| B | `tools/list` 连续 5xx 两次 | 关闭 | 0 | 0 | 成功，读调用 3 次 |
| C | `tools/list` 会话过期 | 关闭 | 0 | 0 | 成功，初始化 2 次 |
| D | 提交后响应超时 | 关闭 | 1 | 1 | `mcp_outcome_unknown` |
| E | 提交后断开连接 | 关闭 | 1 | 1 | `mcp_outcome_unknown` |
| F | 提交后截断响应 | 关闭 | 1 | 1 | `mcp_outcome_unknown` |
| G | 提交后返回 5xx | 关闭 | 1 | 1 | `mcp_outcome_unknown` |
| H | 首次断连，服务端按 key 去重 | 开启 | 2 | 1 | 成功 |
| I | 首次断连，服务端忽略 key | 开启 | 2 | 2 | 成功，暴露重复副作用风险 |
| J | 提交后响应超过体积上限 | 关闭 | 1 | 1 | `mcp_response_too_large` |
| K | 未授权 | 开启 | 0 | 0 | `mcp_http_unauthorized` |

## 合同与限制

- `tools/call` 的默认配置不重试；结果未知统一暴露为 `mcp_outcome_unknown`，并保留底层 `cause_code`。
- `max_idempotent_retries` 默认值为 `0`。开启后，每个逻辑调用生成唯一的随机 `Idempotency-Key`，该次内部重试复用同一 key。
- H 依赖服务端实现持久化去重；I 说明服务端未实现该合同会重复副作用，因此配置必须由接入方显式确认。
- 测试服务器为确定性验证工具，未模拟生产环境中的去重缓存 TTL、容量控制或跨进程故障恢复。
