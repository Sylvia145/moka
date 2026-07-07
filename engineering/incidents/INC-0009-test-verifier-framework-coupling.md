# INC-0009: Test verifier was coupled to pytest output text

- Date: 2026-08-12
- Severity: medium
- Scope: post-fix DeepSeek order-pricing dogfood run

## Symptom

The live agent read the test and source files, repaired the formula, and ran
the required `unittest` command successfully (`exit_code: 0`). The scenario
still failed its `tests_ran` check.

## Root cause

The original helper looked for the literal text `passed` in a successful shell
result. That happened to match pytest output but not `unittest`, which reports
individual tests as `ok` and a final `OK`.

## Resolution

The test-evidence check now requires a successful `run_shell` result with
`exit_code: 0`. The external verifier remains separate and executes the same
workspace command. Tool success is the contract; framework-specific rendering
is not.

## Regression evidence

The failed artifact is retained in
`artifacts/engineering/business-dogfood/20260812-order-pricing-run3`.
