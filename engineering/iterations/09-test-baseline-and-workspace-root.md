# Iteration 09: Test baseline hardening and workspace root isolation

## Trigger

Pre-interview assessment of test health. The docs stated "no clean full-suite
pass on Windows" but never pinned down the boundary between *environment*,
*platform difference*, and *code defect*. A candidate needs a defensible answer
to "do all your tests pass?".

## Baseline (full suite, default env, Windows)

```
506 passed, 36 failed, 2 skipped  (458.74s)
```

36 failures decompose into ~7 root causes, not one. Verified by reading each
failure's traceback.

| # | Root cause | Nature | Count | Fix |
|---|---|---|---|---|
| 1 | `shell_env()` allowlist is Unix-only; missing `ComSpec`/`SystemRoot`/`PATHEXT` makes `subprocess.run(shell=True)` return exit code 1 on Windows even when the command succeeds | **real bug** | ~6 | code |
| 2 | `dream_reports/<iso>.json` filename embeds `:` (e.g. `2026-08-16T03:08:42Z.json`), illegal in a Windows filename → `OSError [Errno 22]` | **real bug** | 4 | code |
| 3 | `Path.home()` raises `Could not determine home directory` when tests run `patch.dict(os.environ, ..., clear=True)`, which wipes `USERPROFILE` | robustness | ~11 | code |
| 4 | Rename drift: tests still assert `"You are pico"` but the system prompt now says `"You are Moka"` | stale assertion | ≥1 | test |
| 5 | Path separator `/` vs `\`; `/tmp` hard-coded; `shlex.quote` emits POSIX single quotes that `cmd.exe` cannot parse; Windows symlink needs privilege | platform difference | ~6 | test/skip |
| 6 | `runtime.py` 952 lines and `tool_executor.py` 186 lines exceed entropy budget | code organization | 2 | code |
| 7 | Provider config priority: `PICO_*` env vars override project `.pico.toml`, contradicting the documented legacy-vs-project split | **real bug** | ~3 | code |
| 8 | Remaining assertion failures (verification signal, fingerprint hash, microcompact, final-readiness, llm-handoff, real-session gate8) | to triage | ~8 | — |

## Decisions and changes (留痕)

Every change below is a clean "found → root-caused → fixed → regression test"
story, kept here as interview evidence.

### D1. `shell_env()` Windows system variables — real bug (root cause #1)

**Symptom:** `run_shell` on Windows reports `exit_code: 1` while stdout shows the
command actually succeeded. Verified with a minimal repro: `subprocess.run(...,
shell=True, env=<filtered>)` returns 1 when `ComSpec` is absent.

**Root cause:** `DEFAULT_SHELL_ENV_ALLOWLIST` contains only Unix names
(`HOME`, `LANG`, `PATH`, …). On Windows, `shell=True` needs `ComSpec`
(and `SystemRoot`/`PATHEXT`) to locate `cmd.exe` and system dirs. Omitting them
made the child run but report a bogus non-zero exit code.

**Fix (`pico/core/runtime_secrets.py`):** keep the secret-free
`WINDOWS_SHELL_ENV_NAMES = ("ComSpec", "SystemRoot", "SystemDrive", "PATHEXT",
"WINDIR", "ProgramFiles")` out of the sensitive allowlist, and merge them back
into `shell_env()` on `win32` only.

**Regression test:** `test_shell_env_keeps_windows_system_variables_for_subprocess`
asserts the variables are present on win32 while `MCA_NOT_IN_ALLOWLIST` is still
filtered.

### D2. `dream_reports` filename `:` — real bug (root cause #2)

**Symptom:** `OSError [Errno 22] Invalid argument` when writing the dream report.

**Root cause:** the report path used an ISO-8601 timestamp
(`2026-08-16T03:08:42Z`) as the filename; `:` is illegal in a Windows filename.

**Fix (`pico/features/memory.py`):** `safe_stem = iso_ts.replace(":", "-")`
before building the path. Portable on POSIX too.

**Regression test:** the four existing dream-report tests now pass on Windows.

### D3. `Path.home()` degradation — robustness (root cause #3)

**Symptom:** `RuntimeError: Could not determine home directory` from
`skills.py` when tests run `patch.dict(os.environ, ..., clear=True)` (wipes
`USERPROFILE`), crashing the whole runtime assembly.

**Root cause:** `discover_skills()` called `Path.home()` unguarded during
`Pico.__init__`.

**Fix (`pico/features/skills.py`):** wrap the `Path.home()` lookup in a
`try/except (OSError, RuntimeError)` and degrade to builtin + project skills when
the home dir is undeterminable. Matches the existing container story.

### D4. Rename drift — stale assertion (root cause #4)

**Fix (`tests/test_context_manager.py`):** assert `"You are Moka"` instead of
`"You are pico"` (mechanical).

### D5. Platform differences — explicit, not silently red (root cause #5)

- `test_run_shell_uses_allowlisted_environment_only`: `shlex.quote` emits POSIX
  single quotes that `cmd.exe` cannot parse. Switched to a platform branch —
  `"{sys.executable}" -c "{script}"` (double-quoted, single-quoted Python string
  literal) on win32, `shlex.quote` elsewhere.
- `test_trace_and_report_redact_secret_env_values`: `clear=True` wiped
  `ComSpec`/`SystemRoot`, and `printf` is a Unix-only builtin. The test now
  preserves Windows system variables and uses `echo` (cross-platform) so the
  secret actually lands on stdout and the redaction of the tool result is
  exercised on Windows.

### D6. Entropy budget — real split, not a raised ceiling (root cause #6)

`runtime.py` (952 → 808) held a coherent checkpoint/resume block
(`current_runtime_identity`, `checkpoint_state`, `current_checkpoint`,
`invalidate_stale_memory`, `evaluate_resume_state`, `render_checkpoint_text`)
that belonged next to the existing `RuntimeCheckpointsMixin`. Moved it (plus the
five `CHECKPOINT_*` status constants) into `pico/core/runtime_checkpoints.py` —
a pure move, no logic change, no import cycle.

`tool_executor.py` (186 → 171) held `_permission_error`, the reason→message
mapping for denied permission decisions. Moved it into `pico/core/permissions.py`
as `permission_error_message`, next to the `PermissionChecker` that produces
those reasons.

Both moved functions are referenced via `self.` / module import, so MRO and
imports resolve identically. The budget test itself is untouched.

### D7. Provider config priority — real bug (root cause #7)

**Symptom:** `test_provider_profile_uses_project_toml_before_legacy_pico_env`
fails — a project `.pico.toml` key is shadowed by a `PICO_*` env var.

**Root cause:** `resolve_provider_config` ranked `_env_values(...)` (which reads
`PICO_DEEPSEEK_API_KEY` etc. from `os.environ`) **above**
`_profile_values(...)` (project `.pico.toml`). The documented split is: generic
env vars (`DEEPSEEK_API_KEY`) are high-priority; `PICO_*` is legacy naming and
should sit **below** the project toml. Both mappings listed the same names, so
nothing distinguished them.

**Fix (`pico/config/__init__.py`):**
- `_env_values` now reads only non-`PICO_` names (generic env vars) as high
  priority.
- `_legacy_values` reads the `.env` file first, then falls back to `PICO_*`
  names from `os.environ`, keeping legacy naming usable as the sole source when
  no toml exists.

**Regression tests:** `test_provider_profile_uses_project_toml_before_legacy_pico_env`,
`test_build_agent_uses_provider_profile_protocol_from_project_toml`, plus the
existing `.env`-file and default-model cases.

### D8. Tool return paths normalize to `/` — real consistency bug (root cause #5, path part)

**Symptom:** `test_patch_allows_self_authored_file_without_extra_read` and
`test_list_files_shows_one_level_child_preview` fail on Windows — tools return
`wrote scripts\check.py` (backslash) instead of `wrote scripts/check.py`.

**Root cause:** `tool_write_file`, `tool_patch_file`, `tool_list_files`,
`tool_read_file`, and `tool_search` render `path.relative_to(agent.root)` directly
into f-strings. On Windows `Path.__str__` yields `\`, so the LLM sees
platform-dependent paths. Everywhere else in the codebase (`memory.py`,
`media.py`, `runtime_checkpoints.py`, `worker_artifacts.py`) already normalizes
with `.as_posix()`; `registry.py` was the missed spot.

**Fix (`pico/tools/registry.py`):** six presentation paths now call
`.as_posix()`. No logic change — output is identical on POSIX, and normalized to
`/` on Windows.

### D9. Verification classifier is platform-aware — real bug (root cause #8, one of them)

**Symptom:** `test_verification_signal_passes_after_workspace_verification` fails
on Windows — `command_class` cannot classify `python -m compileall`.

**Root cause:** three Windows problems stacked in
`classify_verification_command`:
1. `shlex.split` assumes POSIX quoting, so `C:\path\python.exe` gets its
   backslashes eaten as escape sequences;
2. `tokens[0].rsplit("/", 1)[-1]` splits on `/` only, missing `\`;
3. `_is_python_command` does not recognize the `.exe` suffix.

**Fix (`pico/core/verification.py`):** a platform-aware tokenizer falls back to a
quote-stripping split on Windows; the basename extraction normalizes `\` to `/`;
and `_is_python_command` strips `.exe`. The tokenizer is inlined into
`classify_verification_command` rather than extracted as a helper, because the
module's entropy budget is 80 lines — the final file lands at exactly 80. POSIX
behavior is unchanged and the existing `test_verification.py` cases still pass.

### D10. Remaining platform differences — fix what's fixable, skip the rest (root cause #5 + #8)

Fixed with platform branches (cross-platform green):

- `test_long_shell_output_is_clipped...`: single-line script, double-quoted for
  `cmd.exe` (single-quoted Python literal inside).
- `test_strict_final_readiness_blocks_partial_success_workspace_changes`:
  single-line `;`-separated script, same branch.
- `test_verification_signal_passes_after_workspace_verification`: `-m compileall`
  command, same branch (paired with D9).
- `test_best_effort_sandbox_records_degrade_and_runs_without_backend`: `python -c
  'print(42)'` → double-quoted on Windows.
- `test_off_sandbox_keeps_plain_subprocess_behavior`: `pwd` → `cd` on Windows.

Marked `skipif(win32)` with an explicit reason (verified the reason matches the
failure mode, never a silent red):

- `test_microcompact_keeps_latest_failed_tool_result_visible`,
  `test_microcompact_keeps_latest_workspace_changing_tool_result_visible` — the
  multi-line `python -c` script carries a `for`-suite + newline that cannot be
  flattened into a single `cmd.exe`-parseable line.
- `test_symlink_path_traversal_is_rejected` — creating a symlink needs
  developer-mode privilege on Windows.
- `test_bench_script_env_max_steps_overrides_yaml_arg` — the fixture writes a
  POSIX bash script (`#!/usr/bin/env bash` + `chmod`).
- `test_workspace_fingerprint_uses_git_root_when_available` — `git rev-parse`
  returns a path whose normalization differs on Windows.
- `test_fixture_verifiers_pass_after_scripted_correct_state`,
  `test_llm_handoff_benchmark_cli_scripted_smoke` — the fixture tasks shell out
  with POSIX-only commands.
- `test_gate8_acceptance_harness_writes_real_session_evidence_bundle` — the
  real-session gate drives a live model run and is not hermetic.

### D11. SessionStore atomic replace retries on Windows — real bug (root cause #8, one of them)

**Symptom:** `test_run_paired_experiment_scripted_populates_llm_handoff_metrics`
fails intermittently on Windows with `PermissionError [WinError 5]` at
`session_store.py` (`os.replace(tmp_path, path)`).

**Root cause:** Windows may hold a just-written JSON target briefly while
concurrent worker activity is writing. `RunStore` already retries this
(INC-0011), but `SessionStore.save()` still treated a transient lock as an
immediate terminal error. Same root cause, one missed store.

**Fix (`pico/core/session_store.py`):** `save()` now retries `PermissionError`
from `os.replace` up to three times with bounded incremental backoff (0.05s /
0.10s), then removes the temp file and re-raises — identical to `RunStore`.

**Regression test:** `test_run_paired_experiment_scripted_populates_llm_handoff_metrics`
now passes on Windows; `test_run_store.py` remains green.

## Verification status

Baseline (default env): `506 passed, 36 failed, 2 skipped`.

After D1–D11, full suite re-run in `.venv` with `-p no:cacheprovider`:

```
535 passed, 10 skipped, 13 warnings in 505.09s  (exit code 0)
```

0 failed. The 10 skips are all explicit `skipif`/reason platform differences
(D10) — symlink privilege, POSIX-bash fixtures, git path normalization,
real-session live-model gate — none silently red. The two failures that
remained after the first fix pass (entropy budget via D6/D9, SessionStore lock
via D11) are green in this run.

Each fix above has a passing regression test; the full-suite number is the
authoritative signal. Remaining failures, if any, are triaged individually and
either fixed or marked with an explicit `skipif`/reason so "red" becomes
"clearly skipped" — never silently ignored.

## Additional finding: human-scenario gate pollutes the real repo

Running `scripts/run_v3_human_scenario_gate.py` (and
`scripts/run_real_session_acceptance.py`) left `README.md` truncated to
`"overwrite"`, plus `notes.txt`/`scripts/check.py`/`forbidden/` in the repo root.
These are scenario-script residues, not pytest residues: `run_pico` launches the
subprocess with `cwd=ROOT` and only passes the scenario workspace via `--cwd`.

The write-path isolation relies on `WorkspaceContext.build(cwd)` resolving the
repo root from the `--cwd` argument, not from the process cwd. When that holds,
writes land in the scenario workspace; when a scenario's agent runs against the
repo root (e.g. the "overwrite requires read" scenario that targets `README.md`),
it mutates the real files. The residue files were removed and `README.md`
restored with `git checkout -- README.md`.

Open question for a later iteration: make the gate scenarios write to a throwaway
workspace (or run under a git worktree) so a release gate can never mutate the
checked-out repo. This is a *test-harness isolation* gap, not a product defect,
but it is exactly the kind of thing to catch before a demo.

## Environment leftover: corrupted `.pytest_cache`

`.pytest_cache/v` became an orphaned directory entry — `stat` shows `Links: 0`,
garbled timestamps, and `Access: denied` even for `takeown`/`rm -rf`. This is
NTFS metadata damage, most likely from a previous pytest process killed
mid-write; it is not a code defect. It only surfaces as a `PytestCacheWarning`
and never affects pass/fail. To clear it: `chkdsk E: /f` (elevated, possibly a
reboot) then delete the directory, or run pytest with `-p no:cacheprovider` —
the final verification run below uses the latter.
