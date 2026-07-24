# ADR-008：远程 MCP 写工具采用幂等键安全重试

## 决策

为远程 streamable-HTTP MCP 增加**默认关闭**的幂等键安全重试：`McpServerConfig.max_idempotent_retries`（默认 `0`）。开启后，`tools/call` 在结果未知四类故障时以相同 `Idempotency-Key` 头重试，服务端按 key 去重，使副作用精确一次。默认契约（ADR-006）不变：未开启时 `tools/call` 依然固定不重试。

## 背景

ADR-006 预留路径："只有未来服务端提供可靠幂等键契约时，才允许对特定写工具增加安全重试。"本 ADR 落实该路径。`tools/call` 一旦发出，传输层失败（超时/断连/截断/5xx）时客户端无法判断服务端是否已执行；单纯重试会重复副作用，单纯不重试则表面成功率受限。幂等键契约让"重试并去重"成为安全选项。

## 取舍

- 无差别重试：提高表面成功率，但重复执行写操作，被 ADR-006 否决；
- 无差别不重试：最安全（现状），但写路径瞬时故障完全无法恢复；
- 幂等键契约重试：默认关、需服务端配合（识别并去重 `Idempotency-Key`），副作用精确一次。

选择幂等键契约重试。服务端忽略该头时行为退化为无差别不重试（客户端仍重试，但重复副作用，详见验证 I 场景）；因此该选项仅应在接入方确认服务端实现去重契约后开启。

## 契约细节

- **重试集合**：仅结果未知四类 `mcp_http_timeout` / `mcp_http_connect_failed` / `mcp_http_server_error` / `mcp_invalid_response`。`unauthorized` / `session_expired` / `redirect_blocked` / `response_too_large` / `remote_error` 为确定性拒绝，永不重试。
- **Key 生命周期**：每次逻辑 `tools/call` 生成一个不可预测的 256 位 key；该次调用的所有内部重试复用该 key。即使 tool 和参数相同，后续独立调用也生成新 key，避免服务端误去重合法的第二次写入。
- **与读重试隔离**：`max_retries` 仅治理 `initialize`/`tools/list` 等无副作用调用；写走独立幂等循环，互不渗透。
- **Session**：重试间不重置 session（传输层失败，session 仍有效）；`_initialized=False` 时惰性重新握手。
- **Trace**：成功路径在工具元数据记录 `mcp_idempotent_retries`；失败路径错误码始终 `mcp_outcome_unknown`，上层不把传输细节误解释为"未执行"。
- **生产服务端要求**：去重缓存必须有 TTL 与容量上限，避免无限增长；本仓库的共享测试服务器（`pico/evaluation/mcp_http_fault_server.py`）为确定性测试不做回收。

## 验证

`tests/test_mcp_http.py` 覆盖：服务端去重时重试恢复且副作用一次、默认关闭不发 key、key 跨重试稳定、未恢复仍抛 `mcp_outcome_unknown`、unauthorized 不重试、key 派生稳定且碰撞安全、Agent 元数据记录重试次数。`scripts/mcp_http_fault_injection.py` 输出 A–K 对照表（H vs I：服务端去重时 `side_effects=1`、忽略头时 `side_effects=2`），记录于 `docs/benchmark/MCP远程故障注入与幂等重试.md`。
