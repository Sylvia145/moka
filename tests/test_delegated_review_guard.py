import json

from pico import Pico, SessionStore, WorkspaceContext
from pico.evaluation.release_governance import (
    policy_server_config,
    prepare_workspace,
)
from pico.testing import ScriptedModelClient


def test_scoped_worker_activates_parent_review_guard_and_blocks_main_writes(tmp_path):
    server_path = prepare_workspace(tmp_path)
    agent = Pico(
        model_client=ScriptedModelClient(
            [
                '<tool name="write_file" path="reports/release-governance.md"><content>draft</content></tool>',
                "<final>Worker report is ready.</final>",
            ]
        ),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
        mcp_servers=(policy_server_config(server_path),),
    )
    try:
        payload = json.loads(
            agent.run_tool(
                "agent",
                {
                    "description": "Prepare release report",
                    "prompt": "Write reports/release-governance.md only.",
                    "subagent_type": "worker",
                    "write_scope": ["reports"],
                },
            )
        )

        assert payload["status"] == "completed"
        assert agent.active_tool_profile.name == "delegated_review"
        assert agent.delegation_guard_active is True
        assert (tmp_path / ".worktrees" / "agent_1" / "reports" / "release-governance.md").is_file()

        blocked = agent.run_tool(
            "write_file", {"path": "reports/parent-overwrite.md", "content": "must not write"}
        )
        assert "delegated review mode blocks write_file" in blocked
        assert not (tmp_path / "reports" / "parent-overwrite.md").exists()
        assert agent._last_tool_result_metadata["tool_error_code"] == "delegated_write_guard"

        policy = agent.run_tool(
            "mcp__release_policy__get_policy", {"release_id": "billing-api-2026.08"}
        )
        assert "billing-release-v1" in policy
    finally:
        agent.mcp_clients["release_policy"].close()


def test_delegated_review_guard_is_restored_with_session(tmp_path):
    server_path = prepare_workspace(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    agent = Pico(
        model_client=ScriptedModelClient(["<final>done</final>"]),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=store,
        approval_policy="auto",
        mcp_servers=(policy_server_config(server_path),),
    )
    try:
        agent.activate_delegated_review_mode("agent_7")
        restored = Pico.from_session(
            model_client=ScriptedModelClient(["<final>done</final>"]),
            workspace=WorkspaceContext.build(tmp_path),
            session_store=store,
            session_id=agent.session["id"],
            approval_policy="auto",
            mcp_servers=(policy_server_config(server_path),),
        )
        try:
            assert restored.delegation_guard_active is True
            assert restored.active_tool_profile.name == "delegated_review"
            assert "delegated review mode blocks patch_file" in restored.run_tool(
                "patch_file", {"path": "README.md", "old_text": "Billing", "new_text": "Changed"}
            )
        finally:
            restored.mcp_clients["release_policy"].close()
    finally:
        agent.mcp_clients["release_policy"].close()
