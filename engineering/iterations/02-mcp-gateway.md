# 02：Policy-aware MCP 工具网关

## 工程问题

外部 MCP 工具若绕过内部 ToolSpec、权限和证据链路，会使 Agent 的安全与可观测性失效。第一版需要以最小 stdio 协议接入，验证动态发现与统一治理能共存。

## 最小范围

- stdio server 配置、初始化、`tools/list` 与 `tools/call`；
- MCP schema 适配为内部注册工具，名称使用 server namespace；
- 复用既有参数校验、permission、tool policy、重复调用防护和 artifact 处理；
- mock server 覆盖确定性测试，并保留一个真实演示场景；
- 处理启动、协议、参数、超时和 server 退出错误。

## 非目标

不支持 HTTP/SSE、A2A、工具市场、复杂工具检索或高可用 server 管理。
