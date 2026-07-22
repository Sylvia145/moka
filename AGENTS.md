# Repository Guidelines

## Project Structure & Module Organization

`pico/` contains the Python package. Keep runtime orchestration and state in `pico/core/`, user-facing memory, skills, and sandbox features in `pico/features/`, provider adapters in `pico/providers/`, tool definitions in `pico/tools/`, evaluation code in `pico/evaluation/`, and Textual UI code in `pico/tui/`. Tests live in `tests/` and generally mirror the module or behavior they cover. Operational scripts belong in `scripts/`; benchmark inputs are in `benchmarks/`; maintained documentation and screenshots are in `docs/`, `release/v3/`, and `assets/`.

## Build, Test, and Development Commands

- `uv sync --dev`: create/update the development environment.
- `uv run pico`: run the local CLI from the checkout.
- `uv run pico-tui`: launch the Textual interface.
- `uv run pytest tests -q`: run the complete automated test suite.
- `uv run pytest tests/test_memory.py -q`: run one focused test module.
- `uv run ruff check .`: run static lint checks.
- `uv run python scripts/run_v3_human_scenario_gate.py --suite full`: execute the full human-scenario acceptance gate.

## Coding Style & Naming Conventions

Target Python 3.10 or newer. Use four-space indentation, `snake_case` for modules, functions, and variables, and `PascalCase` for classes. Add type hints to public APIs and Pydantic models at external/tool boundaries. Keep runtime consumers side-effect-light and avoid introducing parallel state or event systems when an existing `core` abstraction can be extended. Run Ruff before submitting changes.

## Testing Guidelines

Pytest is the primary framework; async tests use `pytest-asyncio`. Name files `test_<area>.py` and tests `test_<behavior>()`. Add focused unit coverage for new logic and acceptance coverage when changing runtime, tool, memory, permission, or TUI flows. Tests should be deterministic and must not require live provider credentials unless explicitly guarded, such as `PICO_LIVE_SMOKE=1`.

## Commit & Pull Request Guidelines

Follow the repository's Conventional Commit style: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, or `release:` followed by an imperative summary. Keep commits scoped. Pull requests should explain the problem, design choice, verification commands, and user-visible impact; link relevant issues and include screenshots for TUI changes. Call out configuration, compatibility, or security implications.

## v3 Learning Documentation

`release/v3/learning/` is an architecture-oriented learning set, not a frozen API reference. Read it together with the current `pico/`, `tests/`, and `scripts/` trees. Its core topics all have corresponding implementations: runtime/engine, context-memory-compact, tools-permissions-sandbox, workers-plan-todo, providers-config, skills-CLI-TUI, session-run-evaluation, and Dream memory consolidation.

There is no known case in this learning set where a document states that an implemented Pico feature exists but no corresponding project code can be found. The known drift is in the other direction: `09-module-map.md` is not exhaustive, while several documents still describe shipped work as future work. In particular, `core/context_sections.py` and `core/context_orchestrator.py` provide the section-registry foundation; `features/memory_lint.py` provides a standalone memory lint; `features/memory.py` writes Dream quality reports; and `core/final_readiness.py` gates finals with high-priority todo checks.

Use `release/v3/learning/12-document-audit-change-log.md` as the detailed audit record. When adding, splitting, or removing `pico/` modules, update `09-module-map.md` and `10-module-learning-guide.md`. When an item in a learning document's improvement roadmap ships, rewrite it as current behavior plus remaining limitations rather than leaving it as a future-only proposal. Keep confirmed limitations accurate: manual and automatic Dream do not yet share one execution lock; Dream has no independently managed lifecycle or review/apply output store; workers now have bounded scheduling, timeout/cancellation, and write-scope worktree isolation, but worker heartbeat/restart-from-crash is not yet modeled; and runtime tool handling remains based on completed text responses rather than turn-internal native streaming blocks.

## Security & Local Artifacts

Never commit `.env`, `.pico.toml`, credentials, run traces, or `.pico/` memory. Put temporary Agent-generated Markdown and personal plans under `.local-notes/` and ignore them locally; reserve tracked documentation for polished architecture, benchmark, and release evidence.

## Coding Agent 永久约束（后端并发增强版）

以下约束对所有 Coding Agent 修改 Moka 代码时永久生效：

1. 文档、代码注释、TODO/FIXME 使用中文。
2. 类/函数/变量使用正常英文工程命名。
3. 修改前必须分析真实调用链。
4. 优先复用 Runtime / Engine / WorkerManager / Session / Trace。
5. 不创建第二套权限、状态机、配置或 Trace。
6. 一次只实现一个最小阶段。
7. 每阶段必须有测试。
8. 所有并发修改必须列出 race condition。
9. timeout/retry/cancellation 必须明确语义。
10. 不通过放大 timeout 掩盖竞态。
11. 不吞异常。
12. 不通过删测试/削弱断言通关。
13. terminal state 必须可追踪。
14. 新配置必须有默认值、来源和测试。
15. 每阶段完成报告固定输出：
   修改文件 / 核心合同 / 并发风险 / 测试结果 / 未解决问题。
