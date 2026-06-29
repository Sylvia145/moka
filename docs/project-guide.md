# Moka 项目导览与迭代指南

> 面向第一次接触本仓库的开发者。本文以当前源码为准，目标不是逐文件解释代码，而是帮助你快速建立系统心智模型、找到关键入口，并能判断后续迭代的优先级。

## 1. 先用一分钟认识 Pico

Moka 是一个运行在本地代码仓库中的轻量 coding agent harness。它把一次自然语言请求变成一段**有边界、可恢复、可审计**的执行过程：组装上下文、调用模型、解析模型输出、执行工具、记录状态，并把最终结果与运行证据持久化到本地。

它的核心价值不在于“又封装了一次模型 API”，而在于模型外部的工程控制：

- **控制面**：runtime 和 engine 决定任务如何推进、暂停与结束。
- **动作面**：tools、权限、策略和 sandbox 限制模型能做什么。
- **上下文面**：context、compact 和 memory 决定模型此刻能看到什么。
- **状态面**：session、checkpoint、todo 和 worker 让任务可以续接。
- **证据面**：trace、task state、report 和 evaluation 让运行可以复盘与回归。

当前包版本是 `0.3.0`，要求 Python 3.10+。源码约有 104 个 Python 文件、1.75 万行；测试目录有 57 个测试文件、约 1 万行，当前可收集 515 个测试。v3 是一次从单循环 agent 到分层 runtime engine 的架构重写，而当前源码已经在 v3 基础上继续长出了上下文编排、LLM handoff 压缩、最终回答就绪门和图片检查等能力。

## 2. 最重要的心智模型

把 Moka 理解成“模型被包在一个本地运行时里”，而不是“CLI 调模型”：

```text
CLI / REPL / TUI / slash command
                |
                v
          Moka runtime 对象图
                |
                v
        Engine.run_turn() 状态机
          |        |        |
          v        v        v
      Context   Provider   ToolExecutor
          |                   |
          v                   v
    memory/compact      permission/policy/sandbox
                \         /
                 v       v
          session / run evidence
```

阅读任何模块时，都先问三个问题：它属于哪个平面？它维护什么状态？它通过什么事件或持久化产物被观察？这样比按文件名逐个阅读更容易理解设计意图。

## 3. 一次请求的真实运行链路

用户从 `moka` / `moka-tui` 进入；内部主链路从 `pico/cli.py` 开始：

1. CLI 解析 provider、模型、工作目录、审批、sandbox、memory、vision 和 final-readiness 配置。
2. `build_agent()` 创建 `WorkspaceContext`、provider client、`SessionStore`，再装配内部 `Pico` runtime。
3. 内部 `Pico` 对象持有 session、memory、tools、workers、权限、context manager/orchestrator 等运行时对象；它本身不是循环。
4. `Pico.ask()` 委托 `Engine.run_turn()` 创建 `TaskState` 和 run 目录，并先落盘用户消息与 `run_started` 事件。
5. `ContextOrchestrator` 取得快照，按上下文压力决定是否 compact，再由 `ContextManager` 组装 prompt。
6. provider 的统一 `complete()` 边界调用 OpenAI-compatible 或 Anthropic-compatible API，并返回文本与 usage metadata。
7. `model_output` 把结果解析成 tool batch、final 或 retry。
8. `ToolExecutor` 依次经过 schema 校验、tool profile、permission、tool policy、重复调用保护和实际 runner。
9. 如果模型给出 final，before-final hook 与 final-readiness gate 会检查证据是否足够；通过后才正式结束。
10. 结束时写入 checkpoint、task state、trace、report，并触发 durable memory 提升和可选 auto-dream。

最值得从源码追踪的一条路径是：

```text
pico/cli.py
  -> pico/core/runtime.py
  -> pico/core/engine.py
  -> pico/core/context_orchestrator.py
  -> pico/core/context_manager.py
  -> pico/providers/base.py
  -> pico/core/model_output.py
  -> pico/core/tool_executor.py
  -> pico/core/completion_governance.py
  -> pico/core/run_store.py
```

## 4. 目录和关键抽象

| 区域 | 关键文件 | 你需要理解的职责 |
| --- | --- | --- |
| 用户入口 | `pico/cli.py`、`pico/tui/`、`pico/commands/slash.py` | 参数与对象装配、TUI/REPL/one-shot 分流、slash command 控制 |
| Runtime | `core/runtime.py`、`core/engine.py` | 内部 `Pico` runtime 持有运行现场，`Engine` 推进一轮状态机；不要把两者重新揉在一起 |
| 上下文 | `context_orchestrator.py`、`context_manager.py`、`context_*`、`compact.py` | section 预算、压力判断、历史保留、替换 ledger、压缩与报告 |
| 记忆 | `features/memory.py`、`context_handoff.py` | session working memory、durable topics、检索、freshness、Dream、LLM 摘要交接 |
| 工具 | `tools/registry.py`、`tools/schemas.py`、`tool_executor.py` | 显式 registry、Pydantic 参数边界、统一执行网关和结果 metadata |
| 安全 | `permissions.py`、`tool_policy.py`、`tool_profiles.py`、`features/sandbox/` | 审批、运行模式能力集、先读后写、路径边界、shell 隔离与 secret redaction |
| 复杂任务 | `plan_mode.py`、`todo_ledger.py`、`worker_*`、`tools/agents.py` | plan 模式、任务账本、受限子 runtime、通知与 write scope |
| Provider | `providers/`、`config/__init__.py`、`model_router.py` | 多协议配置归一化、重试与 usage、vision 专用 client 路由 |
| 多模态 | `content_blocks.py`、`media.py`、`vision.py`、`tools/media.py` | 安全加载 workspace 图片、模型输入块、图片工件与元数据 |
| 完成治理 | `completion_governance.py`、`final_readiness*.py`、`before_final_hooks.py` | final 不等于完成；依据 todo、验证和所需工件决定提醒、警告或阻止 |
| 持久化 | `session_store.py`、`session_events.py`、`run_store.py`、`task_state.py` | 对话时间线、单次运行状态、trace、report 与恢复信息 |
| 评测 | `pico/evaluation/`、`pico/testing.py`、`scripts/`、`benchmarks/` | scripted model、benchmark、context cost、real-session 与人工场景 gate |

三个最重要的对象边界：

- 内部 `Pico` runtime 是运行现场和依赖容器，不应继续吸收所有业务逻辑。
- `Engine` 只拥有 turn 生命周期和状态迁移，不应直接实现 provider、tool 或 UI 细节。
- `ToolExecutor` 是所有模型动作的总闸口；新增工具不能绕过它直接改 workspace。

`tests/test_architecture_boundaries.py` 还为核心文件设置了行数预算。这不是风格测试，而是在防止控制面重新退化成难以审计的巨型模块。

## 5. 五个必须理解的设计点

### 5.1 Context、compact 和 memory 不是一回事

- **Context** 是当前模型调用能看到的 prompt，由稳定 prefix、runtime 状态、skills、memory、history 和当前请求等 section 组成。
- **Compact** 在上下文压力升高时把较早历史替换成摘要；既支持确定性摘要，也支持 LLM 生成结构化 handoff，并保留失败回退。
- **Working memory** 跟随 session，记录当前任务摘要、接触文件、文件摘要和 episodic notes。
- **Durable memory** 位于 `.pico/memory/`，通过 daily log、topic 和 `MEMORY.md` 跨 session 保存稳定事实。
- **Dream** 是后台整理过程，不是主任务必须同步等待的步骤。

当前实现的特点是：上下文已从“固定拼接”进化成可观测的编排过程。`ContextOrchestrator` 会输出是否压缩、触发原因、节省字符数、summary 质量和 usage 等决策证据。

### 5.2 工具安全是多层门，不是一个布尔开关

一次工具调用依次受到这些约束：

1. 工具是否注册、参数是否通过 Pydantic schema。
2. 当前 tool profile 是否允许，例如 plan、readonly、worker、dream。
3. approval policy 是否允许 risky tool。
4. 路径是否仍在 workspace/write scope 内，symlink 逃逸也会被拒绝。
5. tool policy 是否允许，例如修改已有文件前必须有 fresh read，普通搜索不能伪装成 shell。
6. shell 是否需要进入 sandbox，环境变量是否经过 allowlist。
7. 是否在重复无效调用，输出是否需要转存 artifact。

这套分层的意义是把“能执行”和“应该执行”分开，也让拒绝原因进入 trace，而不是只返回一条模糊错误。

### 5.3 Session、run 和 checkpoint 各自回答不同问题

```text
.pico/sessions/<session_id>.json                 # 对话与 session 状态
.pico/sessions/<session_id>.events.jsonl         # 用户可见的持久事件时间线
.pico/runs/<run_id>/task_state.json              # 本次请求目前到哪一步
.pico/runs/<run_id>/trace.jsonl                  # 每一步实际发生了什么
.pico/runs/<run_id>/report.json                  # 本次请求最后如何收口
.pico/runs/<run_id>/artifacts/                   # 过长/二进制工具结果
```

Session 面向跨请求连续性，run 面向一次请求的证据，checkpoint 面向恢复时的 runtime/workspace 一致性。调试时不要只看最终回答，优先看 `stop_reason`、trace 的决策事件和 report 中的 evidence summary。

### 5.4 Plan、Todo、Worker 是控制面，不只是提示词

- 进入 plan mode 会切换 runtime mode 和 tool profile，写操作只能落到 active plan artifact。
- todo ledger 会同时进入 prompt、session state 和 run evidence，最终就绪门能据此发现未完成事项。
- Explore worker 只读；普通 worker 是受限 child runtime，不能再任意生成新的协调层，写入也受 `write_scope` 控制。
- worker 的结果通过 notification 回流主循环，避免 UI 或子线程直接篡改主状态。

### 5.5 “模型输出 final”不等于“任务真的完成”

`final-readiness` 支持 `off`、`warn`、`soft`、`strict`。它会结合验证信号、未完成 todo、所需工件和上下文治理状态做决定。`before_final_hooks` 还提供项目级策略扩展点。这是当前源码相对早期 v3 文档很重要的新增方向：完成条件正在从模型自报转向证据驱动。

## 6. 配置、启动和日常开发

安装开发环境：

```bash
uv sync --dev
```

常用入口：

```bash
uv run moka                         # Textual TUI
uv run moka --repl                  # 普通 REPL
uv run moka "总结当前仓库"          # one-shot
uv run moka --resume latest         # 恢复最近 session
```

建议新项目先使用：

```bash
uv run moka --approval ask --sandbox best_effort
```

配置优先级是：

```text
CLI 参数 > 环境变量 > 项目 .pico.toml > 全局配置 > 代码默认值
```

provider profile 的名字只用于选择配置，真正决定请求格式的是 `protocol = "openai" | "anthropic"`。图片检查还可以单独配置 vision provider。Moka 目前保留 `.pico.toml`、`.pico/`、`PICO_*` 和 `pico` Python 包名作为兼容性内部标识；真实 key、配置和运行数据都不应提交到 Git。

标准验证命令：

```bash
uv run pytest tests -q
uv run ruff check .
uv run python scripts/run_v3_human_scenario_gate.py --suite full
```

当前 Windows 工作区的实测基线需要注意：完整 pytest 在 120 秒超时前已出现失败。已单独定位的失败包括 Bash benchmark 对 Windows 临时路径的处理，以及验证命令在 Windows 下未被识别为成功；相关核心 focused tests 为 48 passed、1 failed。Ruff 当前报告 235 项问题，其中 132 项可自动修复。因此 `release/v3/TESTING.md` 中“224 passed / Ruff clean”是历史发布证据，不应当作当前 checkout 的实时状态。

## 7. 新成员的高效阅读路线

### 30 分钟：建立全局图

1. 本文第 1～5 节。
2. `README.md` 的启动、命令和本地文件部分。
3. `release/v3/learning/01-overall-architecture.md`。
4. 快速浏览 `pico/core/runtime.py` 的构造函数和 `pico/core/engine.py::run_turn()`。

### 半天：能追踪一次请求

1. 用 `ScriptedModelClient` 阅读 `tests/test_engine_acceptance.py`，避免一开始依赖真实 provider。
2. 从 `Engine.run_turn()` 追踪到 context build、model parse、tool execute、final governance。
3. 跑一个 focused test，并查看临时 workspace 生成的 session/run 文件。
4. 阅读 `release/v3/learning/04-tools-permissions-sandbox.md` 和 `08-session-run-evaluation.md`。

### 一天：能开始改动

根据目标选择一条纵向链路：

| 目标 | 阅读顺序 | 先跑的测试 |
| --- | --- | --- |
| 改主循环 | `engine.py` → `turn_transitions.py` → `completion_governance.py` | `test_engine_transitions.py`、`test_engine_acceptance.py` |
| 改上下文 | `context_orchestrator.py` → `context_manager.py` → `compact.py` | `test_context_orchestrator.py`、`test_context_manager.py`、`test_compact.py` |
| 加工具 | `tools/schemas.py` → `tools/registry.py` → `tool_executor.py` | `test_tool_validation.py`、`test_tool_policy_acceptance.py` |
| 改权限 | `tool_profiles.py` → `permissions.py` → `tool_policy.py` | `test_permissions_acceptance.py`、`test_safety_invariants.py` |
| 改记忆 | `features/memory.py` → `context_handoff.py` → `context_manager.py` | `test_memory.py`、`test_context_handoff.py` |
| 改 provider | `config/__init__.py` → `providers/runtime.py` → `providers/clients.py` | `test_pico.py`、`test_provider_errors.py`、`test_usage.py` |
| 改 TUI | `tui/app.py` → `tui/widgets.py` → runtime events | `test_tui.py`、`test_ask_user.py` |
| 改评测 | `evaluation/` → `testing.py` → `scripts/` | 对应 benchmark/acceptance 测试 |

## 8. 如何理解当前迭代路线

以下不是已承诺的 roadmap，而是依据当前代码、测试和既有设计文档给出的优先级判断。

### P0：先恢复可信的工程基线

- 修复或按平台隔离 Bash benchmark 测试，使 Windows/Linux 的验收口径明确。
- 清理 Ruff 基线，并在 CI 中固定 `pytest + ruff + architecture budget`。
- 更新 v3 学习文档或新增“post-v3”说明，覆盖 context orchestrator、handoff、final readiness 和 multimodal，避免文档与实现漂移。
- 为 release evidence 标注 commit、平台和日期，区分历史结果与当前状态。

这是最优先项，因为 Moka 的卖点就是“证据可复盘”；如果仓库自己的实时证据不稳定，其他能力升级很难被可信地评价。

### P1：强化长任务可靠性

- 把 runtime event schema 固化成更明确的公共合同，让 CLI、TUI、report 和 tests 共用同一语义。
- 推进 transcript-first persistence：在进入可能失败的 provider/工具步骤前确保输入和状态已落盘。
- 补齐 streaming/partial output 与 idle watchdog，区分“模型慢、网络卡住、无输出、用户主动中止”。
- 给重复工具调用加入“换策略”反馈，而不只做拒绝。
- 用 context-cost 和 handoff benchmark 校准 compact 阈值、摘要质量、缓存命中与净 token 收益。

### P1：让完成判断真正证据化

- 把 `final-readiness` 的 reason schema、严重级别和 required-artifact 规则稳定下来。
- 为典型任务建立“修改代码必须有相关验证”“交付文件必须存在”等可配置 before-final hook。
- 在 report/TUI 中直接呈现“为什么允许完成、为什么被阻止”，减少只读 trace 的成本。

### P2：扩展能力，但守住边界

- Provider：完善 streaming、prompt-cache miss 解释、错误 taxonomy 和更多真实端点 smoke。
- Memory：为 Dream 增加可靠后台 job、可审阅/丢弃的整理结果和更清楚的事实生命周期。
- Tools：进一步拆开定义、验证、权限提示、执行和结果预算，但仍保持内部 `Pico.run_tool()` 为唯一总闸口。
- Multimodal：把图片能力纳入统一 usage、失败分类和 evaluation，不让二进制内容进入普通 history/trace。
- UX：让 TUI 更完整地消费 runtime events，而不是在 UI 层复制运行逻辑。

## 9. 评审迭代方案时的检查清单

一个改动如果会影响 agent 行为，至少回答这些问题：

- 它改变了控制面、状态面、动作面、上下文面还是证据面？
- 新状态的唯一所有者是谁？是否引入了第二套 event/state 系统？
- 失败、中止、step limit、resume 和 worker 场景下会怎样？
- 权限拒绝、路径逃逸、secret redaction 和 read freshness 是否仍有效？
- trace/task state/report 中能否解释新行为？
- focused unit test、acceptance test 和真实 run evidence 分别覆盖什么？
- 上下文 token、延迟、provider 调用数和 artifact 大小是否有可测成本？
- 文档描述的是当前事实、历史证据，还是未来计划？是否明确区分？

特别要避免四类架构倒退：把逻辑重新堆回 `runtime.py`；在 TUI 中复制 engine 决策；新增工具绕过统一执行网关；把完整 transcript 当成长时记忆无限注入 prompt。

## 10. 继续深入的资料

- `release/v3/learning/00-reading-map.md`：完整专题阅读索引。
- `release/v3/learning/02-runtime-engine.md`：runtime/engine 设计。
- `release/v3/learning/03-context-memory-compact.md`：上下文、记忆和压缩。
- `release/v3/learning/04-tools-permissions-sandbox.md`：动作安全边界。
- `release/v3/learning/08-session-run-evaluation.md`：持久化与证据面。
- `release/v3/learning/09-module-map.md`：按源码文件查职责。
- `release/v3/learning/11-dream-memory-consolidation.md`：Dream 深入说明。
- `release/v3/testing/README.md`：v3 真人场景验收包。

最后用一句话概括这个项目：**Moka 的迭代主线不是增加更多“会做的事”，而是让模型在真实仓库中做事时更可控、可续接、可解释、可验证。**
