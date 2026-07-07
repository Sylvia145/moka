# Experiment 01: Release governance and isolated repair dogfood

- Date: 2026-08-12
- Provider: configured DeepSeek profile
- Model parameters: temperature 0, `max_new_tokens=1024`
- Evidence root: `artifacts/engineering/business-dogfood/`

## Purpose

Validate two business-shaped loops with a real model instead of treating a
deterministic tool script as evidence of agent capability:

1. a Billing API release review that retrieves policy through MCP and delegates
   a report-only worker in a Git worktree;
2. a pricing calculation repair that must produce in-agent and independent test
   evidence.

## Release-governance result

After correcting the Markdown-tolerant semantic verifier (INC-0006), three
independent runs passed all 18 checks:

| Artifact | Main tool steps | Worker outcome | Handoff |
|---|---:|---|---|
| `20260812-release-governance-run2` | 10 | completed | pending review |
| `20260812-release-governance-run3` | 10 | completed | pending review |
| `20260812-release-governance-run4` | 10 | completed | pending review |

The retained first run is intentionally not counted as a model failure: it
produced `POLICY: billing-release-v1` and `STATUS: BLOCKED`, but the initial
verifier did not accept Markdown emphasis. The corrected verifier checks the
field/value semantics rather than presentation.

## Pricing-repair iteration

| Run | Result | Tool steps | Important observation |
|---|---|---:|---|
| `order-pricing-run1` | failed | 7 | Independent `uv` verifier hit Windows decoding/runtime instability (INC-0007). |
| `order-pricing-run2` | failed | 8 | In-workspace pytest was unavailable; model tried remediation and reached the step limit (INC-0008). |
| `order-pricing-run3` | failed | 5 | `unittest` completed with exit code 0, but verifier searched for pytest text `passed` (INC-0009). |
| `order-pricing-run4` | passed | 4 | Repair plus in-agent and independent unittest verification passed. |
| `order-pricing-run5` | passed | 4 | Same result. |
| `order-pricing-run6` | passed | 4 | Same result. |

The post-fix sample is 3/3 successful. The earlier artifacts are preserved as
engineering evidence, not replaced by the successful sample.

## Decisions confirmed

- A task is not successful solely because the output claims success: business
  assertions inspect source, MCP trace, worker state, handoff and test result.
- Test evidence must be executable in the agent's actual workspace. For these
  dependency-free fixtures, `unittest` is the portable contract; this does not
  prescribe a test framework for production repositories.
- A worker's output is reviewable evidence, not an automatic merge: the release
  workflow records a base commit, changed paths, diff summary, verification and
  `pending_review` status.

## Reproduction

```powershell
.\.venv\Scripts\python.exe scripts\run_business_scenario_dogfood.py `
  --provider deepseek --scenario release_governance_with_isolated_worker `
  --output-dir artifacts\engineering\business-dogfood\<run-id> `
  --max-steps 10 --max-new-tokens 1024

.\.venv\Scripts\python.exe scripts\run_business_scenario_dogfood.py `
  --provider deepseek --scenario order_pricing_bugfix `
  --output-dir artifacts\engineering\business-dogfood\<run-id> `
  --max-steps 8 --max-new-tokens 1024
```

Provider credentials are resolved from local configuration and are not part of
the artifact set.
