# Requirement 03: Delegated write ownership guard

## Problem

In the HTTP release-governance dogfood, a worker correctly created the report
in its isolated worktree, but the parent agent then continued exploring and
wrote a second report into the main workspace. The verifier blocked the run,
but prevention belonged in the runtime permission boundary.

## Acceptance criteria

1. Delegating a `worker` with a non-empty `write_scope` activates a parent
   `delegated_review` tool profile.
2. The parent may read files, use MCP tools explicitly marked
   `annotations.readOnlyHint=true`, and send control messages to that worker.
3. The parent must be denied `write_file`, `patch_file`, `run_shell`, new
   delegation, and MCP tools without a read-only annotation.
4. Denials have the stable reason `delegated_write_guard`, are included in
   normal permission/governance evidence, and do not change the main workspace.
5. The guard survives session restoration so a resumed session cannot bypass
   the ownership boundary.

## Non-goals

Automatic merge, human-review UI, generic RBAC, or trusting an unannotated
remote MCP side-effect declaration are out of scope.
