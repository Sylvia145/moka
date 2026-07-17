# Iteration 11: Live provider dogfood — real DeepSeek, real toolchain, real acceptance

## Trigger

Iteration 10 recorded an explicit gap: the evaluation framework had run only on
the deterministic (`scripted`) harness, so the `actual_only` telemetry bucket was
empty — "no live provider was called". A candidate cannot claim "real
engineering delivery" while every quoted number is `estimated_proxy`.

This iteration closes that gap by running the full business-scenario dogfood
suite against a real provider — DeepSeek's Anthropic-compatible endpoint — with
real tool execution, real unittest acceptance, and real provider-billed token
telemetry.

## What was run

```bash
.venv/Scripts/python.exe scripts/run_business_scenario_dogfood.py \
    --provider deepseek --output-dir artifacts/dogfood-deepseek
```

Output: `{"scenario_count": 5, "status": "passed"}` — 5 scenarios, 62 checks, all green.

The provider profile resolves from `.pico.toml` (`[providers.deepseek]`,
`protocol = "anthropic"`, `base_url = https://api.deepseek.com/anthropic`,
`model = deepseek-v4-pro`), so `_build_client_factory` wires an
`AnthropicCompatibleModelClient`. Every scenario produces `trace.jsonl`,
`report.json`, and `session_events.jsonl` under its workspace.

## Results

| Scenario | Checks | What it proves | Calls | Input tok | Output tok | Cached tok |
| --- | --- | --- | --- | --- | --- | --- |
| order_pricing_bugfix | 7/7 | Real coding loop: read test → read src → patch → run unittest | 5 | 8 896 | 747 | 13 312 |
| release_readiness_review | 9/9 | Skill invocation writes a report, leaves business files untouched | 4 | 8 359 | 2 030 | 6 528 |
| incident_resume_fix | 10/10 | Session resume: locate in turn 1, `from_session` resume, todo closed | 9 | 22 286 | 2 001 | 19 840 |
| release_governance_with_isolated_worker | 18/18 | MCP stdio + worker isolation (write_scope, worktree) | 11 | 27 158 | 2 324 | 9 856 |
| release_governance_over_http | 18/18 | MCP Streamable HTTP transport | 10 | 22 958 | 2 415 | 10 368 |
| **TOTAL** | **62/62** | | **39** | **89 657** | **9 517** | **59 904** |

## Actual (provider-billed) telemetry, not estimated proxy

These numbers come from `completion_metadata` on `model_parsed` trace events —
values the DeepSeek endpoint returns in each response's `usage`, not the
`typed_content_heuristic_v1` estimates used in iteration 10. A `model_parsed`
event looks like:

```json
{"completion_metadata": {"cache_hit": true, "cached_tokens": 2560,
  "input_tokens": 2000, "output_tokens": 195, "provider_attempts": 1,
  "provider_base_url": "https://api.deepseek.com/anthropic/v1",
  "provider_model": "deepseek-v4-pro", "provider_protocol": "anthropic",
  "provider_retry_count": 0}}
```

Two things worth quoting in an interview:

1. **Prompt cache hit on 38 of 39 calls** (59 904 cached tokens). The
   Anthropic-compatible endpoint returns server-side cache usage on repeated
   prefixes, and the client surfaces `cached_tokens`/`cache_hit` unchanged. That
   is provider-billed evidence that the five-section prompt's stable prefix is
   actually cheaper on every subsequent turn — not a direction estimate.

2. **Zero provider retries** across all 39 calls (`provider_retry_count: 0`,
   `provider_attempts: 1` everywhere). The retry path exists but was never
   needed; DeepSeek's endpoint was stable end-to-end.

## Findings beyond the pass/fail

- **The step budget is real, and the agent does not fake completion.** In the two
  `release_governance` scenarios and `release_readiness_review`, the model hit
  `max_steps=8` before finishing the *tail* work (human-review handoff), and its
  `<final>` honestly reports "已达本轮 step 预算上限, use `/resume` to continue"
  with an explicit list of what is done vs. not done. The checks still pass
  because the core artifact (skill report / worker governance report) was
  produced inside the budget. A weaker harness would either let the loop run
  forever or silently mark the task complete.
- **Two `run/` directories per resuming/worker scenario.** `incident_resume_fix`
  has two runs (first turn + `from_session` resume) and each `release_governance`
  scenario has two (main agent + delegated worker agent). The multi-run layout is
  itself evidence that session resume and worker delegation are real, separate
  execution contexts, not in-process short-circuits.

## Commands to reproduce / re-summarize

```bash
# Run all 5 scenarios against DeepSeek (regenerable; artifacts/ is gitignored)
.venv/Scripts/python.exe scripts/run_business_scenario_dogfood.py \
    --provider deepseek --output-dir artifacts/dogfood-deepseek

# Sum provider-billed tokens from the traces
.venv/Scripts/python.exe scripts/summarize_dogfood_tokens.py
```

## Caveats (stated so they are not discovered against you)

- Single run, single model (`deepseek-v4-pro`). Not a statistical claim and not a
  cross-provider comparison — it proves the live path works and yields real
  telemetry, not that DeepSeek beats another provider.
- Three scenarios end at `max_steps=8` with an honest "resume" handoff rather
  than full completion. The pass is on the *core artifact*, not on the full
  human-review tail.
- `artifacts/dogfood-deepseek/` is gitignored (local run output); traceability
  lives in this document + the exact commands above + the inline totals.

## Still-open live-path items (recorded, not fixed)

- **Anthropic provider config bug**: `resolve_provider_config("anthropic")`
  returns DeepSeek's `model`/`base_url` (deepseek-v4-pro @ api.deepseek.com)
  instead of `.pico.toml`'s `claude-sonnet-4-6 @ right.codes/claude`. Root cause
  not yet localized; DeepSeek (the default profile) resolves correctly, which is
  why this iteration uses DeepSeek.
- **OpenAI provider 403**: `right.codes/codex` returns HTTP 403 for the
  configured key. Not yet diagnosed.

Both are provider-config edge cases, not the core agent path — but a candidate
should be able to say they *found* them and where they stand, rather than be
surprised by them in review.

---

**留痕原则**: every token number above is summed from the `completion_metadata`
of the actual run (script in `scripts/summarize_dogfood_tokens.py`), and
the runs are regenerable with the exact commands in "Commands to reproduce".
The raw traces are gitignored by design; traceability lives in script + command
+ inline numbers, not in a committed snapshot of the output.
