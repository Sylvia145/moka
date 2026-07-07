# ADR-001：发布规则通过 stdio MCP 输入

## 决策

将版本化发布规则作为本地 stdio MCP 工具返回，而不是硬编码进 prompt 或直接读取 fixture 文件。

## 背景与备选方案

| 方案 | 结论 |
| --- | --- |
| 将规则写死在系统 prompt | 拒绝：规则无法独立版本化、审计和替换。 |
| 主 Agent 直接读取本地策略文件 | 拒绝：无法验证外部工具接入是否经过统一治理。 |
| stdio MCP policy tool | 采用：复用现有 schema、risk、trace 和权限链路，且可用 mock fixture 重现。 |
| HTTP/SSE MCP | 暂不采用：本轮不需要远程连接、鉴权和连接池，增加范围而不增加业务证据。 |

## 代价与边界

stdio server 与 Agent 同机启动，适合受控本地 fixture，不等同于生产级远程策略服务。规则只返回发布审查约束，不授予写权限。
