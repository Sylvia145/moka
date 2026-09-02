"""可审计记忆跨 Session 端到端演示与确定性配对评测。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from ..core.runtime import Pico, SessionStore
from ..core.workspace import WorkspaceContext
from ..providers.errors import ProviderError
from ..testing import ScriptedModelClient


def _read_jsonl(path):
    """读取 JSONL Trace。"""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


SCENARIOS = (
    {
        "id": "config_supersede",
        "category": "fact_update",
        "path": "provider.txt",
        "query": "What provider endpoint should this project use?",
        "memory_line": "Project convention: Provider endpoint is https://api.new.example/v1.",
        "old_memory_line": "Project convention: Provider endpoint is https://api.old.example/v1.",
        "source": "endpoint=https://api.new.example/v1\n",
        "answer": "Use https://api.new.example/v1.",
    },
    {
        "id": "debug_procedure",
        "category": "procedure_reuse",
        "path": "logs/parser-error.log",
        "query": "How should I resolve the parser error?",
        "memory_line": "Decision: For parser errors, inspect logs/parser-error.log and run tests/test_parser.py first.",
        "source": "parser error: invalid header\nverified command: pytest tests/test_parser.py -q\n",
        "answer": "Inspect logs/parser-error.log and run tests/test_parser.py first.",
    },
    {
        "id": "release_guardrail",
        "category": "guardrail_reuse",
        "path": "release/checklist.txt",
        "query": "What must happen before editing the release configuration?",
        "memory_line": "Guardrail: Run tests/test_release.py before editing release configuration.",
        "source": "release configuration requires verifier\n",
        "answer": "Run tests/test_release.py before editing release configuration.",
    },
    {
        "id": "multifile_refactor",
        "category": "multifile_reuse",
        "path": "src/profile.py",
        "query": "Which files belong to the profile refactor?",
        "memory_line": "Project convention: Profile refactor changes src/profile.py and tests/test_profile.py.",
        "source": "profile module boundary\n",
        "answer": "Change src/profile.py and tests/test_profile.py.",
    },
    {
        "id": "dependency_stale_anchor",
        "category": "stale_anchor",
        "path": "requirements.txt",
        "query": "Which httpx version is currently required?",
        "memory_line": "Dependency: HTTP client is httpx 0.28.",
        "source": "httpx==0.28\n",
        "changed_source": "httpx==0.29\n",
        "answer": "httpx 0.29 requires rereading requirements.txt.",
    },
)


class _BootstrapClient(ScriptedModelClient):
    """在来源 Session 写入可锚定文件并输出可晋升结论。"""

    def __init__(self, scenario, memory_line, source):
        super().__init__([])
        self.scenario = scenario
        self.memory_line = memory_line
        self.source = source
        self.phase = "write"

    def complete(self, prompt, max_new_tokens, **kwargs):
        """按固定顺序模拟来源任务。"""
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        if self.phase == "write":
            self.phase = "final"
            return (
                '<tool>{"name":"write_file","args":{"path":'
                + json.dumps(self.scenario["path"])
                + ',"content":'
                + json.dumps(self.source)
                + "}}</tool>"
            )
        if self.phase == "final":
            self.phase = "done"
            return f"<final>Verified source and captured durable memory.\n- {self.memory_line}</final>"
        raise RuntimeError("bootstrap client received an unexpected extra completion")


class _FollowupClient(ScriptedModelClient):
    """检验后续 Session 是否因注入记忆跳过重复读取。"""

    def __init__(self, scenario, expect_memory):
        super().__init__([])
        self.scenario = scenario
        self.expect_memory = bool(expect_memory)
        self.phase = "answer"
        self.memory_seen = False

    def complete(self, prompt, max_new_tokens, **kwargs):
        """当证据已注入时直答，否则读取来源文件后作答。"""
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        expected = self.scenario["memory_line"].split(": ", 1)[1].lower()
        self.memory_seen = expected in prompt.lower()
        if self.phase == "answer" and self.memory_seen:
            self.phase = "done"
            return f"<final>{self.scenario['answer']}</final>"
        if self.phase == "answer":
            self.phase = "after_read"
            return (
                '<tool>{"name":"read_file","args":{"path":'
                + json.dumps(self.scenario["path"])
                + ',"start":1,"end":20}}</tool>'
            )
        if self.phase == "after_read":
            self.phase = "done"
            return f"<final>{self.scenario['answer']}</final>"
        raise RuntimeError("follow-up client received an unexpected extra completion")


def _build_agent(root, client, feature_flags=None):
    """构造隔离 workspace 内的真实 Runtime 实例。"""
    return Pico(
        model_client=client,
        workspace=WorkspaceContext.build(root),
        session_store=SessionStore(root / ".pico" / "sessions"),
        approval_policy="auto",
        auto_dream=False,
        final_readiness_mode="off",
        max_steps=3,
        feature_flags=feature_flags,
    )


def _bootstrap_source(root, scenario):
    """运行一个或两个来源 Session，并返回其审计引用。"""
    runs = []
    if scenario.get("old_memory_line"):
        old_agent = _build_agent(root, _BootstrapClient(scenario, scenario["old_memory_line"], "endpoint=https://api.old.example/v1\n"))
        old_agent.ask("Remember the verified provider configuration for future tasks.")
        runs.append({"session_id": old_agent.session["id"], "run_id": old_agent.current_task_state.run_id, "run_dir": str(old_agent.current_run_dir)})
    source_agent = _build_agent(root, _BootstrapClient(scenario, scenario["memory_line"], scenario["source"]))
    source_agent.ask("Remember the verified result for future tasks.")
    runs.append({"session_id": source_agent.session["id"], "run_id": source_agent.current_task_state.run_id, "run_dir": str(source_agent.current_run_dir)})
    return runs


def _trace_summary(agent):
    """提取后续 Session 的检索、工具和报告证据。"""
    run_dir = Path(agent.current_run_dir)
    events = _read_jsonl(run_dir / "trace.jsonl")
    retrieval = next((event for event in events if event.get("event") == "memory.retrieval"), {})
    return {
        "session_id": agent.session["id"],
        "run_id": agent.current_task_state.run_id,
        "run_dir": str(run_dir),
        "report_path": str(run_dir / "report.json"),
        "tool_steps": int(agent.current_task_state.tool_steps),
        "read_file_calls": sum(1 for event in events if event.get("event") == "tool_executed" and event.get("name") == "read_file"),
        "memory_event": next((event.get("event") for event in events if event.get("event") in {"memory_retrieved", "memory_abstained"}), ""),
        "selected": list(retrieval.get("selected", [])),
        "rejected": list(retrieval.get("rejected", [])),
    }


def _run_variant(root, scenario, memory_enabled):
    """运行一个完整的来源到后续 Session 链路。"""
    source_runs = _bootstrap_source(root, scenario)
    source_path = root / scenario["path"]
    if scenario.get("changed_source"):
        source_path.write_text(scenario["changed_source"], encoding="utf-8")
    flags = None if memory_enabled else {"memory": False, "relevant_memory": False}
    client = _FollowupClient(scenario, expect_memory=memory_enabled and not scenario.get("changed_source"))
    followup_agent = _build_agent(root, client, feature_flags=flags)
    final_answer = followup_agent.ask(scenario["query"])
    trace = _trace_summary(followup_agent)
    expected_selected = memory_enabled and not scenario.get("changed_source")
    selected_texts = [item.get("text", "") for item in trace["selected"]]
    stale_rejected = any(item.get("reject_reason") == "stale_evidence" for item in trace["rejected"])
    passed = (
        final_answer == scenario["answer"]
        and client.memory_seen is expected_selected
        and (scenario["memory_line"].split(": ", 1)[1] in selected_texts if expected_selected else True)
        and (stale_rejected if scenario.get("changed_source") and memory_enabled else True)
    )
    return {
        "variant": "memory_on" if memory_enabled else "memory_off",
        "passed": passed,
        "final_answer": final_answer,
        "memory_seen_by_model": client.memory_seen,
        "source_runs": source_runs,
        "followup": trace,
    }


def _copy_evidence(root, evidence_root, scenario_id, variant):
    """复制脱离临时目录后的运行证据，供 artifact 反查。"""
    destination = Path(evidence_root) / scenario_id / variant / ".pico"
    if destination.exists():
        raise FileExistsError(f"evidence destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / ".pico", destination)
    return destination


def _rebase_evidence_paths(result, evidence_root):
    """将临时 workspace 路径替换为保留后的证据目录引用。"""
    evidence_root = Path(evidence_root)
    for source in result["source_runs"]:
        source["run_dir"] = str(evidence_root / "runs" / source["run_id"])
    followup = result["followup"]
    run_dir = evidence_root / "runs" / followup["run_id"]
    followup["run_dir"] = str(run_dir)
    followup["report_path"] = str(run_dir / "report.json")


def run_memory_e2e_demo_v1(artifact_path, evidence_root=None):
    """执行五场景 memory-on / memory-off 跨 Session 配对评测。"""
    artifact_path = Path(artifact_path)
    evidence_root = Path(evidence_root or artifact_path.parent / f"{artifact_path.stem}-runs")
    rows = []
    for scenario in SCENARIOS:
        variants = []
        for memory_enabled in (True, False):
            variant = "memory_on" if memory_enabled else "memory_off"
            with tempfile.TemporaryDirectory(prefix=f"pico-memory-e2e-{scenario['id']}-{variant}-") as temp_dir:
                root = Path(temp_dir)
                (root / "README.md").write_text("# Memory E2E fixture\n", encoding="utf-8")
                result = _run_variant(root, scenario, memory_enabled)
                result["evidence_root"] = str(_copy_evidence(root, evidence_root, scenario["id"], variant))
                _rebase_evidence_paths(result, result["evidence_root"])
                variants.append(result)
        on, off = variants
        rows.append(
            {
                "scenario_id": scenario["id"],
                "category": scenario["category"],
                "passed": bool(on["passed"] and off["passed"]),
                "memory_on": on,
                "memory_off": off,
                "repeated_read_reduction": off["followup"]["read_file_calls"] - on["followup"]["read_file_calls"],
                "tool_step_reduction": off["followup"]["tool_steps"] - on["followup"]["tool_steps"],
            }
        )
    summary = {
        "total_scenarios": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "failed": sum(not row["passed"] for row in rows),
        "memory_on_correct": sum(row["memory_on"]["passed"] for row in rows),
        "memory_off_correct": sum(row["memory_off"]["passed"] for row in rows),
        "repeated_read_reduction": sum(row["repeated_read_reduction"] for row in rows),
        "tool_step_reduction": sum(row["tool_step_reduction"] for row in rows),
    }
    artifact = {"schema_version": 1, "artifact_type": "memory-e2e-demo-v1", "summary": summary, "rows": rows}
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def run_live_memory_e2e_smoke(artifact_path, provider):
    """在显式授权时运行一条真实模型后续 Session 冒烟。"""
    artifact_path = Path(artifact_path)
    if os.environ.get("PICO_LIVE_SMOKE") != "1":
        artifact = {
            "schema_version": 1,
            "artifact_type": "memory-e2e-live-smoke-v1",
            "status": "skipped",
            "reason": "PICO_LIVE_SMOKE is not enabled",
        }
    else:
        from ..cli import build_agent, build_arg_parser

        scenario = SCENARIOS[1]
        with tempfile.TemporaryDirectory(prefix="pico-memory-e2e-live-") as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Live memory smoke fixture\n", encoding="utf-8")
            source_runs = _bootstrap_source(root, scenario)
            args = build_arg_parser().parse_args(
                [
                    "--cwd",
                    str(root),
                    "--provider",
                    str(provider),
                    "--approval",
                    "auto",
                    "--non-interactive",
                    "--no-auto-dream",
                    "--max-steps",
                    "3",
                    "--max-new-tokens",
                    "512",
                    "--final-readiness",
                    "off",
                    "Use the verified memory when relevant. State the first verified parser-error action and return a final answer.",
                ]
            )
            try:
                agent = build_agent(args)
                final_answer = agent.ask("Use the verified memory when relevant. State the first verified parser-error action and return a final answer.")
                trace = _trace_summary(agent)
                artifact = {
                    "schema_version": 1,
                    "artifact_type": "memory-e2e-live-smoke-v1",
                    "status": "passed" if trace["selected"] and final_answer else "failed",
                    "provider": str(provider),
                    "model": str(getattr(agent.model_client, "model", "") or ""),
                    "source_runs": source_runs,
                    "followup": trace,
                    "final_answer": agent.redact_text(final_answer),
                }
            except (OSError, ProviderError, RuntimeError, ValueError) as exc:
                artifact = {
                    "schema_version": 1,
                    "artifact_type": "memory-e2e-live-smoke-v1",
                    "status": "failed",
                    "provider": str(provider),
                    "reason": exc.__class__.__name__,
                }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact
