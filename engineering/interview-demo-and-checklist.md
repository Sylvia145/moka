# Moka 面试演示脚本 + 检查单

> 目标岗位：大厂 Agent 开发。本文是现场演示脚本和自检清单，配合
> `release/v3/learning/`（架构阅读）和 `engineering/iterations/`（留痕）使用。

## 一、30 秒电梯陈述

> Moka 是一个跑在终端里的轻量级本地 coding agent，基于开源项目 pico 二次开发。
> 它把模型、工具、上下文、记忆、权限、持久化和评测包成一条可审计的本地执行链。
> 核心价值不是工具数量，而是把 coding agent 最容易失控的几层——工具越权、上下文
> 膨胀、会话恢复、长输出、子任务隔离、结果验收——变成显式的控制面和证据面。

关键词落到三个面：**控制面**（Engine 是 turn 级状态机，不是 while 循环）、
**状态面**（Session/Memory/Checkpoint 让任务能续接）、**证据面**（trace/report
让"真实跑过"可证明）。

## 二、演示脚本（按场景，选 2–3 个讲透）

现场优先用**确定性 harness**（`pico.testing.ScriptedModelClient`）演示，不依赖真实
API key，结果可复现。有 key 再补一个真实 one-shot。

### 场景 0：测试基线（开场 30 秒）

```bash
.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q
```

讲一句："这是全量测试，含 engine 状态机、权限沙箱、记忆、MCP、context 压缩、
final readiness 等 60 个测试文件。Windows 和 POSIX 都跑。"

### 场景 1：one-shot 工具调用链（核心，2 分钟）

```bash
moka --approval never "找出 tests/test_verification.py 里 classify 的返回分支并总结"
```

预期：agent 依次调用 `search` → `read_file` → 总结，最后 `<final>`。

讲什么：
- `<tool>` / `<final>` 是 Pico 自己的**文本协议**，`core/model_output.py` 只负责解析。
- 每次工具调用都过 `tool_executor`：参数校验 → 权限 → policy → 重复调用 → 工作区 diff
  → 输出截断，全链路写 trace。
- 打开 `.pico/runs/<run_id>/trace.jsonl` 指给面试官看事件流。

### 场景 2：权限与沙箱边界（安全，1 分钟）

```bash
moka --approval never "执行 run_shell 命令 echo hi"
moka --read-only "改写 README.md"
```

讲什么：
- `PermissionChecker` + tool profile + approval policy + write scope + sandbox 是**四层**
  边界，不是单一 if。
- 越权、重复调用、部分成功（shell exit != 0 但改了文件）都会被记录成不同的
  `tool_status` / `security_event_type`。
- 举例：`write_scope` 让 worker 只能写自己的 scope，越界即拒（见 D7/ADR-007）。

### 场景 3：分层记忆 + dream（差异化，1 分钟）

```bash
moka "/remember 这个仓库用 DeepSeek 的 Anthropic-compatible endpoint"
moka "/dream"
moka "/memory"
```

讲什么：working memory（会话内）→ daily log（当天）→ durable topics（跨会话），
`/dream` 把 daily log 后台整合成 durable topic。这是"有记忆的 agent"，对标 Claude
Code 的 auto memory。

### 场景 4：子 agent 隔离（工程深度，1 分钟）

演示 `/agents` 或一个 delegate 任务。

讲什么：`WorkerManager` 管理子 agent，`write_scope` + git worktree 隔离写路径，
worker 结果结构化回传，主 agent 能解释改动来源（见 ADR-002/ADR-007）。

### 场景 5：MCP 网关（扩展性，1 分钟）

讲什么：MCP stdio + Streamable HTTP 双传输（ADR-005/ADR-006），外部工具经统一的
执行/权限/证据链路接入，不是裸调。

### 场景 6（可选，有 key）：真实 one-shot

```bash
moka "给 tests/test_session_store.py 补一个 Windows 原子替换重试的回归测试"
```

讲什么：真实模型 + 真实工具链，落地一个 commit。

## 三、测试状态的标准回答（必被问）

> "我的测试不是'全绿'这么简单。全量 535 passed / 10 skipped / 0 failed。这 535
> 是从 baseline 506 passed / 36 failed 一路修上来的——我把 36 个失败拆成三类：
> **环境差异**（比如缺 textual 依赖）、**平台差异**（Windows 路径分隔符、cmd.exe
> 引号规则）、**真实代码缺陷**。能跨平台就修，不能修的用 `skipif` 明确标注
> reason，绝不让测试'红着'还装作没看见。每个 root cause 和 fix 都记在
> `engineering/iterations/09-test-baseline-and-workspace-root.md`。"

关键数字（见下方速查表），要能脱口而出。

## 四、技术深挖应对（追问清单）

| 追问 | 应对要点 |
| --- | --- |
| "为什么不直接用 LangChain？" | 零核心依赖（仅标准库），Runtime/Engine/ToolExecutor 边界自己控制，LangChain 的抽象对本地 harness 是负担。 |
| "你的 ReAct 和最小 ReAct 差在哪？" | 最小 ReAct 只证明"思考+行动"交替；Moka 处理的是循环之外的工程问题：工具越权、上下文膨胀、会话恢复、长输出、子任务隔离、结果验收（见 `01-overall-architecture.md`）。 |
| "上下文怎么不膨胀？" | 五段式 prompt + 12000 预算 + `/compact` 压缩 + microcompact 保留最新工具结果 + 分层记忆，不是无限 transcript。 |
| "模型死循环调同一个工具怎么办？" | `repeated_tool_call` guard：相同调用直接拒绝并提示换工具或 final。 |
| "工具部分成功怎么记录？" | shell exit != 0 但改了文件 → `partial_success`，trace 里 `workspace_changed=true`，final readiness 严格模式会 block。 |
| "worker 写越界怎么办？" | `write_scope` + git worktree 隔离，越界写被 `write_scope_guard` 拒绝（D7/ADR-007）。 |
| "provider 失败怎么恢复？" | provider error recovery，把错误分类而不是冷 stop。 |
| "你怎么证明改动没变差？" | 全量 pytest + 确定性 harness（12 题）+ verifier 证据 + real-session gate（INC/ADR 里记录）。 |
| "entropy budget 是什么？" | 架构边界测试：每个核心模块有最大行数上限（如 runtime 950、verification 80），超了必须真实拆分而不是提高预算（见 D6）。 |

## 五、关键数据速查

| 项 | 值 |
| --- | --- |
| 测试文件数 | 60 |
| 全量结果（`.venv`，exit 0） | **535 passed, 10 skipped, 0 failed** |
| 真实 bug 修复（本次迭代） | D1 shell_env Windows 变量 / D2 dream 文件名 `:` / D7 provider 优先级 / D8 工具路径 `/` / D9 verification 分类器 / D11 SessionStore Windows 重试 |
| 平台分支修复 | shlex.quote 引号、pwd→cd、路径分隔符 |
| 明确 skipif 的平台差异 | symlink 权限、bash fixture、git 路径归一化、真实会话 gate |
| ADR | 7 篇（`engineering/decisions/ADR-*.md`） |
| INC | 11 篇（`engineering/incidents/INC-*.md`） |
| 迭代留痕 | 9 篇（`engineering/iterations/0*.md`） |

## 六、面试前检查单（30 分钟）

- [ ] 跑一遍 `pytest -p no:cacheprovider -q`，记住最终数字（passed/skipped）。
- [ ] 复述一遍"三层"（控制面/状态面/证据面）和"四层权限边界"。
- [ ] 能一句话说清 2 个最硬的 bug 修复：provider 优先级（D7）、Windows 原子替换
      （D11，关联 INC-0011）。
- [ ] 打开 `.pico/runs/<run_id>/trace.jsonl` 和 `report.json`，能现场指认事件字段。
- [ ] 准备好 3 个"为什么这么设计"的答案（Engine 拆出 Runtime、文本协议、熵预算）。
- [ ] 确认 demo 命令在本机可跑（无 key 也能跑的场景 1–5）。
- [ ] 清理 `.pytest_cache`（如损坏，用 `chkdsk` 或 `-p no:cacheprovider` 绕过）。

---

**留痕原则**：本文档和 `engineering/iterations/09-*.md`、`ADR-*.md`、`INC-*.md`
一起构成面试证据链——每个结论都能追溯到一次真实的 bug 定位和修复。
