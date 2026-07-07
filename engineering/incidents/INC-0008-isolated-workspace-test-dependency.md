# INC-0008: Isolated workspace could not execute pytest

- Date: 2026-08-12
- Severity: medium
- Scope: real DeepSeek order-pricing dogfood run

## Symptom

The model fixed the pricing calculation and called `run_shell`, but
`python -m pytest -q` used the system interpreter and failed with
`No module named pytest`. It then attempted `uv sync`, which was unavailable
offline, and reached the eight-step budget. The external verifier passed only
because it used the host project's virtual environment.

## Root cause

The fixture described a pytest command but did not provide a workspace-local
environment or a zero-dependency test entry point. The model therefore had no
way to satisfy the required evidence reliably in a clean agent workspace.

## Resolution

The repair fixtures now use standard-library `unittest` and publish the exact
command in the task contract. The independent verifier runs the same command
from the host interpreter. The acceptance check is named `tests_ran`, rather
than tying the business requirement to a particular test framework.

## Follow-up

Re-run the scenario three times with the same provider and retain both the
pre-fix failure and post-fix artifacts for comparison.
