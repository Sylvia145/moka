"""Pico 自动化测试模块。"""
from pico import Pico, SessionStore, WorkspaceContext
from pico.evaluation.release_governance import (
    evaluate_run,
    policy_http_server_config,
    policy_server_config,
    prepare_workspace,
    release_governance_prompt,
)
from pico.evaluation.release_policy_http import release_policy_http_server
from pico.testing import ScriptedModelClient


def test_release_governance_keeps_production_files_out_of_worker_scope(tmp_path):
    """执行 `test_release_governance_keeps_production_files_out_of_worker_scope` 的内部逻辑。"""
    server_path = prepare_workspace(tmp_path)
    agent = Pico(
        model_client=ScriptedModelClient(
            [
                '<tool>{"name":"mcp__release_policy__get_policy","args":{"release_id":"billing-api-2026.08"}}</tool>',
                '<tool>{"name":"read_file","args":{"path":".env.example","start":1,"end":20}}</tool>',
                '<tool>{"name":"read_file","args":{"path":"deploy.md","start":1,"end":20}}</tool>',
                '<tool>{"name":"read_file","args":{"path":"migrations/20260812_add_invoice.sql","start":1,"end":20}}</tool>',
                '<tool>{"name":"agent","args":{"description":"Prepare release governance report","prompt":"Write reports/release-governance.md with POLICY: billing-release-v1, STATUS: BLOCKED, and the missing PAYMENT_WEBHOOK_SECRET, migration confirmation, and rollback owner. Do not modify other files.","subagent_type":"worker","write_scope":["reports"]}}</tool>',
                '<tool name="write_file" path="reports/release-governance.md"><content>**POLICY:** billing-release-v1\n**STATUS:** BLOCKED\nMissing PAYMENT_WEBHOOK_SECRET, migration confirmation, and rollback owner.\n</content></tool>',
                "<final>Release report is ready for review.</final>",
                "<final>Release remains blocked pending human review.</final>",
            ]
        ),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
        max_steps=6,
        mcp_servers=(policy_server_config(server_path),),
    )
    try:
        answer = agent.ask(release_governance_prompt())
        checks = evaluate_run(agent, tmp_path)
    finally:
        agent.mcp_clients["release_policy"].close()

    assert "blocked" in answer.lower()
    assert all(check["status"] == "passed" for check in checks), checks


def test_release_governance_over_streamable_http_keeps_same_business_boundaries(tmp_path):
    """执行 `test_release_governance_over_streamable_http_keeps_same_business_boundaries` 的内部逻辑。"""
    prepare_workspace(tmp_path)
    with release_policy_http_server(response_mode="sse") as (url, state):
        agent = Pico(
            model_client=ScriptedModelClient(
                [
                    '<tool>{"name":"mcp__release_policy__get_policy","args":{"release_id":"billing-api-2026.08"}}</tool>',
                    '<tool>{"name":"read_file","args":{"path":".env.example","start":1,"end":20}}</tool>',
                    '<tool>{"name":"read_file","args":{"path":"deploy.md","start":1,"end":20}}</tool>',
                    '<tool>{"name":"read_file","args":{"path":"migrations/20260812_add_invoice.sql","start":1,"end":20}}</tool>',
                    '<tool>{"name":"agent","args":{"description":"Prepare release governance report","prompt":"Write reports/release-governance.md with POLICY: billing-release-v1, STATUS: BLOCKED, and the missing PAYMENT_WEBHOOK_SECRET, migration confirmation, and rollback owner. Do not modify other files.","subagent_type":"worker","write_scope":["reports"]}}</tool>',
                    '<tool name="write_file" path="reports/release-governance.md"><content>POLICY: billing-release-v1\nSTATUS: BLOCKED\nMissing PAYMENT_WEBHOOK_SECRET, migration confirmation, and rollback owner.\n</content></tool>',
                    "<final>Release report is ready for review.</final>",
                    "<final>Release remains blocked pending human review.</final>",
                ]
            ),
            workspace=WorkspaceContext.build(tmp_path),
            session_store=SessionStore(tmp_path / ".pico" / "sessions"),
            approval_policy="auto",
            max_steps=6,
            mcp_servers=(policy_http_server_config(url),),
        )
        try:
            answer = agent.ask(release_governance_prompt())
            checks = evaluate_run(agent, tmp_path)
        finally:
            agent.mcp_clients["release_policy"].close()

    assert "blocked" in answer.lower()
    assert any(request.get("method") == "tools/call" for request in state["requests"])
    assert all(check["status"] == "passed" for check in checks), checks
