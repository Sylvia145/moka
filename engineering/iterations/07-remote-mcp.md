# Iteration 07：Remote MCP reliability boundary

## 目标

将 Moka 的 MCP 能力从本地 stdio 扩展到 Streamable HTTP，同时保持工具权限、审计和评测统一，并处理远程服务的网络不确定性。

## 交付

- `McpClient` 公共接口与 stdio/HTTP 客户端工厂；
- Streamable HTTP 的 initialize、notification、tools/list、tools/call、JSON、SSE 和 session 支持；
- HTTP 超时、连接、鉴权、服务端、session、响应格式和响应大小错误分类；
- Token 仅通过环境变量名称引用，Authorization Header 不进入错误与 artifact；
- 读取操作有限重试，`tools/call` 结果未知时不重试；
- HTTP 发布策略 MCP 与 Worker 发布治理对照场景。

## 关键工程决策

1. 传输层与 Tool Registry 解耦，避免 HTTP 成为权限和审计旁路；
2. 写工具优先保证不重复执行，而非追求自动恢复率；
3. 每个 Runtime 持有独立 MCP session，session 失效只恢复安全读取路径；
4. 以 localhost 独立 HTTP 服务验证协议，不将完整 OAuth、远程部署和旧协议兼容堆入本轮。

## 验证

- 单元与协议测试覆盖 JSON、SSE、session、鉴权、响应限额、超时和结果未知；
- HTTP 发布治理场景与 stdio 场景使用同一业务 Verifier；
- 真实 DeepSeek HTTP Dogfood 运行 3 次，结果见实验记录。

## 当前限制

- Bearer Token 仅支持预配置环境变量，不是完整 MCP OAuth Client；
- 测试服务运行在独立本地 HTTP 进程边界，未部署公网服务；
- 主 Agent 在 Worker 完成后仍可能尝试自行写入主工作区；现有业务 Verifier 能拦截该行为，但尚未实现“委派后父 Agent 自动降权”的通用策略。
