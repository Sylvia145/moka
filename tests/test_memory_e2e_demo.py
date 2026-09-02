"""可审计记忆端到端演示测试。"""

import json
from pathlib import Path

from pico.evaluation.memory_e2e_demo import (
    run_live_memory_e2e_smoke,
    run_memory_e2e_demo_v1,
)


def test_memory_e2e_demo_runs_five_cross_session_pairs(tmp_path):
    """验证五个跨 Session 场景及其配对效率合同。"""
    artifact = run_memory_e2e_demo_v1(tmp_path / "memory-e2e-demo-v1.json")

    assert artifact["summary"] == {
        "total_scenarios": 5,
        "passed": 5,
        "failed": 0,
        "memory_on_correct": 5,
        "memory_off_correct": 5,
        "repeated_read_reduction": 4,
        "tool_step_reduction": 4,
    }
    rows = {row["scenario_id"]: row for row in artifact["rows"]}
    for row in rows.values():
        assert row["memory_on"]["followup"]["run_id"]
        assert row["memory_off"]["followup"]["run_id"]
        assert row["memory_on"]["evidence_root"]
        assert Path(row["memory_on"]["followup"]["report_path"]).is_file()
        assert Path(row["memory_off"]["followup"]["report_path"]).is_file()
    assert rows["config_supersede"]["memory_on"]["followup"]["memory_event"] == "memory_retrieved"
    assert rows["release_guardrail"]["memory_on"]["followup"]["selected"][0]["kind"] == "guardrail"
    assert rows["debug_procedure"]["memory_on"]["followup"]["selected"][0]["kind"] == "procedure"
    stale = rows["dependency_stale_anchor"]["memory_on"]["followup"]
    assert stale["memory_event"] == "memory_abstained"
    assert stale["rejected"][0]["reject_reason"] == "stale_evidence"
    stored = json.loads((tmp_path / "memory-e2e-demo-v1.json").read_text(encoding="utf-8"))
    assert stored["summary"] == artifact["summary"]


def test_live_memory_e2e_smoke_skips_without_explicit_environment(tmp_path, monkeypatch):
    """未显式授权时真实模型冒烟必须跳过。"""
    monkeypatch.delenv("PICO_LIVE_SMOKE", raising=False)

    artifact = run_live_memory_e2e_smoke(tmp_path / "live.json", "openai")

    assert artifact["status"] == "skipped"
