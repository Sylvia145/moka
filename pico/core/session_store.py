"""Session JSON storage."""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .workspace import clip

WINDOWS_REPLACE_RETRIES = 3
WINDOWS_REPLACE_RETRY_DELAY_SECONDS = 0.05


class SessionStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path(self, session_id):
        return self.root / f"{_safe_session_id(session_id)}.json"

    def event_path(self, session_id):
        return self.root / f"{_safe_session_id(session_id)}.events.jsonl"

    def save(self, session):
        path = self.path(session["id"])
        payload = json.dumps(session, indent=2)
        with self._lock:
            tmp_path = path.with_name(
                f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            tmp_path.write_text(payload, encoding="utf-8")
            # Windows 可能在刚写入后短暂占用目标文件（见 INC-0011）；与 RunStore 对齐，
            # 对 PermissionError 做有限重试，避免瞬时锁被误判为持久化失败。
            for attempt in range(WINDOWS_REPLACE_RETRIES):
                try:
                    os.replace(tmp_path, path)
                    break
                except PermissionError:
                    if attempt + 1 == WINDOWS_REPLACE_RETRIES:
                        tmp_path.unlink(missing_ok=True)
                        raise
                    time.sleep(WINDOWS_REPLACE_RETRY_DELAY_SECONDS * (attempt + 1))
        return path

    def load(self, session_id):
        with self._lock:
            return json.loads(self.path(session_id).read_text(encoding="utf-8"))

    def latest(self):
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime)
        return files[-1].stem if files else None

    def list_sessions(self):
        rows = []
        for index, path in enumerate(
            sorted(
                self.root.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            ),
            start=1,
        ):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            history = list(session.get("history", []))
            rows.append(
                {
                    "index": index,
                    "id": str(session.get("id", path.stem)),
                    "created_at": str(session.get("created_at", "")),
                    "updated_at": datetime.fromtimestamp(
                        path.stat().st_mtime
                    ).isoformat(timespec="seconds"),
                    "history_count": len(history),
                    "runtime_mode": str(
                        session.get("runtime_mode", {}).get("mode", "default")
                        or "default"
                    ),
                    "workspace_root": str(session.get("workspace_root", "")),
                    "last_final_answer": _last_final_preview(history),
                }
            )
        return rows


def _last_final_preview(history):
    for item in reversed(history):
        if item.get("role") == "assistant":
            return clip(item.get("content", ""), 80)
    return ""


def _safe_session_id(session_id):
    value = str(session_id or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("invalid session id")
    return value
