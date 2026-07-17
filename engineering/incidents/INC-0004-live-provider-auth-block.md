# INC-0004：真实提供商冒烟评测认证失败

- 日期：2026-08-11
- 严重度：阻塞真实模型指标，不阻塞本地确定性验收
- 影响：无法产生可用于简历的真实模型通过率或时延数据

## 现象

对 GPT、Claude 和 DeepSeek 的本地配置分别执行单题、温度 0 的固定基准冒烟时，请求均到达提供商后返回 HTTP 401，运行在第一次模型调用即以 `model_error` 停止；没有工具调用，也没有修改 fixture。

## 已确认事实

- 配置解析能发现 provider、模型、端点和密钥字段；不记录其具体值。
- 三个原始结果位于忽略的 `artifacts/engineering/live-smoke-<provider>.json`，包含运行 ID、状态和错误类型。
- 三次运行的 0/1 仅表示认证失败，**不代表 Agent 的能力通过率**。

## 处理与后续

不通过替换模型、伪造输出或将确定性脚本结果包装为真实模型结果来绕过。待用户更新有效的本地 provider 凭据后，使用同一份单题冒烟基准重跑；成功后再决定是否执行多题、多次的正式评测。

## 2026-08-16 更新：定位到具体根因

- DeepSeek（直连 `api.deepseek.com`）已连通，真实业务 dogfood 全部通过（见 iteration 11）。
- `anthropic` 此前被宿主通用环境变量静默路由到 DeepSeek（见 [INC-0012](INC-0012-provider-config-host-env-injection.md)），修复后正确指向 `right.codes/claude`。
- `openai` / `anthropic` 现在的失败形态已从 401 演进为 403：`right.codes` 返回「API Key 不允许访问该渠道，请前往令牌管理界面修改令牌权限」。这是代理端渠道权限配置，非 Moka 代码缺陷，需用户在 right.codes 令牌管理界面开通 codex/claude 渠道。
