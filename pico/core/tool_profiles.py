"""Pico 运行时实现模块。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSetProfile:
    name: str
    allowed_tools: frozenset[str]

    def allows(self, tool_name):
        """执行 `allows` 的内部逻辑。"""
        return tool_name in self.allowed_tools


def build_tool_profiles(tools):
    """执行 `build_tool_profiles` 的内部逻辑。"""
    all_tools = frozenset(tools)
    coordinator_tools = frozenset({"agent", "send_message", "task_stop"})
    mode_tools = frozenset({"enter_plan_mode", "exit_plan_mode"})
    interactive_tools = frozenset({"ask_user"})
    read_only = (
        frozenset(name for name, tool in tools.items() if tool.read_only)
        - coordinator_tools
        - mode_tools
        - interactive_tools
    )
    plan_tools = read_only | frozenset(
        {
            "write_file",
            "patch_file",
            "agent",
            "send_message",
            "task_stop",
            "ask_user",
            "exit_plan_mode",
        }
    )
    dream_tools = read_only | frozenset({"write_file", "patch_file"})
    delegated_review_tools = read_only | frozenset({"send_message", "task_stop"})
    worker_tools = (
        all_tools
        - coordinator_tools
        - mode_tools
        - interactive_tools
        - frozenset({"run_shell"})
    )
    return {
        "default": ToolSetProfile("default", all_tools),
        "plan": ToolSetProfile("plan", plan_tools & all_tools),
        "dream": ToolSetProfile("dream", dream_tools & all_tools),
        "readonly": ToolSetProfile("readonly", read_only),
        "delegated_review": ToolSetProfile("delegated_review", delegated_review_tools & all_tools),
        "worker": ToolSetProfile("worker", worker_tools),
    }
