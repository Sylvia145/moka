"""Pico 运行时实现模块。"""

import hashlib
import uuid

from ..features import memory as memorylib
from .workspace import IGNORED_PATH_NAMES, clip, now

CHECKPOINT_SCHEMA_VERSION = "phase1-v1"
CHECKPOINT_NONE_STATUS = "no-checkpoint"
CHECKPOINT_FULL_VALID_STATUS = "full-valid"
CHECKPOINT_PARTIAL_STALE_STATUS = "partial-stale"
CHECKPOINT_WORKSPACE_MISMATCH_STATUS = "workspace-mismatch"
CHECKPOINT_SCHEMA_MISMATCH_STATUS = "schema-mismatch"


class RuntimeCheckpointsMixin:
    def capture_workspace_snapshot(self):
        """执行 `capture_workspace_snapshot` 的内部逻辑。"""
        snapshot = {}
        for path in self.root.rglob("*"):
            try:
                relative_parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            if any(part in IGNORED_PATH_NAMES for part in relative_parts) or not path.is_file():
                continue
            try:
                snapshot[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                continue
        return snapshot

    @staticmethod
    def diff_workspace_snapshots(before, after):
        """执行 `diff_workspace_snapshots` 的内部逻辑。"""
        changed_paths = []
        summaries = []
        for path in sorted(set(before) | set(after)):
            if before.get(path) == after.get(path):
                continue
            changed_paths.append(path)
            if path not in before:
                summaries.append(f"created:{path}")
            elif path not in after:
                summaries.append(f"deleted:{path}")
            else:
                summaries.append(f"modified:{path}")
        return changed_paths, summaries

    def create_checkpoint(self, task_state, user_message, trigger):
        """执行 `create_checkpoint` 的内部逻辑。"""
        state = self.checkpoint_state()
        current = self.current_checkpoint()
        checkpoint_id = "ckpt_" + uuid.uuid4().hex[:8]
        key_files = []
        freshness = {}
        for path in self.memory.to_dict()["working"]["recent_files"]:
            file_freshness = memorylib.file_freshness(path, self.root)
            freshness[path] = file_freshness
            key_files.append({"path": path, "freshness": file_freshness})
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": current.get("checkpoint_id", "") if current else "",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "created_at": now(),
            "current_goal": str(user_message),
            "completed": [task_state.final_answer] if task_state.final_answer else [],
            "excluded": [],
            "current_blocker": "" if str(task_state.stop_reason or "") in ("", "final_answer_returned") else str(task_state.stop_reason),
            "next_step": self.infer_next_step(task_state),
            "key_files": key_files,
            "freshness": freshness,
            "summary": f"{trigger}: {clip(str(user_message), 120)}",
            "runtime_identity": self.current_runtime_identity(),
        }
        state["items"][checkpoint_id] = checkpoint
        state["current_id"] = checkpoint_id
        task_state.checkpoint_id = checkpoint_id
        self.session["runtime_identity"] = checkpoint["runtime_identity"]
        self.session_path = self.session_store.save(self.session)
        return checkpoint

    def current_runtime_identity(self):
        """执行 `current_runtime_identity` 的内部逻辑。"""
        return {
            "session_id": self.session.get("id", ""),
            "cwd": str(self.root),
            "model": str(getattr(self.model_client, "model", "")),
            "model_client": self.model_client.__class__.__name__,
            "approval_policy": self.approval_policy,
            "read_only": bool(self.read_only),
            "max_steps": int(self.max_steps),
            "max_new_tokens": int(self.max_new_tokens),
            "feature_flags": dict(self.feature_flags),
            "shell_env_allowlist": list(self.shell_env_allowlist),
            "workspace_fingerprint": getattr(
                getattr(self, "prefix_state", None),
                "workspace_fingerprint",
                self.workspace.fingerprint(),
            ),
            "tool_signature": self.tool_signature(),
        }

    def checkpoint_state(self):
        """执行 `checkpoint_state` 的内部逻辑。"""
        self._ensure_session_shape()
        return self.session["checkpoints"]

    def current_checkpoint(self):
        """执行 `current_checkpoint` 的内部逻辑。"""
        state = self.checkpoint_state()
        checkpoint_id = str(state.get("current_id", "")).strip()
        if not checkpoint_id:
            return None
        return state.get("items", {}).get(checkpoint_id)

    def invalidate_stale_memory(self):
        """执行 `invalidate_stale_memory` 的内部逻辑。"""
        invalidated = self.memory.invalidate_stale_file_summaries()
        self.session["memory"] = self.memory.to_dict()
        return invalidated

    def evaluate_resume_state(self):
        """执行 `evaluate_resume_state` 的内部逻辑。"""
        previous_resume_state = dict(self.session.get("resume_state", {}) or {})
        invalidated = self.invalidate_stale_memory()
        checkpoint = self.current_checkpoint()
        status = CHECKPOINT_NONE_STATUS
        stale_paths = list(invalidated)
        mismatch_fields = []
        if checkpoint:
            if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
                status = CHECKPOINT_SCHEMA_MISMATCH_STATUS
            else:
                for item in checkpoint.get("key_files", []):
                    path = str(item.get("path", "")).strip()
                    if not path:
                        continue
                    expected = item.get("freshness")
                    current = memorylib.file_freshness(path, self.root)
                    if expected != current and path not in stale_paths:
                        stale_paths.append(path)
                saved_identity = dict(
                    checkpoint.get("runtime_identity", {})
                    or self.session.get("runtime_identity", {})
                    or {}
                )
                current_identity = self.current_runtime_identity()
                identity_keys = (
                    "cwd",
                    "model",
                    "model_client",
                    "approval_policy",
                    "read_only",
                    "max_steps",
                    "max_new_tokens",
                    "feature_flags",
                    "shell_env_allowlist",
                    "workspace_fingerprint",
                    "tool_signature",
                )
                for key in identity_keys:
                    if key not in saved_identity:
                        continue
                    if saved_identity.get(key) != current_identity.get(key):
                        mismatch_fields.append(key)
                mismatch_fields.sort()
                if stale_paths:
                    status = CHECKPOINT_PARTIAL_STALE_STATUS
                elif mismatch_fields:
                    status = CHECKPOINT_WORKSPACE_MISMATCH_STATUS
                else:
                    status = CHECKPOINT_FULL_VALID_STATUS

        resume_state = {
            "status": status,
            "stale_paths": stale_paths,
            "runtime_identity_mismatch_fields": mismatch_fields,
            "stale_summary_invalidations": max(
                len(invalidated),
                int(previous_resume_state.get("stale_summary_invalidations", 0))
                if status == CHECKPOINT_PARTIAL_STALE_STATUS
                else 0,
            ),
        }
        self.session["resume_state"] = resume_state
        self.session["runtime_identity"] = self.current_runtime_identity()
        return resume_state

    def render_checkpoint_text(self):
        """执行 `render_checkpoint_text` 的内部逻辑。"""
        checkpoint = self.current_checkpoint()
        if not checkpoint:
            return ""
        lines = [
            "Task checkpoint:",
            f"- Resume status: {self.resume_state.get('status', CHECKPOINT_NONE_STATUS)}",
            f"- Current goal: {checkpoint.get('current_goal', '-') or '-'}",
            f"- Current blocker: {checkpoint.get('current_blocker', '-') or '-'}",
            f"- Next step: {checkpoint.get('next_step', '-') or '-'}",
        ]
        key_files = [
            str(item.get("path", "")).strip()
            for item in checkpoint.get("key_files", [])
            if str(item.get("path", "")).strip()
        ]
        lines.append(f"- Key files: {', '.join(key_files) or '-'}")
        if checkpoint.get("completed"):
            lines.append(
                "- Completed: "
                + " | ".join(str(item) for item in checkpoint.get("completed", []))
            )
        if checkpoint.get("excluded"):
            lines.append(
                "- Excluded: "
                + " | ".join(str(item) for item in checkpoint.get("excluded", []))
            )
        if self.resume_state.get("stale_paths"):
            lines.append(
                "- Stale paths: " + ", ".join(self.resume_state["stale_paths"])
            )
        summary = str(checkpoint.get("summary", "")).strip()
        if summary:
            lines.append(f"- Summary: {summary}")
        return "\n".join(lines)
