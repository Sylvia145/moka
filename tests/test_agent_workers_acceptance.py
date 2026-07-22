"""Pico 自动化测试模块。"""
import json
import subprocess
import threading
import time

from pico import Pico, SessionStore, WorkspaceContext
from pico.testing import ScriptedModelClient


def build_agent(tmp_path, outputs, **kwargs):
    """执行 `build_agent` 的内部逻辑。"""
    (tmp_path / "README.md").write_text("demo readme\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=ScriptedModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def read_jsonl(path):
    """执行 `read_jsonl` 的内部逻辑。"""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class BlockingModelClient:
    def __init__(self, outputs, started, release):
        """执行 `__init__` 的内部逻辑。"""
        self.outputs = list(outputs)
        self.started = started
        self.release = release
        self.prompts = []
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}
        self.abort_count = 0

    def complete(self, prompt, max_new_tokens, **kwargs):
        """执行 `complete` 的内部逻辑。"""
        self.prompts.append(prompt)
        self.started.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("blocking test client timed out")
        if not self.outputs:
            raise RuntimeError("scripted model ran out of outputs")
        return self.outputs.pop(0)

    def abort(self):
        """执行 `abort` 的内部逻辑。"""
        self.abort_count += 1
        self.release.set()


def test_delegate_is_removed_from_runtime_tool_surface(tmp_path):
    """执行 `test_delegate_is_removed_from_runtime_tool_surface` 的内部逻辑。"""
    agent = build_agent(tmp_path, [])

    assert "delegate" not in agent.tools
    assert "delegate" not in agent.available_tools()
    assert '"name":"delegate"' not in agent.prefix
    assert "- delegate(" not in agent.prefix
    assert not hasattr(agent, "tool_delegate")


def test_async_worker_notification_is_drained_by_coordinator_only(tmp_path):
    """执行 `test_async_worker_notification_is_drained_by_coordinator_only` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    child_client = BlockingModelClient(["<final>Child done.</final>"], started, release)
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: child_client,
    )

    before = time.monotonic()
    payload = json.loads(
        agent.run_tool(
            "agent",
            {
                "description": "Background read",
                "prompt": "Summarize README",
                "subagent_type": "Explore",
            },
        )
    )

    assert payload["status"] == "started"
    assert time.monotonic() - before < 1.0
    assert started.wait(timeout=1)
    assert not any(
        "<task-notification>" in item.get("content", "")
        for item in agent.session["history"]
    )

    release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if (
            agent.worker_manager.to_dict()["items"][0]["status"] == "completed"
            and not agent.worker_manager._notifications.empty()
        ):
            break
        time.sleep(0.01)

    drained = agent.engine.drain_worker_notifications()

    assert len(drained) == 1
    assert "<task-id>agent_1</task-id>" in drained[0]
    assert any(
        "<task-notification>" in item.get("content", "")
        for item in agent.session["history"]
    )
    assert agent.engine.drain_worker_notifications() == []
    assert agent.worker_manager.to_dict()["items"][0]["notification_drained"] is True


def test_background_workers_queue_at_configured_concurrency_limit(tmp_path):
    """执行 `test_background_workers_queue_at_configured_concurrency_limit` 的内部逻辑。"""
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    second_release = threading.Event()
    clients = iter(
        [
            BlockingModelClient(["<final>First done.</final>"], first_started, first_release),
            BlockingModelClient(["<final>Second done.</final>"], second_started, second_release),
        ]
    )
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: next(clients),
        max_concurrent_workers=1,
    )

    first = agent.worker_manager.spawn("First", "wait", subagent_type="Explore")
    assert first["status"] == "started"
    assert first_started.wait(timeout=1)

    second = agent.worker_manager.spawn("Second", "wait", subagent_type="Explore")
    assert second["status"] == "queued"
    assert not second_started.wait(timeout=0.1)

    first_release.set()
    assert second_started.wait(timeout=2)
    second_release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        statuses = [item["status"] for item in agent.worker_manager.to_dict()["items"]]
        if statuses == ["completed", "completed"]:
            break
        time.sleep(0.01)

    assert [item["status"] for item in agent.worker_manager.to_dict()["items"]] == [
        "completed",
        "completed",
    ]
    metrics = agent.worker_manager.to_dict()["metrics"]
    assert metrics["accepted"] == 2
    assert metrics["queued"] == 1
    assert metrics["completed"] == 2
    assert metrics["queue_wait_samples"] == 1
    assert metrics["queue_wait_ms_avg"] >= 0


def test_background_workers_reject_when_pending_queue_is_full(tmp_path):
    """执行 `test_background_workers_reject_when_pending_queue_is_full` 的内部逻辑。"""
    first_started = threading.Event()
    first_release = threading.Event()
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: BlockingModelClient(
            ["<final>First done.</final>"], first_started, first_release
        ),
        max_concurrent_workers=1,
        max_pending_workers=0,
    )

    first = agent.worker_manager.spawn("First", "wait", subagent_type="Explore")
    assert first["status"] == "started"
    assert first_started.wait(timeout=1)

    rejected = agent.worker_manager.spawn("Rejected", "wait", subagent_type="Explore")

    assert rejected["status"] == "rejected"
    assert rejected["error"] == {
        "code": "worker_queue_full",
        "retryable": True,
        "running": 1,
        "pending": 0,
        "max_workers": 1,
        "max_pending": 0,
    }
    assert agent.worker_manager.to_dict()["metrics"]["rejected"] == 1
    events = read_jsonl(agent.session_event_bus.path)
    assert any(
        event["event"] == "worker_rejected" and event["code"] == "worker_queue_full"
        for event in events
    )
    first_release.set()


def test_send_message_rejects_running_worker(tmp_path):
    """执行 `test_send_message_rejects_running_worker` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: BlockingModelClient(
            ["<final>Child done.</final>"], started, release
        ),
    )

    agent.run_tool(
        "agent",
        {
            "description": "Still running",
            "prompt": "Wait for release",
            "subagent_type": "Explore",
        },
    )
    assert started.wait(timeout=1)

    rejected = agent.run_tool(
        "send_message", {"to": "agent_1", "message": "Continue now"}
    )

    release.set()
    assert "worker is running" in rejected


def test_task_stop_requests_child_runtime_abort(tmp_path):
    """执行 `test_task_stop_requests_child_runtime_abort` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    child_client = BlockingModelClient(["<final>Child done.</final>"], started, release)
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: child_client,
    )

    agent.run_tool(
        "agent",
        {
            "description": "Abort me",
            "prompt": "Wait until stopped",
            "subagent_type": "Explore",
        },
    )
    assert started.wait(timeout=1)

    payload = json.loads(agent.run_tool("task_stop", {"task_id": "agent_1"}))

    assert payload["status"] == "canceled"
    assert child_client.abort_count == 1
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if agent.worker_manager.to_dict()["items"][0]["status"] == "canceled":
            break
        time.sleep(0.01)
    assert agent.worker_manager.to_dict()["items"][0]["status"] == "canceled"


def test_worker_timeout_requests_abort_and_keeps_timeout_terminal_state(tmp_path):
    """执行 `test_worker_timeout_requests_abort_and_keeps_timeout_terminal_state` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    child_client = BlockingModelClient(["<final>Late completion.</final>"], started, release)
    agent = build_agent(tmp_path, [], model_client_factory=lambda: child_client)

    payload = json.loads(
        agent.run_tool(
            "agent",
            {
                "description": "Timeout worker",
                "prompt": "Wait until timeout",
                "subagent_type": "Explore",
                "timeout_seconds": 1,
            },
        )
    )

    assert payload["status"] == "started"
    assert started.wait(timeout=1)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if agent.worker_manager.to_dict()["items"][0]["status"] == "timed_out":
            break
        time.sleep(0.01)

    assert child_client.abort_count == 1
    assert agent.worker_manager.to_dict()["items"][0]["status"] == "timed_out"


def test_terminal_race_commits_once_and_notification_is_idempotent(tmp_path):
    """执行 `test_terminal_race_commits_once_and_notification_is_idempotent` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    agent = build_agent(
        tmp_path, [],
        model_client_factory=lambda: BlockingModelClient(["<final>done</final>"], started, release),
    )
    agent.worker_manager.spawn("race", "wait", subagent_type="Explore")
    assert started.wait(timeout=1)
    outcomes = []

    def transition(status, actor):
        outcomes.append(agent.worker_manager.transition_worker_state(
            "agent_1", {"running"}, status, reason="race", actor=actor
        ))

    first = threading.Thread(target=transition, args=("timed_out", "watcher"))
    second = threading.Thread(target=transition, args=("canceled", "stop"))
    first.start(); second.start(); first.join(); second.join()
    item = agent.worker_manager.to_dict()["items"][0]
    assert item["status"] in {"timed_out", "canceled"}
    committed = next(value for value in outcomes if value is not None)
    assert agent.worker_manager.publish_terminal_notification(committed) is True
    assert agent.worker_manager.publish_terminal_notification(committed) is False
    assert agent.worker_manager.to_dict()["metrics"]["duplicate_terminal_transition"] == 1
    release.set()


def test_write_worker_uses_isolated_git_worktree(tmp_path):
    """执行 `test_write_worker_uses_isolated_git_worktree` 的内部逻辑。"""
    (tmp_path / "README.md").write_text("main workspace\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Moka Test", "-c", "user.email=moka@example.test", "commit", "-m", "fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="notes/worker.txt"><content>isolated\n</content></tool>',
            "<final>Worker wrote the isolated note.</final>",
        ],
    )

    payload = agent.worker_manager.spawn(
        "Write isolated note", "Create notes/worker.txt", write_scope=["notes"]
    )
    item = agent.worker_manager.to_dict()["items"][0]
    worktree = tmp_path / item["worktree_path"]

    assert payload["status"] == "completed"
    assert item["base_commit"]
    assert worktree.exists()
    assert (worktree / "notes" / "worker.txt").read_text(encoding="utf-8") == "isolated\n"
    assert not (tmp_path / "notes" / "worker.txt").exists()
    handoff = item["change_handoff"]
    assert handoff["status"] == "pending_review"
    assert handoff["review_required"] is True
    assert handoff["base_commit"] == item["base_commit"]
    assert handoff["diff_paths"] == ["notes/worker.txt"]
    assert handoff["untracked_paths"] == ["notes/worker.txt"]
    assert "notes/worker.txt" in handoff["diff_stat"]
    assert ".pico" not in handoff["diff_stat"]
    assert handoff["diff_check_exit_code"] == 0
    # handoff 使用稳定幂等键（worker + 执行轮次），跨重复通知/恢复可去重。
    assert handoff["idempotency_key"] == "agent_1:1:handoff"


def test_clear_session_stops_running_background_workers(tmp_path):
    """执行 `test_clear_session_stops_running_background_workers` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    child_client = BlockingModelClient(["<final>Child done.</final>"], started, release)
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: child_client,
    )

    agent.run_tool(
        "agent",
        {
            "description": "Clear me",
            "prompt": "Wait until clear",
            "subagent_type": "Explore",
        },
    )
    assert started.wait(timeout=1)
    old_id = agent.session["id"]

    new_id = agent.clear_session()

    assert new_id != old_id
    assert child_client.abort_count == 1
    assert agent.worker_manager.to_dict()["items"] == []
    assert agent.engine.drain_worker_notifications() == []


def test_watch_timeout_ignores_worker_cleared_by_session_reset(tmp_path):
    """执行 `test_watch_timeout_ignores_worker_cleared_by_session_reset` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    child_client = BlockingModelClient(["<final>Done.</final>"], started, release)
    agent = build_agent(tmp_path, [], model_client_factory=lambda: child_client)

    agent.run_tool(
        "agent",
        {
            "description": "Cleared watcher",
            "prompt": "Wait until cleared",
            "subagent_type": "Explore",
            "timeout_seconds": 1,
        },
    )
    assert started.wait(timeout=1)

    old_id = agent.session["id"]
    new_id = agent.clear_session()
    assert new_id != old_id
    assert agent.worker_manager.to_dict()["items"] == []

    # 旧会话的 timeout watcher 线程仍在 ~1s 后触发；它必须静默退出（条目已被
    # clear_session 丢弃），而不是对新会话抛 `ValueError: unknown worker`。
    time.sleep(1.5)


def test_resume_requeues_pending_worker_and_marks_orphaned_running_worker_failed(tmp_path):
    """执行 `test_resume_requeues_pending_worker_and_marks_orphaned_running_worker_failed` 的内部逻辑。"""
    first_started = threading.Event()
    first_release = threading.Event()
    first = build_agent(
        tmp_path, [],
        model_client_factory=lambda: BlockingModelClient(["<final>blocked</final>"], first_started, first_release),
        max_concurrent_workers=1,
    )
    first.worker_manager.spawn("running", "wait", subagent_type="Explore")
    assert first_started.wait(timeout=1)
    first.worker_manager.spawn("queued", "finish", subagent_type="Explore")
    session_id = first.session["id"]

    resumed = build_agent(
        tmp_path, [],
        model_client_factory=lambda: ScriptedModelClient(["<final>resumed</final>"]),
        max_concurrent_workers=1,
    )
    resumed.resume_session(session_id)

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        statuses = [item["status"] for item in resumed.worker_manager.to_dict()["items"]]
        if statuses == ["failed", "completed"]:
            break
        time.sleep(0.01)
    assert [item["status"] for item in resumed.worker_manager.to_dict()["items"]] == ["failed", "completed"]


def test_explore_agent_runs_real_readonly_child_session_and_records_notification(
    tmp_path,
):
    """执行 `test_explore_agent_runs_real_readonly_child_session_and_records_notification` 的内部逻辑。"""
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"agent","args":{"description":"Inspect readme","prompt":"Read README.md and summarize it","subagent_type":"Explore"}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            "<final>README says demo readme.</final>",
            "<final>Exploration complete.</final>",
        ],
        max_steps=4,
    )

    assert agent.ask("inspect with a subagent") == "Exploration complete."

    notifications = [
        item
        for item in agent.session["history"]
        if item["role"] == "user" and "<task-notification>" in item["content"]
    ]
    assert len(notifications) == 1
    assert "<task-id>agent_1</task-id>" in notifications[0]["content"]
    assert "<status>completed</status>" in notifications[0]["content"]
    assert "README says demo readme." in notifications[0]["content"]

    events = read_jsonl(agent.session_event_bus.path)
    assert any(
        event["event"] == "worker_started" and event["worker_id"] == "agent_1"
        for event in events
    )
    assert any(
        event["event"] == "worker_finished" and event["worker_id"] == "agent_1"
        for event in events
    )
    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report["workers"]["items"][0]["id"] == "agent_1"
    assert report["workers"]["items"][0]["subagent_type"] == "Explore"
    assert report["workers"]["items"][0]["result_contract"]["run_id"]


def test_worker_agent_can_be_continued_with_same_child_context_and_write_scope(
    tmp_path,
):
    """执行 `test_worker_agent_can_be_continued_with_same_child_context_and_write_scope` 的内部逻辑。"""
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"agent","args":{"description":"Write notes","prompt":"Create the first note","subagent_type":"worker","write_scope":["notes"]}}</tool>',
            '<tool name="write_file" path="notes/first.txt"><content>first\n</content></tool>',
            "<final>First note written.</final>",
            '<tool>{"name":"send_message","args":{"to":"agent_1","message":"Create the second note"}}</tool>',
            '<tool name="write_file" path="notes/second.txt"><content>second\n</content></tool>',
            "<final>Second note written.</final>",
            "<final>Both worker steps are done.</final>",
        ],
        max_steps=5,
    )

    assert agent.ask("use a worker twice") == "Both worker steps are done."

    assert (tmp_path / "notes" / "first.txt").read_text(encoding="utf-8") == "first\n"
    assert (tmp_path / "notes" / "second.txt").read_text(encoding="utf-8") == "second\n"
    assert agent.model_client.prompts[4].count("First note written.") >= 1

    notifications = [
        item
        for item in agent.session["history"]
        if item["role"] == "user" and "<task-notification>" in item["content"]
    ]
    assert len(notifications) == 2
    assert all(
        "<task-id>agent_1</task-id>" in item["content"] for item in notifications
    )
    events = read_jsonl(agent.session_event_bus.path)
    assert (
        sum(
            1
            for event in events
            if event["event"] == "worker_started" and event["worker_id"] == "agent_1"
        )
        == 2
    )


def test_worker_write_scope_blocks_child_file_modification_outside_scope(tmp_path):
    """执行 `test_worker_write_scope_blocks_child_file_modification_outside_scope` 的内部逻辑。"""
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"agent","args":{"description":"Bad write","prompt":"Write outside scope","subagent_type":"worker","write_scope":["allowed"]}}</tool>',
            '<tool name="write_file" path="forbidden/out.txt"><content>no\n</content></tool>',
            "<final>Write was blocked.</final>",
            "<final>Worker reported the blocked write.</final>",
        ],
        max_steps=4,
    )

    assert agent.ask("try a scoped worker") == "Worker reported the blocked write."

    assert not (tmp_path / "forbidden" / "out.txt").exists()
    notification = next(
        item
        for item in agent.session["history"]
        if item["role"] == "user" and "<task-notification>" in item["content"]
    )
    assert "Write was blocked." in notification["content"]


def test_worker_without_write_scope_cannot_modify_workspace(tmp_path):
    """执行 `test_worker_without_write_scope_cannot_modify_workspace` 的内部逻辑。"""
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"agent","args":{"description":"No scope","prompt":"Write without scope","subagent_type":"worker"}}</tool>',
            '<tool name="write_file" path="notes/out.txt"><content>no\n</content></tool>',
            "<final>Write was blocked.</final>",
            "<final>Worker respected missing scope.</final>",
        ],
        max_steps=4,
    )

    assert agent.ask("try an unscoped worker") == "Worker respected missing scope."

    assert not (tmp_path / "notes" / "out.txt").exists()


def test_plan_mode_cannot_continue_write_capable_worker(tmp_path):
    """执行 `test_plan_mode_cannot_continue_write_capable_worker` 的内部逻辑。"""
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"agent","args":{"description":"Worker","prompt":"Read only first","subagent_type":"worker","write_scope":["notes"]}}</tool>',
            "<final>Worker ready.</final>",
            "<final>Coordinator done.</final>",
        ],
        max_steps=3,
    )

    assert agent.ask("create a worker") == "Coordinator done."
    agent.enter_plan_mode("gate7")

    rejected = agent.run_tool(
        "send_message", {"to": "agent_1", "message": "Write notes/out.txt"}
    )

    assert "plan mode only allows Explore agents" in rejected
    assert not (tmp_path / "notes" / "out.txt").exists()


def test_plan_mode_allows_only_explore_agents(tmp_path):
    """执行 `test_plan_mode_allows_only_explore_agents` 的内部逻辑。"""
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"agent","args":{"description":"Explore plan","prompt":"Read README","subagent_type":"Explore"}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            "<final>Explored.</final>",
            '<tool name="write_file" path=".pico/plans/gate7-plan.md"><content># Gate7\n</content></tool>',
            "<final>Plan ready.</final>",
        ],
        max_steps=5,
    )

    agent.enter_plan_mode("gate7")
    rejected = agent.run_tool(
        "agent",
        {
            "description": "Write from plan",
            "prompt": "change files",
            "subagent_type": "worker",
            "write_scope": ["pico"],
        },
    )

    assert "plan mode only allows Explore agents" in rejected
    assert agent.ask("plan with explore") == "Plan ready."
    assert agent.active_tool_profile.name == "default"


def test_cancel_queued_worker_frees_slot_and_never_starts(tmp_path):
    """执行 `test_cancel_queued_worker_frees_slot_and_never_starts` 的内部逻辑。"""
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    second_release = threading.Event()
    second_client = BlockingModelClient(["<final>Second done.</final>"], second_started, second_release)
    clients = iter(
        [
            BlockingModelClient(["<final>First done.</final>"], first_started, first_release),
            second_client,
        ]
    )
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: next(clients),
        max_concurrent_workers=1,
    )

    first = agent.worker_manager.spawn("First", "wait", subagent_type="Explore")
    assert first["status"] == "started"
    assert first_started.wait(timeout=1)

    second = agent.worker_manager.spawn("Second", "wait", subagent_type="Explore")
    assert second["status"] == "queued"
    assert agent.worker_manager.to_dict()["metrics"]["pending"] == 1

    canceled = agent.worker_manager.stop_task("agent_2")

    assert canceled["status"] == "canceled"
    assert not second_started.wait(timeout=0.1)
    assert second_client.prompts == []
    assert agent.worker_manager.to_dict()["metrics"]["pending"] == 0

    # 释放 First 后没有可启动的 queued 任务；Second 保持 canceled，不被重启。
    first_release.set()
    time.sleep(0.3)
    items = agent.worker_manager.to_dict()["items"]
    assert items[0]["status"] == "completed"
    assert items[1]["status"] == "canceled"
    assert not second_started.is_set()


def test_timeout_releases_capacity_and_starts_next_queued(tmp_path):
    """执行 `test_timeout_releases_capacity_and_starts_next_queued` 的内部逻辑。"""
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    second_release = threading.Event()
    clients = iter(
        [
            BlockingModelClient(["<final>First done.</final>"], first_started, first_release),
            BlockingModelClient(["<final>Second done.</final>"], second_started, second_release),
        ]
    )
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: next(clients),
        max_concurrent_workers=1,
    )

    first = agent.worker_manager.spawn(
        "First", "wait", subagent_type="Explore", timeout_seconds=1
    )
    assert first["status"] == "started"
    assert first_started.wait(timeout=1)

    second = agent.worker_manager.spawn("Second", "wait", subagent_type="Explore")
    assert second["status"] == "queued"

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        statuses = [item["status"] for item in agent.worker_manager.to_dict()["items"]]
        if statuses[0] == "timed_out" and statuses[1] == "running":
            break
        time.sleep(0.01)

    assert agent.worker_manager.to_dict()["items"][0]["status"] == "timed_out"
    assert agent.worker_manager.to_dict()["items"][1]["status"] in {"starting", "running"}
    assert second_started.wait(timeout=1)
    assert agent.worker_manager.to_dict()["metrics"]["queue_wait_samples"] == 1
    second_release.set()


def test_cancel_keeps_canceled_terminal_after_late_worker_return(tmp_path):
    """执行 `test_cancel_keeps_canceled_terminal_after_late_worker_return` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    child_client = BlockingModelClient(["<final>Late done.</final>"], started, release)
    agent = build_agent(tmp_path, [], model_client_factory=lambda: child_client)

    agent.run_tool(
        "agent",
        {
            "description": "Cancel me",
            "prompt": "Wait until stopped",
            "subagent_type": "Explore",
        },
    )
    assert started.wait(timeout=1)

    payload = json.loads(agent.run_tool("task_stop", {"task_id": "agent_1"}))
    assert payload["status"] == "canceled"

    # worker 线程随后返回（abort 释放了 release），不得把 canceled 终态覆盖成
    # completed/stopped，也不得回写 result。
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not agent.worker_manager._tasks["agent_1"].thread.is_alive():
            break
        time.sleep(0.01)

    item = agent.worker_manager.to_dict()["items"][0]
    assert item["status"] == "canceled"
    assert item["result"] == ""
    metrics = agent.worker_manager.to_dict()["metrics"]
    assert metrics["canceled"] == 1
    assert metrics["completed"] == 0


def test_rejected_write_worker_does_not_activate_delegated_review(tmp_path):
    """执行 `test_rejected_write_worker_does_not_activate_delegated_review` 的内部逻辑。"""
    started = threading.Event()
    release = threading.Event()
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: BlockingModelClient(
            ["<final>Blocked.</final>"], started, release
        ),
        max_concurrent_workers=1,
        max_pending_workers=0,
    )

    first = agent.worker_manager.spawn("Occupier", "wait", subagent_type="Explore")
    assert first["status"] == "started"
    assert started.wait(timeout=1)
    assert agent.delegation_guard_active is False

    rejected = agent.worker_manager.spawn(
        "Rejected write",
        "write something",
        subagent_type="worker",
        write_scope=["notes"],
    )

    assert rejected["status"] == "rejected"
    assert rejected["error"]["code"] == "worker_queue_full"
    # 委派从未被接受，父 Agent 不得进入 delegated_review。
    assert agent.delegation_guard_active is False
    assert agent.active_tool_profile.name == "default"
    release.set()


def test_rejected_write_worker_cleans_up_its_worktree(tmp_path):
    """执行 `test_rejected_write_worker_cleans_up_its_worktree` 的内部逻辑。"""
    (tmp_path / "README.md").write_text("main workspace\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Moka Test", "-c", "user.email=moka@example.test", "commit", "-m", "fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    started = threading.Event()
    release = threading.Event()
    agent = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: BlockingModelClient(
            ["<final>Blocked.</final>"], started, release
        ),
        max_concurrent_workers=1,
        max_pending_workers=0,
    )

    first = agent.worker_manager.spawn("Occupier", "wait", subagent_type="Explore")
    assert first["status"] == "started"
    assert started.wait(timeout=1)

    rejected = agent.worker_manager.spawn(
        "Rejected write",
        "write something",
        subagent_type="worker",
        write_scope=["notes"],
    )

    assert rejected["status"] == "rejected"
    assert not (tmp_path / ".worktrees" / "agent_2").exists()
    events = read_jsonl(agent.session_event_bus.path)
    assert any(
        event["event"] == "worker_worktree_removed" and event["worker_id"] == "agent_2"
        for event in events
    )
    release.set()


def test_resume_does_not_restart_terminal_workers(tmp_path):
    """执行 `test_resume_does_not_restart_terminal_workers` 的内部逻辑。"""
    first = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: ScriptedModelClient(["<final>First done.</final>"]),
    )
    payload = first.worker_manager.spawn("First", "finish", subagent_type="Explore")
    assert payload["status"] == "started"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if first.worker_manager.to_dict()["items"][0]["status"] == "completed":
            break
        time.sleep(0.01)
    assert first.worker_manager.to_dict()["items"][0]["status"] == "completed"
    session_id = first.session["id"]
    events_before = read_jsonl(first.session_event_bus.path)

    resumed = build_agent(
        tmp_path,
        [],
        model_client_factory=lambda: ScriptedModelClient(["<final>Resumed.</final>"]),
    )
    resumed.resume_session(session_id)

    item = resumed.worker_manager.to_dict()["items"][0]
    assert item["status"] == "completed"
    assert item["execution_sequence"] == 1
    assert resumed.worker_manager.to_dict()["metrics"]["completed"] == 1
    # 终态 Worker 不重建执行实体，resume 不向同一事件文件追加任何内容。
    assert resumed.worker_manager._tasks == {}
    assert read_jsonl(resumed.session_event_bus.path) == events_before


def test_unhandled_worker_thread_exception_is_recorded(tmp_path):
    """执行 `test_unhandled_worker_thread_exception_is_recorded` 的内部逻辑。"""
    agent = build_agent(tmp_path, [])
    # 让钩子能按属主匹配到当前 manager（多 manager 进程里 fallback 不可靠）。
    agent.worker_manager._tasks["agent_9"] = None

    def boom():
        raise RuntimeError("boom")

    thread = threading.Thread(target=boom, name="pico-worker-agent_9", daemon=True)
    thread.start()
    thread.join()

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if agent.worker_manager.to_dict()["metrics"]["unhandled_thread_exception"] == 1:
            break
        time.sleep(0.01)
    assert agent.worker_manager.to_dict()["metrics"]["unhandled_thread_exception"] == 1
    events = read_jsonl(agent.session_event_bus.path)
    assert any(
        event["event"] == "worker_thread_exception" and event["worker_id"] == "agent_9"
        for event in events
    )
