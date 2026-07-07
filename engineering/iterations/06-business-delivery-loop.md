# Iteration 06: Business delivery loop

## Objective

Turn existing Agent runtime capabilities into auditable business outcomes:
release governance via MCP and an isolated worker, plus a repair workflow with
executable test evidence.

## Delivered

- A Billing API release-governance fixture with a versioned policy served over
  local stdio MCP.
- A report-only worker running in a Git worktree; its result includes a
  `pending_review` handoff with base commit, reviewable paths, diff summary,
  verification metadata and risk flags.
- Semantic business checks: release status, mandatory configuration, migration
  confirmation, rollback owner, policy version, source immutability and handoff
  boundaries.
- A real-provider dogfood runner with selectable scenarios and raw report,
  trace and session-event evidence.
- Portable zero-dependency test commands for isolated code-repair workspaces.

## Engineering issues found while running real scenarios

| Incident | Finding | Resulting change |
|---|---|---|
| INC-0006 | Verifier mistook Markdown formatting for absent business fields. | Normalize formatting before semantic field checks. |
| INC-0007 | Outer `uv` invocation had Windows decoding/runtime instability. | Use the runner interpreter with explicit UTF-8 decoding. |
| INC-0008 | Agent workspace did not include pytest. | Make fixture verification self-contained with `unittest`. |
| INC-0009 | `passed` was pytest-specific output, not proof of command success. | Assert shell exit code and keep an independent verifier. |

## Verification

```text
ruff check scripts/run_business_scenario_dogfood.py tests/test_business_scenario_dogfood.py
pytest tests/test_business_scenario_dogfood.py tests/test_release_governance.py \
  tests/test_agent_workers_acceptance.py tests/test_runtime_demo.py -q
# 18 passed
```

Real DeepSeek evidence is summarized in
`engineering/experiments/01-release-governance-and-repair-dogfood.md`.

## Scope control

This iteration does not add automatic merge, arbitrary remote MCP, a new
observability platform or generic workflow DSL. The purpose is to make the
already-delivered runtime capabilities demonstrably useful and testable in a
small, realistic delivery loop.
