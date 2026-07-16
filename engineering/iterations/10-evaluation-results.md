# Iteration 10: Evaluation results — one positive, one honest negative

## Trigger

Pre-interview gap found in the re-assessment: the project had a full evaluation
*infrastructure* (paired experiments, ablation, cost experiments, verifiers)
but no run-out *numbers* a candidate could quote. An agent-dev interviewer will
ask "how do you prove your agent is good?", and "I have a framework" is not the
same as "I ran it and here is what it found".

This iteration runs two experiments on the deterministic (`scripted`) harness —
no live API key required — and records the results, **including a negative one**,
because an evaluation framework that only ever reports wins is not evidence.

## What was run

Both scripts live under `scripts/` and drive `pico/evaluation/context_cost.py`:

```bash
.venv/Scripts/python.exe scripts/run_context_cost_experiment.py \
    --mode scripted --output-dir artifacts/context-cost

.venv/Scripts/python.exe scripts/run_llm_handoff_benchmark.py \
    --mode scripted
```

`scripted` mode uses `pico.testing.ScriptedModelClient`, so the runs are
deterministic and hermetic. Cost is `estimated_proxy` (token counts derived from
`prompt_built` context-usage estimates, priced with the configured rate), **not**
provider-billed telemetry. The report files themselves carry this split
(`actual_only` vs `estimated_proxy_only`), so nothing is silently overstated.

## Experiment 1 — deterministic context compaction: POSITIVE

`--mode scripted` compares a control run (no context reduction) against a
treatment run (deterministic compaction of the transcript).

| Metric | Value |
| --- | --- |
| Paired tasks | 1 |
| Input tokens / task (control → treatment) | 9522 → 8180 |
| Net tokens saved / task | **1342 (−14.09%)** |
| Quality regressions | **0** |
| Claimable cost win | True |

**Reading:** deterministic compaction cuts input tokens by ~14% with no
verification regression. This is the concrete, quotable backing for the
`/compact` feature — it is not just "the transcript gets shorter", it measurably
reduces the billable-input proxy by double digits.

## Experiment 2 — LLM handoff vs deterministic compaction: NEGATIVE

`run_llm_handoff_benchmark.py` pairs two orchestrator variants on the 5
long-session tasks in `benchmarks/long_session_tasks.json`:
`full_orchestrator` (deterministic compaction) vs
`full_orchestrator_with_llm_handoff` (LLM writes the handoff).

| Task | Deterministic cost | LLM handoff cost | Net benefit |
| --- | --- | --- | --- |
| add-endpoint-with-test | 0.0443 | 0.0510 | −3124 tokens |
| config-migration | 0.0362 | 0.0407 | −3123 tokens |
| debug-and-fix | 0.0288 | 0.0336 | −3123 tokens |
| dependency-upgrade | 0.0434 | 0.0480 | −3123 tokens |
| multi-file-refactor | 0.0363 | 0.0412 | −3124 tokens |
| **Median** | — | — | **−3123 tokens (−11.82%)** |

- Positive net benefit: **0%** (all 5 tasks net-negative)
- Quality regressions: **0**

**Reading:** my hypothesis was "an LLM-written handoff compresses better and
saves tokens". The data says the opposite: LLM handoff costs ~12% *more* input
tokens and buys zero verification gain on these tasks. That is an honest,
recorded negative result — the LLM-handoff path is *not* a cost win here.

## Why the negative result matters more than the positive one

An interviewer who only hears "my compaction saves 14%" should ask "what did you
try that *didn't* work?". The negative result is the stronger evidence because:

1. It proves the framework is not rigged to report wins — it measured, and
   reported, a design hypothesis that failed.
2. It forces a sharper explanation of **what LLM handoff is actually for**: its
   value is *information fidelity* on very long sessions (an LLM can keep the
   semantic intent that a mechanical truncation drops), not token savings. LLM
   handoff adds one extra model call by construction, so it can never win on
   raw tokens — the 5 task fixtures here are short enough that the fidelity
   benefit never materializes. The correct follow-up experiment is a
   near-context-limit session where deterministic truncation starts losing
   verifier passes; only there would LLM handoff's cost buy a quality win.

## Caveats (stated so they are not discovered against you in an interview)

- `estimated_proxy` data: token counts come from context-usage estimates, not
  provider telemetry. Directional evidence for token cost, not a billing claim.
  The `actual_only` bucket is empty because no live provider was called.
- Small sample: 1 task (experiment 1) and 5 tasks × 1 repetition (experiment 2).
  Not a statistical claim; a stable effect, not a measured distribution.
- Scripted tasks are short; they cannot exercise the "very long session" regime
  where LLM handoff's fidelity is supposed to win. The negative result is about
  *token cost*, not about *handoff quality at scale*.

## Next step (recorded, not done)

Run the LLM-handoff experiment in `live` mode (with provider telemetry) and on a
near-limit-length session to test the fidelity hypothesis properly. This is the
gap between "directional proxy" and "provider-billed, quality-weighted" evidence.

---

**留痕原则**: every number above is quoted inline from the run output, and the
runs are regenerable with the exact commands in "What was run". The raw reports
land in `artifacts/` (gitignored by design — that tree is local build output),
so they are not committed; the traceability lives in the script + command + the
inline numbers, not in a committed snapshot of the output.
