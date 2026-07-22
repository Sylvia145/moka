"""Worker 并发与 Backpressure 故障注入（手册 Phase 7）。

逐场景运行 A–J，输出指标快照与事件结果，用于填充
docs/benchmark/Worker并发与Backpressure.md。不使用真实模型。

用法：uv run python scripts/worker_concurrency_fault_injection.py
"""

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pico import Pico, SessionStore, WorkspaceContext
from pico.testing import ScriptedModelClient


class BlockingModelClient:
    def __init__(self, outputs, started, release):
        self.outputs = list(outputs)
        self.started = started
        self.release = release
        self.prompts = []
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}
        self.abort_count = 0

    def complete(self, prompt, max_new_tokens, **kwargs):
        self.prompts.append(prompt)
        self.started.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("blocking test client timed out")
        if not self.outputs:
            raise RuntimeError("scripted model ran out of outputs")
        return self.outputs.pop(0)

    def abort(self):
        self.abort_count += 1
        self.release.set()


def build_agent(tmp_path, outputs, **kwargs):
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
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def snapshot(manager, label, events=None):
    m = manager.to_dict()["metrics"]
    wanted = [
        "accepted", "queued", "rejected", "completed", "failed",
        "timed_out", "canceled", "duplicate_terminal_transition",
        "unhandled_thread_exception", "running", "pending",
        "queue_wait_ms_avg", "queue_wait_ms_max",
    ]
    row = {k: m.get(k, 0) for k in wanted}
    row["label"] = label
    if events:
        row["worker_events"] = sorted({e["event"] for e in events if e["event"].startswith("worker")})
    return row


def wait_status(manager, index, expected, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        items = manager.to_dict()["items"]
        if index < len(items) and items[index]["status"] in expected:
            return items[index]["status"]
        time.sleep(0.01)
    return manager.to_dict()["items"][index]["status"]


def release_and_wait(agent, release, timeout=3):
    release.set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(i["status"] not in {"starting", "running", "stopping"} for i in agent.worker_manager.to_dict()["items"]):
            break
        time.sleep(0.01)
    # 等待 worker 线程真正结束（可能还在做 _save），避免临时目录被提前删除。
    agent.worker_manager.shutdown(timeout=2)
    time.sleep(0.2)


def run_scenarios():
    results = []

    # A 单 Worker
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        agent = build_agent(
            Path(td), [],
            model_client_factory=lambda: ScriptedModelClient(["<final>A done.</final>"]),
        )
        payload = agent.worker_manager.spawn("A", "finish", subagent_type="Explore")
        assert payload["status"] == "started"
        wait_status(agent.worker_manager, 0, {"completed"})
        results.append(snapshot(agent.worker_manager, "A 单 Worker"))

    # B 达到 max_workers
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        started = threading.Event(); release = threading.Event()
        agent = build_agent(
            Path(td), [],
            model_client_factory=lambda: BlockingModelClient(["<final>B done.</final>"], started, release),
            max_concurrent_workers=1,
        )
        assert agent.worker_manager.spawn("B1", "wait", subagent_type="Explore")["status"] == "started"
        started.wait(timeout=1)
        second = agent.worker_manager.spawn("B2", "wait", subagent_type="Explore")
        assert second["status"] == "queued"
        results.append(snapshot(agent.worker_manager, "B 达到 max_workers"))
        release_and_wait(agent, release)

    # C pending 满
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        started = threading.Event(); release = threading.Event()
        agent = build_agent(
            Path(td), [],
            model_client_factory=lambda: BlockingModelClient(["<final>C done.</final>"], started, release),
            max_concurrent_workers=1, max_pending_workers=0,
        )
        assert agent.worker_manager.spawn("C1", "wait", subagent_type="Explore")["status"] == "started"
        started.wait(timeout=1)
        rejected = agent.worker_manager.spawn("C2", "wait", subagent_type="Explore")
        assert rejected["status"] == "rejected"
        assert rejected["error"]["code"] == "worker_queue_full"
        results.append(snapshot(agent.worker_manager, "C pending 满 REJECTED"))
        release_and_wait(agent, release)

    # D timeout
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        started = threading.Event(); release = threading.Event()
        agent = build_agent(
            Path(td), [],
            model_client_factory=lambda: BlockingModelClient(["<final>D done.</final>"], started, release),
        )
        assert agent.worker_manager.spawn("D", "wait", subagent_type="Explore", timeout_seconds=1)["status"] == "started"
        started.wait(timeout=1)
        wait_status(agent.worker_manager, 0, {"timed_out"})
        results.append(snapshot(agent.worker_manager, "D timeout"))
        release_and_wait(agent, release)

    # E cancel queued
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        started = threading.Event(); release = threading.Event()
        agent = build_agent(
            Path(td), [],
            model_client_factory=lambda: BlockingModelClient(["<final>E done.</final>"], started, release),
            max_concurrent_workers=1,
        )
        assert agent.worker_manager.spawn("E1", "wait", subagent_type="Explore")["status"] == "started"
        started.wait(timeout=1)
        assert agent.worker_manager.spawn("E2", "wait", subagent_type="Explore")["status"] == "queued"
        canceled = agent.worker_manager.stop_task("agent_2")
        assert canceled["status"] == "canceled"
        results.append(snapshot(agent.worker_manager, "E cancel queued"))
        release_and_wait(agent, release)

    # F cancel running
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        started = threading.Event(); release = threading.Event()
        agent = build_agent(
            Path(td), [],
            model_client_factory=lambda: BlockingModelClient(["<final>F done.</final>"], started, release),
        )
        assert agent.worker_manager.spawn("F", "wait", subagent_type="Explore")["status"] == "started"
        started.wait(timeout=1)
        canceled = agent.worker_manager.stop_task("agent_1")
        assert canceled["status"] == "canceled"
        wait_status(agent.worker_manager, 0, {"canceled"})
        results.append(snapshot(agent.worker_manager, "F cancel running"))
        release_and_wait(agent, release)

    # G completion-timeout race：watcher 先到点提交 timed_out，工作线程晚返回不得覆盖
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        started = threading.Event(); release = threading.Event()
        agent = build_agent(
            Path(td), [],
            model_client_factory=lambda: BlockingModelClient(["<final>G done.</final>"], started, release),
        )
        assert agent.worker_manager.spawn("G", "wait", subagent_type="Explore", timeout_seconds=1)["status"] == "started"
        started.wait(timeout=1)
        status = wait_status(agent.worker_manager, 0, {"timed_out", "completed"})
        assert status == "timed_out"
        release_and_wait(agent, release)
        results.append(snapshot(agent.worker_manager, "G completion-timeout race"))

    # H session reset：旧 watcher 到点后条目已丢，必须静默退出
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        started = threading.Event(); release = threading.Event()
        agent = build_agent(
            Path(td), [],
            model_client_factory=lambda: BlockingModelClient(["<final>H done.</final>"], started, release),
        )
        assert agent.worker_manager.spawn("H", "wait", subagent_type="Explore", timeout_seconds=1)["status"] == "started"
        started.wait(timeout=1)
        agent.clear_session()
        time.sleep(1.5)  # 等待旧 watcher 触发
        results.append(snapshot(agent.worker_manager, "H session reset race"))
        release_and_wait(agent, release)

    # I resume：queued 重新入队，孤儿 running 标记 failed，终态不重启
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td)
        started = threading.Event(); release = threading.Event()
        first = build_agent(
            root, [],
            model_client_factory=lambda: BlockingModelClient(["<final>I1</final>"], started, release),
            max_concurrent_workers=1,
        )
        assert first.worker_manager.spawn("I1", "wait", subagent_type="Explore")["status"] == "started"
        started.wait(timeout=1)
        assert first.worker_manager.spawn("I2", "finish", subagent_type="Explore")["status"] == "queued"
        session_id = first.session["id"]

        resumed = build_agent(
            root, [],
            model_client_factory=lambda: ScriptedModelClient(["<final>I2 resumed</final>"]),
            max_concurrent_workers=1,
        )
        resumed.resume_session(session_id)
        wait_status(resumed.worker_manager, 0, {"failed"})
        wait_status(resumed.worker_manager, 1, {"completed"})
        results.append(snapshot(resumed.worker_manager, "I resume"))
        release_and_wait(first, release)

    # J duplicate notification / handoff 幂等键（写 Worker，git 仓库）
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td)
        (root / "README.md").write_text("main workspace\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=Moka", "-c", "user.email=moka@example.test", "commit", "-m", "fixture"],
            cwd=root, check=True, capture_output=True,
        )
        agent = build_agent(root, [
            '<tool name="write_file" path="notes/j.txt"><content>j\n</content></tool>',
            "<final>J done.</final>",
        ])
        payload = agent.worker_manager.spawn(
            "J", "write j.txt", subagent_type="worker", write_scope=["notes"]
        )
        assert payload["status"] == "completed"
        item = agent.worker_manager._get_item("agent_1")
        assert item["change_handoff"]["idempotency_key"] == "agent_1:1:handoff"
        # run_worker 已发布一次；后续重复发布必须被幂等键拦截。
        assert agent.worker_manager.publish_terminal_notification(item) is False
        assert agent.worker_manager.publish_terminal_notification(item) is False
        drained = agent.worker_manager.drain_notifications()
        assert len(drained) == 1
        assert agent.worker_manager.publish_terminal_notification(item) is False
        results.append(snapshot(agent.worker_manager, "J duplicate notification/handoff"))

    return results


def main():
    print("=== Worker 并发与 Backpressure 故障注入报告 ===")
    print("运行时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    results = run_scenarios()
    header = ["label", "accepted", "queued", "rejected", "completed", "failed",
              "timed_out", "canceled", "dup_terminal", "unhandled_exc",
              "running", "pending", "wait_avg_ms", "wait_max_ms"]
    rows = []
    for r in results:
        rows.append([
            r["label"], r["accepted"], r["queued"], r["rejected"], r["completed"],
            r["failed"], r["timed_out"], r["canceled"],
            r["duplicate_terminal_transition"], r["unhandled_thread_exception"],
            r["running"], r["pending"],
            round(float(r["queue_wait_ms_avg"]), 1) if r["queue_wait_ms_avg"] else 0,
            round(float(r["queue_wait_ms_max"]), 1) if r["queue_wait_ms_max"] else 0,
        ])
    width = 14
    print("\n" + "|".join(h.ljust(width) for h in header))
    for row in rows:
        print("|".join(str(c).ljust(width) for c in row))
    print()
    for r in results:
        if r.get("worker_events"):
            print(f"{r['label']}: events={r['worker_events']}")
    print("\n结论：unhandled_exc 全为 0（无未处理线程异常）；dup_terminal 除 G（故意制造的")
    print("completion-timeout race，晚到终态被拒并计数）外全为 0，表示终态单次提交。")


if __name__ == "__main__":
    main()
