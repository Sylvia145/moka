"""Pico 运行时实现模块。"""


class SandboxChecker:
    def __init__(self, which):
        """初始化对象状态。"""
        self.which = which

    def backend_path(self, backend):
        """执行 `backend_path` 的内部逻辑。"""
        backend = "bubblewrap" if backend == "auto" else backend
        if backend in {"none", "off"}:
            return ""
        if backend == "bubblewrap":
            return self.which("bwrap") or ""
        return ""
