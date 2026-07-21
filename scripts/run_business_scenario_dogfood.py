#!/usr/bin/env python3
"""Pico 项目运行与验证脚本。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pico import Pico, SessionStore, WorkspaceContext
from pico.config import resolve_provider_config
from pico.evaluation.release_governance import (
    evaluate_run as evaluate_release_governance_run,
)
from pico.evaluation.release_governance import (
    policy_http_server_config,
    policy_server_config,
    release_governance_prompt,
)
from pico.evaluation.release_governance import (
    prepare_workspace as prepare_release_governance_workspace,
)
from pico.evaluation.release_policy_http import release_policy_http_server
from pico.features.skills_runtime import invoke_skill
from pico.providers import (
    AnthropicCompatibleModelClient,
    OpenAICompatibleModelClient,
)

SUMMARY_JSON = "business-scenario-dogfood.json"
SUMMARY_MARKDOWN = "business-scenario-dogfood.md"


def run_dogfood(
    output_dir,
    *,
    config_path=None,
    provider=None,
    model=None,
    base_url=None,
    api_key=None,
    max_steps=8,
    max_new_tokens=1024,
    scenario_ids=None,
):
    """执行 `run_dogfood` 的内部逻辑。"""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    client_factory, provider_meta = _build_client_factory(
        config_path=config_path,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    scenario_specs = [
        ("order_pricing_bugfix", _scenario_order_pricing_bugfix),
        ("release_readiness_review", _scenario_release_readiness_review),
        ("incident_resume_fix", _scenario_incident_resume_fix),
        ("release_governance_with_isolated_worker", _scenario_release_governance_with_isolated_worker),
        ("release_governance_over_http", _scenario_release_governance_over_http),
    ]
    selected = set(scenario_ids or ())
    unknown = selected.difference(name for name, _ in scenario_specs)
    if unknown:
        raise ValueError(f"unknown scenario ids: {', '.join(sorted(unknown))}")
    scenarios = [
        _run_scenario(output_dir, name, runner, client_factory, max_steps, max_new_tokens)
        for name, runner in scenario_specs
        if not selected or name in selected
    ]
    summary = {
        "status": "passed" if all(item["status"] == "passed" for item in scenarios) else "failed",
        "scenario_count": len(scenarios),
        "provider": provider_meta,
        "scenarios": scenarios,
        "artifacts": {
            "json": SUMMARY_JSON,
            "markdown": SUMMARY_MARKDOWN,
        },
    }
    (output_dir / SUMMARY_JSON).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / SUMMARY_MARKDOWN).write_text(render_markdown(summary) + "\n", encoding="utf-8")
    return summary


def render_markdown(summary):
    """执行 `render_markdown` 的内部逻辑。"""
    provider = summary.get("provider", {})
    lines = [
        "# Pico Business Scenario Dogfood",
        "",
        f"- status: `{summary['status']}`",
        f"- scenarios: `{summary['scenario_count']}`",
        f"- provider: `{provider.get('name', '')}` / `{provider.get('model', '')}`",
        "",
        "| Scenario | Status | Report | Trace | Events |",
        "|---|---|---|---|---|",
    ]
    for scenario in summary["scenarios"]:
        lines.append(
            "| {id} | {status} | `{report}` | `{trace}` | `{events}` |".format(
                id=scenario["id"],
                status=scenario["status"],
                report=scenario.get("report_path", ""),
                trace=scenario.get("trace_path", ""),
                events=scenario.get("session_event_path", ""),
            )
        )
    return "\n".join(lines)


def _run_scenario(output_dir, scenario_id, runner, client_factory, max_steps, max_new_tokens):
    """执行 `_run_scenario` 的内部逻辑。"""
    workspace = output_dir / "workspaces" / scenario_id
    if workspace.exists():
        _remove_tree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        record = runner(output_dir, workspace, client_factory, max_steps, max_new_tokens)
        record["status"] = "passed" if all(check["status"] == "passed" for check in record["checks"]) else "failed"
        return record
    except Exception as exc:  # noqa: BLE001 - 试运行必须保留场景失败证据。
        return {
            "id": scenario_id,
            "status": "failed",
            "workspace_relpath": _relpath(workspace, output_dir),
            "error": str(exc),
            "checks": [{"name": "scenario_exception", "status": "failed", "detail": str(exc)}],
        }


def _scenario_order_pricing_bugfix(output_dir, workspace, client_factory, max_steps, max_new_tokens):
    """执行 `_scenario_order_pricing_bugfix` 的内部逻辑。"""
    src = workspace / "src"
    tests = workspace / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "order_pricing.py").write_text(
        "def calculate_total(subtotal, discount, tax):\n"
        "    return round(subtotal + discount + tax, 2)\n",
        encoding="utf-8",
    )
    (tests / "test_order_pricing.py").write_text(
        "import unittest\n\n"
        "from src.order_pricing import calculate_total\n\n\n"
        "class OrderPricingTest(unittest.TestCase):\n"
        "    def test_discount_is_subtracted_before_tax_is_added(self):\n"
        "        self.assertEqual(calculate_total(100, 15, 8.5), 93.5)\n",
        encoding="utf-8",
    )
    agent = _build_agent(workspace, client_factory, max_steps=max_steps, max_new_tokens=max_new_tokens)
    answer = agent.ask(
        "订单总价折扣计算错了。请严格按下面步骤执行，每次只返回一个 <tool> 或最后一个 <final>："
        "1) read_file tests/test_order_pricing.py start=1 end=40。"
        "2) read_file src/order_pricing.py start=1 end=40。"
        "3) patch_file src/order_pricing.py，把 `return round(subtotal + discount + tax, 2)` "
        "替换为 `return round(subtotal - discount + tax, 2)`。"
        "4) run_shell `python -m unittest discover -s tests -v`。"
        "5) 测试 passed 后 final。不要改其他文件，不要编造文件内容。"
    )
    return _finalize(
        output_dir,
        workspace,
        agent,
        "order_pricing_bugfix",
        checks=[
            _check("answer_nonempty", bool(answer.strip()), answer),
            _check("pricing_fixed", "subtotal - discount + tax" in (src / "order_pricing.py").read_text(encoding="utf-8")),
            _check("tests_ran", _tool_succeeded(agent, "run_shell")),
            _check("external_tests", _run_tests(workspace).returncode == 0),
        ],
    )


def _scenario_release_readiness_review(output_dir, workspace, client_factory, max_steps, max_new_tokens):
    """执行 `_scenario_release_readiness_review` 的内部逻辑。"""
    (workspace / "README.md").write_text("# Billing API\n\nRelease candidate for tenant billing.\n", encoding="utf-8")
    (workspace / ".env.example").write_text("DATABASE_URL=\nSTRIPE_API_KEY=\n", encoding="utf-8")
    (workspace / "deploy.md").write_text("- migrations applied\n- rollback owner assigned\n", encoding="utf-8")
    skill_dir = workspace / ".pico" / "skills" / "release"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: release
description: Release readiness reviewer
allowed-tools: read_file, search, write_file
---
Review release readiness for $ARGUMENTS. Read README.md, .env.example, and deploy.md. Write a concise
blocking/non-blocking checklist to reports/release-readiness.md. Do not edit source files.
""",
        encoding="utf-8",
    )
    agent = _build_agent(workspace, client_factory, max_steps=max_steps, max_new_tokens=max_new_tokens)
    answer = invoke_skill(agent, "release", "billing-api")
    events = _read_events(agent)
    report = workspace / "reports" / "release-readiness.md"
    report_text = report.read_text(encoding="utf-8") if report.exists() else ""
    return _finalize(
        output_dir,
        workspace,
        agent,
        "release_readiness_review",
        checks=[
            _check("answer_nonempty", bool(answer.strip()), answer),
            _check("skill_invoked", any(event["event"] == "skill_invoked" for event in events)),
            _check("skill_completed", any(event["event"] == "skill_completed" for event in events)),
            _check("report_written", report.is_file()),
            _check(
                "report_mentions_config_gap",
                any(token in report_text.upper() for token in ("WEBHOOK", "SECRET", "STRIPE", "API_KEY", "DATABASE_URL")),
            ),
            _check("business_files_unchanged", "PAYMENT_WEBHOOK_SECRET" not in (workspace / ".env.example").read_text(encoding="utf-8")),
        ],
    )


def _scenario_incident_resume_fix(output_dir, workspace, client_factory, max_steps, max_new_tokens):
    """执行 `_scenario_incident_resume_fix` 的内部逻辑。"""
    src = workspace / "src"
    tests = workspace / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "incident_router.py").write_text(
        "def classify_latency(ms):\n"
        "    return 'ok' if ms < 1000 else 'page'\n",
        encoding="utf-8",
    )

    (tests / "test_incident_router.py").write_text(
        "import unittest\n\n"
        "from src.incident_router import classify_latency\n\n\n"
        "class IncidentRouterTest(unittest.TestCase):\n"
        "    def test_degraded_threshold_routes_before_page(self):\n"
        "        self.assertEqual(classify_latency(750), 'degraded')\n"
        "        self.assertEqual(classify_latency(1500), 'page')\n",
        encoding="utf-8",
    )
    store = SessionStore(workspace / ".pico" / "sessions")
    first = Pico(
        model_client=client_factory(),
        workspace=_scenario_workspace(workspace),
        session_store=store,
        approval_policy="auto",
        max_steps=max_steps,
        max_new_tokens=max_new_tokens,
    )
    first_answer = first.ask(
        "线上延迟告警误分级。请严格按下面步骤执行，每次只返回一个 <tool> 或最后一个 <final>："
        "1) todo_add content='Fix latency incident routing' status='in_progress' priority='high'。"
        "2) read_file tests/test_incident_router.py start=1 end=80。"
        "3) read_file src/incident_router.py start=1 end=80。"
        "4) final，说明已定位，等待恢复继续。不要改代码。"
    )
    resumed = Pico.from_session(
        model_client=client_factory(),
        workspace=_scenario_workspace(workspace),
        session_store=store,
        session_id=first.session["id"],
        approval_policy="auto",
        max_steps=max_steps,
        max_new_tokens=max_new_tokens,
    )
    answer = resumed.ask(
        "继续刚才的事故修复。请严格按下面步骤执行，每次只返回一个 <tool> 或最后一个 <final>："
        "1) patch_file src/incident_router.py，把 `return 'ok' if ms < 1000 else 'page'` "
        "替换为 `return 'ok' if ms < 500 else 'degraded' if ms < 1000 else 'page'`。"
        "2) run_shell `python -m unittest discover -s tests -v`。"
        "3) todo_update todo_id='todo_1' status='done' note='threshold fixed and tests verified'。"
        "4) 测试 passed 后 final。不要改其他文件。"
    )
    return _finalize(
        output_dir,
        workspace,
        resumed,
        "incident_resume_fix",
        checks=[
            _check("first_answer_nonempty", bool(first_answer.strip()), first_answer),
            _check("answer_nonempty", bool(answer.strip()), answer),
            _check("same_session", resumed.session["id"] == first.session["id"]),
            _check("todo_done", any(item.get("status") == "done" for item in resumed.session.get("todos", {}).get("items", []))),
            _check("incident_fixed", "degraded" in (src / "incident_router.py").read_text(encoding="utf-8")),
            _check("tests_ran", _tool_succeeded(resumed, "run_shell")),
            _check("external_tests", _run_tests(workspace).returncode == 0),
        ],
    )


def _scenario_release_governance_with_isolated_worker(
    output_dir, workspace, client_factory, max_steps, max_new_tokens
):
    """执行 `_scenario_release_governance_with_isolated_worker` 的内部逻辑。"""
    server_path = prepare_release_governance_workspace(workspace)
    agent = _build_agent(
        workspace,
        client_factory,
        max_steps=max_steps,
        max_new_tokens=max_new_tokens,
        mcp_servers=(policy_server_config(server_path),),
    )
    try:
        answer = agent.ask(release_governance_prompt())
        checks = [
            _check("answer_nonempty", bool(answer.strip()), answer),
            *evaluate_release_governance_run(agent, workspace),
        ]
        return _finalize(
            output_dir,
            workspace,
            agent,
            "release_governance_with_isolated_worker",
            checks,
        )
    finally:
        agent.mcp_clients["release_policy"].close()


def _scenario_release_governance_over_http(
    output_dir, workspace, client_factory, max_steps, max_new_tokens
):
    """执行 `_scenario_release_governance_over_http` 的内部逻辑。"""
    prepare_release_governance_workspace(workspace)
    with release_policy_http_server(response_mode="sse") as (url, _state):
        agent = _build_agent(
            workspace,
            client_factory,
            max_steps=max_steps,
            max_new_tokens=max_new_tokens,
            mcp_servers=(policy_http_server_config(url),),
        )
        try:
            answer = agent.ask(release_governance_prompt())
            checks = [
                _check("answer_nonempty", bool(answer.strip()), answer),
                *evaluate_release_governance_run(agent, workspace),
            ]
            return _finalize(
                output_dir,
                workspace,
                agent,
                "release_governance_over_http",
                checks,
            )
        finally:
            agent.mcp_clients["release_policy"].close()


def _build_agent(workspace, client_factory, max_steps=8, max_new_tokens=1024, mcp_servers=None):
    """执行 `_build_agent` 的内部逻辑。"""
    return Pico(
        model_client=client_factory(),
        workspace=_scenario_workspace(workspace),
        session_store=SessionStore(workspace / ".pico" / "sessions"),
        approval_policy="auto",
        max_steps=max_steps,
        max_new_tokens=max_new_tokens,
        mcp_servers=mcp_servers,
    )


def _scenario_workspace(workspace):
    """执行 `_scenario_workspace` 的内部逻辑。"""
    return WorkspaceContext.build(workspace, repo_root_override=workspace)


def _build_client_factory(*, config_path=None, provider=None, model=None, base_url=None, api_key=None):
    """执行 `_build_client_factory` 的内部逻辑。"""
    config = resolve_provider_config(
        provider,
        start=ROOT,
        config_path=config_path,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    if not config.api_key:
        raise ValueError(f"provider {config.name!r} has no api key; configure .pico.toml or pass --api-key")

    def factory():
        """执行 `factory` 的内部逻辑。"""
        if config.protocol == "openai":
            return OpenAICompatibleModelClient(
                model=config.model,
                base_url=config.base_url,
                api_key=config.api_key,
                temperature=0,
                timeout=300,
            )
        if config.protocol == "anthropic":
            return AnthropicCompatibleModelClient(
                model=config.model,
                base_url=config.base_url,
                api_key=config.api_key,
                temperature=0,
                timeout=300,
            )
        raise ValueError(f"unknown provider protocol: {config.protocol}")

    return factory, {
        "name": config.name,
        "protocol": config.protocol,
        "base_url": config.base_url,
        "model": config.model,
    }


def _finalize(output_dir, workspace, agent, scenario_id, checks):
    """执行 `_finalize` 的内部逻辑。"""
    run_dir = agent.current_run_dir
    report_path = run_dir / "report.json"
    trace_path = run_dir / "trace.jsonl"
    session_event_path = agent.session_event_bus.path
    checks.extend(
        [
            _check("report_exists", report_path.is_file()),
            _check("trace_exists", trace_path.is_file()),
            _check("session_events_exists", session_event_path.is_file()),
        ]
    )
    return {
        "id": scenario_id,
        "workspace_relpath": _relpath(workspace, output_dir),
        "session_event_path": _relpath(session_event_path, output_dir),
        "run_dir": _relpath(run_dir, output_dir),
        "report_path": _relpath(report_path, output_dir),
        "trace_path": _relpath(trace_path, output_dir),
        "checks": checks,
    }


def _read_events(agent):
    """执行 `_read_events` 的内部逻辑。"""
    return [
        json.loads(line)
        for line in agent.session_event_bus.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _history_contains(agent, tool_name, text):
    """执行 `_history_contains` 的内部逻辑。"""
    return any(
        item.get("role") == "tool"
        and item.get("name") == tool_name
        and text in str(item.get("content", ""))
        for item in agent.session["history"]
    )


def _tool_succeeded(agent, tool_name):
    """执行 `_tool_succeeded` 的内部逻辑。"""
    return any(
        item.get("role") == "tool"
        and item.get("name") == tool_name
        and "exit_code: 0" in str(item.get("content", ""))
        for item in agent.session["history"]
    )


def _run_tests(workspace):
    """执行 `_run_tests` 的内部逻辑。"""
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
        check=False,
    )


def _check(name, condition, detail=""):
    """执行 `_check` 的内部逻辑。"""
    return {"name": name, "status": "passed" if condition else "failed", "detail": str(detail)}


def _relpath(path, root):
    """执行 `_relpath` 的内部逻辑。"""
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def _remove_tree(path):
    """执行 `_remove_tree` 的内部逻辑。"""
    for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_dir():
            child.rmdir()
        else:
            child.unlink()
    path.rmdir()


def build_arg_parser():
    """执行 `build_arg_parser` 的内部逻辑。"""
    parser = argparse.ArgumentParser(description="Run Pico business scenario dogfood against a real provider.")
    parser.add_argument("--output-dir", default="/tmp/pico-business-scenario-dogfood", help="Directory for workspaces and summary artifacts.")
    parser.add_argument("--config", default=None, help="Path to a Pico TOML config file.")
    parser.add_argument("--provider", default=None, help="Provider profile to use.")
    parser.add_argument("--api-key", default=None, help="API key override for the selected provider profile.")
    parser.add_argument("--base-url", default=None, help="Base URL override for the selected provider profile.")
    parser.add_argument("--model", default=None, help="Model override for the selected provider profile.")
    parser.add_argument("--max-steps", type=int, default=8, help="Max Pico steps per scenario turn.")
    parser.add_argument("--max-new-tokens", type=int, default=1024, help="Max provider output tokens per model turn.")
    parser.add_argument("--scenario", action="append", help="Run only this scenario id; repeat for multiple scenarios.")
    return parser


def main(argv=None):
    """执行 `main` 的内部逻辑。"""
    args = build_arg_parser().parse_args(argv)
    summary = run_dogfood(
        Path(args.output_dir),
        config_path=args.config,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        scenario_ids=args.scenario,
    )
    print(json.dumps({"status": summary["status"], "scenario_count": summary["scenario_count"]}, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
