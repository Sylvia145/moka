# INC-0010：MCP initialized 通知的 202 空响应被误解析

- 日期：2026-08-12
- 严重度：中
- 范围：Streamable HTTP Client 首次协议测试

## 现象

HTTP MCP Server 在收到 `notifications/initialized` 后返回 `202 Accepted` 且无响应体。第一版 Client 仍尝试按 JSON-RPC 结果解析空响应，导致所有 HTTP 初始化失败。

## 根因

stdio 的通知写入没有 HTTP 响应语义，旧实现的心智模型直接迁移到了 HTTP。Streamable HTTP 中，notification 不携带 JSON-RPC ID，服务端可以以 202 接受且不返回 body。

## 修复

为请求层增加 `expect_body` 语义：notification 允许空 body，普通 request 仍要求与 request ID 匹配的 JSON 或 SSE 响应。

## 回归

JSON、SSE、session 恢复、超时和业务发布治理对照测试均覆盖 initialized notification。
