"""会话恢复时的 Worker 重建策略。"""

from .worker_background import start_next_queued
from .worker_tasks import restore_queued_task


def recover_workers_after_resume(manager):
    """queued 重新入队；缺少本地实体的 active 任务明确失败。"""
    for item in list(manager.state.get("items", [])):
        status = item.get("status")
        if status == "queued":
            manager._tasks[item["id"]] = restore_queued_task(manager, item)
        elif status in {"starting", "running", "stopping"}:
            manager.transition_worker_state(
                item["id"], {status}, "failed", reason="resume_execution_entity_missing", actor="resume"
            )
    while manager._tasks and manager.metrics()["running"] < manager.max_concurrent_workers:
        pending = manager.metrics()["pending"]
        start_next_queued(manager)
        if manager.metrics()["pending"] == pending:
            break
    manager._save()
