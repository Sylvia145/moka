"""Worker 状态机和调度指标的单一入口。"""

import time

from .workspace import now

ACTIVE_STATUSES = {"starting", "running", "stopping"}
TERMINAL_STATUSES = {"completed", "failed", "timed_out", "stopped", "canceled", "rejected"}
METRIC_KEYS = (
    "accepted", "queued", "rejected", "completed", "failed", "timed_out", "canceled",
    "duplicate_terminal_transition", "unhandled_thread_exception", "queue_wait_samples",
    "queue_wait_ms_total", "queue_wait_ms_max",
)


def ensure_metrics(state):
    """为旧会话补齐可向后兼容的指标形状。"""
    metrics = state.setdefault("metrics", {})
    for key in METRIC_KEYS:
        metrics.setdefault(key, 0)


def metrics_snapshot(manager):
    """返回累计指标与当前容量快照。"""
    metrics = dict(manager.state["metrics"])
    samples = int(metrics.get("queue_wait_samples", 0))
    total_wait = int(metrics.get("queue_wait_ms_total", 0))
    metrics["queue_wait_ms_avg"] = total_wait / samples if samples else 0.0
    metrics["running"] = sum(
        1 for item in manager.state.get("items", []) if item.get("status") in ACTIVE_STATUSES
    )
    metrics["pending"] = sum(
        1 for item in manager.state.get("items", []) if item.get("status") == "queued"
    )
    metrics["max_workers"] = manager.max_concurrent_workers
    metrics["max_pending"] = manager.max_pending_workers
    return metrics


def record_metric(manager, name, amount=1):
    with manager._lock:
        metrics = manager.state["metrics"]
        metrics[name] = int(metrics.get(name, 0)) + int(amount)


def record_queue_wait(manager, queued_at):
    if not queued_at:
        return 0
    waited_ms = max(0, int((time.monotonic() - float(queued_at)) * 1000))
    with manager._lock:
        metrics = manager.state["metrics"]
        metrics["queue_wait_samples"] = int(metrics.get("queue_wait_samples", 0)) + 1
        metrics["queue_wait_ms_total"] = int(metrics.get("queue_wait_ms_total", 0)) + waited_ms
        metrics["queue_wait_ms_max"] = max(int(metrics.get("queue_wait_ms_max", 0)), waited_ms)
    return waited_ms


def transition_worker_state(manager, worker_id, expected_states, new_state, *, reason, actor):
    """用 compare-and-set 风格提交状态；终态仅允许一次。"""
    expected = set(expected_states or ())
    with manager._lock:
        item = manager._get_item(worker_id)
        previous = str(item.get("status", ""))
        if previous in TERMINAL_STATUSES:
            if new_state in TERMINAL_STATUSES:
                record_metric(manager, "duplicate_terminal_transition")
                return None
            # 显式 continue 是新的执行轮次；resume 不会调用这一入口重启终态任务。
            if previous not in expected:
                return None
        elif expected and previous not in expected:
            return None
        item["status"] = new_state
        item["updated_at"] = now()
        transition = {
            "from": previous,
            "to": new_state,
            "reason": reason,
            "actor": actor,
            "at": now(),
        }
        item["last_transition"] = transition
        if new_state in TERMINAL_STATUSES:
            metric = "canceled" if new_state == "stopped" else new_state
            record_metric(manager, metric)
    manager.runtime.session_event_bus.emit(
        "worker_state_transition", {"worker_id": str(worker_id), **transition}
    )
    return item
