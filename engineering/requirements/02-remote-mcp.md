# M7：远程 MCP 传输需求

## 业务问题

Moka 已能通过 stdio 调用本地 MCP Server，但企业内部的发布策略、缺陷管理或知识服务通常是独立部署的服务。将 Agent 接入这类服务时，网络故障和凭据安全会使“工具调用成功”不再是一个简单的进程读写问题。

## 本轮目标

1. 支持 MCP Streamable HTTP 的 JSON 与 SSE 响应；
2. 保持本地 stdio MCP 的工具、权限和 Trace 行为不变；
3. 将远程服务的 session、超时、错误分类和响应限制纳入运行时；
4. 对有副作用的 `tools/call` 采取保守策略：请求结果不确定时不自动重试；
5. 支持从环境变量读取预配置 Bearer Token，且不得将凭据写入 artifact 或模型上下文。

## 非目标

- 完整 OAuth 2.1 浏览器授权、PKCE 和 Token 刷新；
- 旧版 HTTP+SSE 传输兼容；
- 通用远程服务发现、负载均衡或多租户网关；
- 模型自行指定 MCP URL。

## 验收条件

- Streamable HTTP 完成 `initialize`、`notifications/initialized`、`tools/list` 和 `tools/call`；
- JSON 和 SSE 响应均有自动测试；
- session 失效后的安全重新初始化有测试；
- 有副作用调用的结果不确定时返回明确错误，且无第二次调用；
- 远程响应、Authorization Header、session ID 均不会泄漏到 Trace 或最终报告；
- stdio MCP 与发布治理已有回归通过；
- HTTP 发布策略场景保留可复现 artifact。
