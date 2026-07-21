"""Pico 运行时实现模块。

权限检查只回答“当前动作是否被允许”；更细粒度的操作约束由工具策略层处理，
两者分离可使拒绝原因稳定、可解释并便于审计。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PermissionDecision:
    decision: str
    reason: str
    security_event_type: str = ""

    @classmethod
    def allow(cls, reason):
        """执行 `allow` 的内部逻辑。"""
        return cls("allow", reason)

    @classmethod
    def deny(cls, reason, security_event_type=""):
        """执行 `deny` 的内部逻辑。"""
        return cls("deny", reason, security_event_type)

    @property
    def allowed(self):
        """执行 `allowed` 的内部逻辑。"""
        return self.decision == "allow"


class PermissionChecker:
    def __init__(self, runtime):
        """初始化对象状态。"""
        self.runtime = runtime

    def check(self, tool, args):
        """执行 `check` 的内部逻辑。"""
        args = args or {}
        profile = self.runtime.active_tool_profile
        # profile 是运行模式的第一道硬边界。必须先检查它，避免后续的“自动批准”
        # 意外绕过计划模式或委派审查模式的工具集合限制。
        if not profile.allows(tool.name):
            if profile.name == "plan":
                return PermissionDecision.deny("plan_mode_tool_not_allowed", "plan_mode_write_guard")
            if profile.name == "delegated_review":
                return PermissionDecision.deny("delegated_write_guard", "delegated_write_guard")
            return PermissionDecision.deny("tool_not_allowed")

        if self.runtime.runtime_mode == "plan":
            return self._check_plan(tool, args)

        if tool.name in {"write_file", "patch_file"} and getattr(self.runtime, "write_scope", ()):
            return self._check_write_scope(tool, args)
        if tool.read_only:
            return PermissionDecision.allow("read_only")
        if self.runtime.read_only:
            return PermissionDecision.deny("approval_denied", "read_only_block")
        if self.runtime.approval_policy == "auto":
            return PermissionDecision.allow("approval_auto")
        if self.runtime.approval_policy == "never":
            return PermissionDecision.deny("approval_denied", "approval_denied")
        if self.runtime.approve(tool.name, args):
            return PermissionDecision.allow("approval_prompt")
        return PermissionDecision.deny("approval_denied", "approval_denied")

    def _check_plan(self, tool, args):
        """执行 `_check_plan` 的内部逻辑。"""
        if tool.read_only:
            return PermissionDecision.allow("plan_read_only")
        if tool.name not in {"write_file", "patch_file"}:
            return PermissionDecision.deny("plan_mode_tool_not_allowed", "plan_mode_write_guard")
        # 计划模式允许写入唯一的计划工件，而不是任意工作区文件；比较解析后的
        # Path 可同时避免相对路径别名和不同分隔符造成的绕过。
        requested = self.runtime.path(args.get("path", ""))
        active = self.runtime.path(self.runtime.plan_mode.plan_path)
        if Path(requested) != Path(active):
            return PermissionDecision.deny("plan_mode_path_mismatch", "plan_mode_write_guard")
        return PermissionDecision.allow("plan_artifact_write")

    def _check_write_scope(self, tool, args):
        # 子代理的可写范围按“请求路径是否位于授权目录之下”判断，不做字符串
        # 前缀匹配，以免 `src2` 被误认为属于 `src`。
        """执行 `_check_write_scope` 的内部逻辑。"""
        requested = self.runtime.path(args.get("path", ""))
        for raw_scope in self.runtime.write_scope:
            scope = self.runtime.path(raw_scope)
            try:
                requested.relative_to(scope)
                return PermissionDecision.allow("write_scope")
            except ValueError:
                continue
        return PermissionDecision.deny("write_scope_mismatch", "write_scope_guard")


def permission_error_message(agent, tool, decision):
    """Format the user-facing error for a denied permission decision.

    Lives here (rather than in tool_executor) so the mapping from a deny reason
    to its message stays next to the code that produces those reasons.
    """
    if decision.reason == "plan_mode_path_mismatch":
        return f"error: plan mode can only write the active plan artifact ({agent.plan_mode.plan_path})"
    if decision.reason == "plan_mode_tool_not_allowed":
        return f"error: plan mode only allows read-only tools or writing the active plan artifact ({agent.plan_mode.plan_path})"
    if decision.reason == "write_scope_mismatch":
        return f"error: worker write_scope does not allow {tool.name} on this path"
    if decision.reason == "delegated_write_guard":
        return f"error: delegated review mode blocks {tool.name}; a write worker owns the change and its handoff requires human review"
    if decision.reason in {"approval_denied", "tool_not_allowed"}:
        return f"error: approval denied for {tool.name}"
    return f"error: permission denied for {tool.name}: {decision.reason}"
