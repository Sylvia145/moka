# INC-0013: Worker timeout watcher crashed after session reset orphaned its item

- Date: 2026-08-16
- Severity: medium (flaky full-suite failure; benign per-call but a real concurrency bug)
- Evidence: `tests/test_agent_workers_acceptance.py::test_async_worker_notification_is_drained_by_coordinator_only` failing in a 751s full-suite run

## Symptom

The full suite failed `test_async_worker_notification_is_drained_by_coordinator_only`
with an unhandled thread exception — even though that test's own assertions all passed:

```
ValueError: unknown worker: agent_1
  File pico/core/worker_background.py, in _watch_timeout
    item = manager._get_item(task.id)
```

## Root cause

`WorkerManager.spawn` starts one daemon `_watch_timeout` thread per worker. The
thread sleeps `timeout_seconds` (default 60), then calls `manager._get_item(task.id)`
to decide whether to time the worker out.

`clear_session()` (and `resume_session()`) replace `runtime.session` with a fresh
dict and rebind a new `WorkerManager`. The old `_watch_timeout` thread still holds
the old manager — which points at the *same* `runtime`, whose `session` has already
been swapped — so when it fires 60s later, `_get_item` iterates the new session's
empty `workers.items` and raises `ValueError: unknown worker: agent_1`.

In a short run the daemon thread is killed at process exit before it fires, so the
bug hides. In a long full-suite run (751s) the orphaned watcher fires mid-suite,
pytest converts the unhandled thread exception into a failure, and a test that is
logically green gets marked red.

## Resolution

`_watch_timeout` now uses a non-raising `_find_item` (returns `None`) and exits
early when the worker item no longer exists — the worker was already cleaned up by a
session reset, so there is nothing to time out. `_get_item` keeps its raising
contract for callers that legitimately expect the item to be present.

## Regression

`test_agent_workers_acceptance.py::test_watch_timeout_ignores_worker_cleared_by_session_reset`
spawns an `Explore` worker with a 1s timeout, clears the session (orphaning the item),
and waits past the watcher's fire point, asserting no exception escapes.

## Residual (recorded, not fixed)

The watcher thread still lingers for the full `timeout_seconds` even after the worker
finishes, rather than being signalled early. It is a bounded, harmless daemon thread
now that it no-ops on a missing item, but a `threading.Event` cancellation would
remove the waste. Left as-is to keep the fix minimal.
