# INC-0011: Windows file lock interrupted worker audit persistence

- Date: 2026-08-12
- Severity: medium
- Evidence: `20260812-release-governance-http-guard-run2`

## Symptom

The worker wrote the isolated release report and produced a valid pending-review
handoff, but failed while atomically replacing its `task_state.json` with
`[WinError 5] Access is denied`. The parent guard correctly denied its later
main-workspace write attempt. The business run failed only because the worker
terminal state was `failed`.

## Root cause

Windows may hold a just-written JSON target briefly while concurrent runtime
artifact activity is occurring. The prior RunStore treated this transient lock
as an immediate terminal persistence error.

## Resolution

RunStore retries `PermissionError` from atomic JSON replacement up to three
times with bounded incremental backoff. It removes the temporary file and
re-raises if all attempts fail, so audit persistence is never silently skipped.

## Regression

`tests/test_run_store.py::test_run_store_retries_transient_permission_error_during_atomic_replace`
injects two replace failures and verifies the third attempt persists the file.
