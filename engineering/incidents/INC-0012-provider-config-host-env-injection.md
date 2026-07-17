# INC-0012: Host-injected generic env vars silently overrode project provider config

- Date: 2026-08-16
- Severity: high (silent config corruption — the `anthropic` profile actually called DeepSeek)
- Evidence: `resolve_provider_config("anthropic")` before/after; 4 regression tests in `tests/test_config.py`

## Symptom

`resolve_provider_config("anthropic")` returned DeepSeek's `model` and `base_url`
(`deepseek-v4-pro @ https://api.deepseek.com/anthropic`) instead of
`.pico.toml`'s explicit `claude-sonnet-4-6 @ https://www.right.codes/claude/v1`.
DeepSeek — the default profile used by the iteration-11 business dogfood — resolved
correctly, which is why the dogfood passed; but any `--provider anthropic` run would
have silently called DeepSeek's backend while labeling the model `claude-sonnet-4-6`.

## Root cause

Two facts interacted:

1. Iteration D7 introduced `_env_values`, which reads generic non-`PICO_` env names
   (`ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, …) so a bare
   `ANTHROPIC_API_KEY` in a CI environment still works without project config.
2. The Claude Code host (configured to use a DeepSeek backend) injects exactly those
   generic names into the child process environment: `ANTHROPIC_MODEL=deepseek-v4-pro`,
   `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`, `ANTHROPIC_AUTH_TOKEN=<35 chars>`.

The resolution chain placed `env_values` (generic env) *above* `.pico.toml`, so the
host's implicit, process-wide settings silently beat the project's explicit,
intentional config. The generic name is shared between a host convention and a
project convention, and the host won.

## Resolution

`.pico.toml`'s explicit provider section now precedes generic env in the chain for
`model`, `base_url`, and `api_key`:

```python
resolved_model = _first_value(
    model,
    os.environ.get(ENV_MODEL),          # PICO_MODEL
    explicit_profile.get("model"),      # .pico.toml explicit — now above generic env
    env_values.get("model"),            # generic env (ANTHROPIC_MODEL, …)
    legacy_env.get(ENV_MODEL),
    legacy_values.get("model"),
    default_values.get("model"),
)
```

Project-level, intentional configuration is now trusted more than implicit host
inheritance. `PICO_*`-prefixed and `.env` legacy paths are unchanged.

## Regression

`tests/test_config.py` — 4 tests:

- `test_explicit_toml_beats_generic_model_and_base_url`
- `test_explicit_toml_beats_generic_api_key`
- `test_generic_env_still_used_without_toml` (generic env is *not* dead without toml)
- `test_generic_model_env_still_used_without_toml`

The last two pin the back-compat behavior so the fix cannot regress bare-env setups.

## Co-diagnosed, external (not a Moka defect): right.codes 403

Fixing this bug *surfaced* the real credential state. Before the fix, `anthropic`
silently routed to DeepSeek and "worked"; after the fix it correctly targets
`right.codes/claude` and returns HTTP 403:

```
{"error": "API Key 不允许访问该渠道，请前往令牌管理界面修改令牌权限"}
```

`openai` (right.codes/codex) fails the same way; `deepseek` (direct
`api.deepseek.com`) succeeds. This is a channel-permission setting on the right.codes
proxy, not a code defect in Moka — see INC-0004 for the earlier 401. The engineering
takeaway for an interview: *fixing the config bug did not invent a new failure — it
replaced a silent mislabeling with the honest credential error that was always there.*
