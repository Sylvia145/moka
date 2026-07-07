# ADR-004: Use self-contained verification for isolated agent workspaces

## Decision

Business dogfood fixtures must expose a verification command that is executable
from the workspace without relying on the host project's virtual environment.
The two code-repair fixtures use `python -m unittest discover -s tests -v`.

## Context

An initial live order-pricing run repaired the implementation but its in-agent
`python -m pytest -q` command resolved to the system Python. That interpreter
had no pytest installed. The agent then attempted dependency installation,
exhausted its bounded step budget, and could not produce verification evidence.
The outer verifier used the host virtual environment and passed, creating a
misleading split between agent evidence and external evidence.

## Consequences

- A scenario pass still requires both in-agent and independent verification.
- The fixture's test command is portable across a clean Windows workspace.
- This is a fixture/runtime contract, not a claim that production projects
  should replace pytest. A production workspace should instead provide a locked
  environment and its documented test entry point.
