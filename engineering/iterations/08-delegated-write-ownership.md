# Iteration 08: Delegated write ownership

## Trigger

Remote MCP release-governance dogfood was 2/3: policy lookup and worker
handoff succeeded, but one parent Agent wrote to the protected main workspace
after delegation.

## Implementation

- Added `delegated_review` to the runtime tool profiles.
- A scoped write worker activates the parent guard after it has started or is
  queued, avoiding interference with worker startup scheduling.
- Added a stable permission reason and user-visible denial message.
- Mapped MCP `readOnlyHint` into the existing risky/read-only Tool Registry
  model; no MCP bypass was added.
- Persisted guard state in the session lifecycle and added direct tests for
  write denial, safe policy query, worktree output and resume restoration.

## Verification status

- New guard-focused tests: 2 passed using an explicit repository-local pytest
  base temp directory.
- MCP/release test batch: 11 passed; one pre-existing timeout test observed a
  server-thread timing race after client timeout (server log later shows the
  request), so it is not counted as a clean full-batch pass.
- Worker batch has pre-existing shared-script-client scheduling and
  write-before-read contract failures under the current Windows environment;
  release-governance tests within that batch passed.

## Real-provider evidence

DeepSeek Streamable HTTP release-governance guard runs: 2/3 passed. In both
passing runs the worker report, pending-review handoff and main-workspace
boundary checks passed. The retained failure was a Windows RunStore atomic
replace lock after the report was already produced; it led to INC-0011 and the
bounded retry change. It was not a parent-agent boundary violation. Two
additional post-retry runs then passed (2/2).
