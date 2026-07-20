# Iteration 12: Kimi provider integration — a real Chat Completions backend

## Trigger

Iteration 11 closed two live-path bugs but left the provider story stuck: the
`openai` and `anthropic` profiles both route through `right.codes`, which returns
HTTP 403 (`API Key 不允许访问该渠道…`) — a channel-permission setting on the
proxy, not a Moka defect (see
[INC-0004](../incidents/INC-0004-live-provider-auth-block.md)). Direct DeepSeek
works, but the request was explicit: drop openai/claude, switch to Kimi
(Moonshot) and verify against the real API.

The switch forced a real design decision rather than a config tweak, because
Moonshot does not implement the OpenAI **Responses** API.

## Design decision 1 — a new client, not a widened one

`OpenAICompatibleModelClient` speaks the Responses API: `POST /v1/responses` with
`input` + `max_output_tokens`. Moonshot only implements Chat Completions
(`POST /v1/chat/completions` with `messages` + `max_tokens`) — calling `/responses`
returns `403 {"error":"The API you are accessing is not open"}`.

So a new `ChatCompletionsModelClient` was added (`pico/providers/clients.py`)
instead of making `OpenAICompatibleModelClient` carry two wire protocols. One class
per wire protocol keeps each `complete()` path readable: the difference is the
endpoint, the request body field names, and the response `choices[].message.content`
shape — all of which a single class would have to branch on.

The client is wired through the existing protocol router:

- `PROTOCOLS = {"openai", "anthropic", "openai_chat"}` (`pico/config/__init__.py`)
- `ProviderClientClasses.openai_chat` default (`pico/providers/runtime.py`)
- `model_client_from_config` `openai_chat` branch
- exported from `pico/providers` and `pico`, and `_provider_client_classes()` in `pico/cli.py`

## Design decision 2 — `kimi` is a first-class provider, not a one-off

Rather than hardcoding a Kimi endpoint in a script, `kimi` joined the provider
table so every existing resolution path (explicit `.pico.toml`, generic env,
`PICO_*` legacy env, aliases) works unchanged:

- `PROVIDER_DEFAULTS["kimi"]` → `protocol="openai_chat"`, `base_url=https://api.moonshot.cn/v1`,
  `model=moonshot-v1-128k`, `supports_vision=False`
- `PROVIDER_MAX_TOKENS["kimi"] = 8192`
- `PROVIDER_ENV_NAMES["kimi"]` / `LEGACY_ENV_NAMES["kimi"]` → `KIMI_API_KEY` / `MOONSHOT_API_KEY`, etc.
- `PROVIDER_ALIASES["moonshot"] = "kimi"`

## Design decision 3 — `moonshot-v1-128k`, not a reasoning model

Kimi's reasoning models (`kimi-k2.5`, `kimi-k2.7-code`, `kimi-k3`) force
`temperature=1` and reject any other value with `400 invalid temperature: only 1
is allowed for this model`. An agent needs `temperature=0` for deterministic
tool-planning. `moonshot-v1-128k` is a non-reasoning model that accepts
`temperature=0`, so it is the profile default. (The decision is a config
default, not a code restriction — a reasoning model can still be selected via
`--model` if a caller wants it, they just inherit its temperature constraint.)

## Design decision 4 — prompt cache is explicitly off

`ChatCompletionsModelClient.supports_prompt_cache = False`. The Responses API has
a first-class prompt-cache contract; the generic `/chat/completions` endpoint has
no equivalent cross-provider semantic. Setting it false closes the cache wiring
rather than passing a "looks uniform but means nothing" parameter and letting a
later reader assume caching is active when it is not.

## Live verification (real provider-billed tokens)

```python
cfg = resolve_provider_config("kimi", start=".")
client = model_client_from_config(cfg, args)   # -> ChatCompletionsModelClient
text = client.complete("用一句话解释什么是贪心算法", max_new_tokens=64)
```

Result: correct UTF-8 text returned; `completion_metadata`:
`{"input_tokens": 14, "output_tokens": 36, "total_tokens": 50, "cached_tokens": 0,
"cache_hit": false, "provider_protocol": "openai_chat", ...}`. These are the
`usage` values Moonshot returns per response — real billing numbers, not
`estimated_proxy` heuristics — and `_extract_usage_cache_details` normalizes
Moonshot's `input_tokens`/`output_tokens` naming into the same structure the
Anthropic-compatible path already produces.

## Tests

`tests/test_kimi_chat_completions.py` — 4 tests:

- `test_moonshot_alias_normalizes_to_kimi`
- `test_kimi_config_resolves_openai_chat_protocol` (explicit `.pico.toml`)
- `test_kimi_generic_env_used_without_toml` (bare `KIMI_API_KEY` still works)
- `test_chat_completions_client_sends_messages_payload` (mocked transport asserts
  `messages`+`max_tokens`, `/chat/completions` endpoint, and provider-billed usage)

## Commands to reproduce

```bash
# Unit tests
.venv/Scripts/python.exe -m pytest tests/test_kimi_chat_completions.py tests/test_config.py -q

# Live call (key lives in gitignored .pico.toml; script prints key length only)
PYTHONPATH=. python scripts/verify_kimi.py   # if kept; otherwise the inline snippet above
```

## Caveats

- `moonshot-v1-128k` is a 128k-context non-reasoning model; the live call above
  is a single-turn smoke check proving the wire path + real billing, not a
  benchmark or a claim about model quality.
- The Kimi API key is stored in gitignored `.pico.toml` only; no secret appears
  in tests, docs, or committed config.
- **Scope boundary (stated so it is a known edge, not a discovered one):** the
  live *agent runtime* path now supports `openai_chat`, but the *evaluation*
  modules (`pico/evaluation/context_cost.py::_build_live_provider_client`,
  `pico/evaluation/metrics.py::_make_provider_client`) still branch only on
  `openai`/`anthropic`. Their live-provider experiment loops iterate
  `("gpt", "claude", "deepseek")`, so they never hit `kimi` today; wiring
  `openai_chat` into those two helpers (and adding `kimi` to the loop) is the
  natural follow-up if Kimi should be benchmarked through the eval harness.

---

**留痕原则**: every decision above (new client, first-class provider, model
choice, cache-off) is recorded because it is a *choice with a reason*, not a
default the reader has to infer. The live-token figure is quoted from a real
Moonshot `usage` block, reproducible with the snippet in "Live verification".
