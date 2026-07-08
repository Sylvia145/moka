# ADR-007: Enforce delegated write ownership in the parent permission layer

## Decision

When a parent delegates a scoped write task, switch the parent to the
`delegated_review` tool profile. The child keeps its worktree-scoped write
permission; the parent becomes an evidence reviewer and worker controller.

## Why this layer

Prompt-only instructions were insufficient in a real HTTP run. A business
verifier can detect a bad main-workspace write after the fact, but cannot
prevent it. The existing Tool Registry and PermissionChecker already mediate
local tools and MCP adapters, so the profile boundary gives one auditable deny
path without adding parallel authorization state.

## MCP treatment

Only MCP tools that declare `annotations.readOnlyHint=true` are exposed as
read-only in this profile. Unknown or side-effecting remote tools remain risky
and are denied. This is deliberately conservative: an annotation permits a
query; it does not make arbitrary remote writes safe.

## Lifecycle

The active guard is persisted in the session and restored with the runtime.
The review/merge decision remains external to the Agent; Moka does not
auto-merge a worker handoff.
