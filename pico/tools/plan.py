"""Pico 运行时实现模块。"""

PLAN_TOOL_SPECS = {
    "enter_plan_mode": {
        "schema": {"topic": "str", "path": "str?"},
        "risky": False,
        "description": "Enter plan mode for a named planning topic.",
    },
    "exit_plan_mode": {
        "schema": {},
        "risky": False,
        "description": "Exit plan mode and return to default runtime mode.",
    },
}

PLAN_TOOL_EXAMPLES = {
    "enter_plan_mode": '<tool>{"name":"enter_plan_mode","args":{"topic":"Refactor auth"}}</tool>',
    "exit_plan_mode": '<tool>{"name":"exit_plan_mode","args":{}}</tool>',
}



def tool_enter_plan_mode(agent, args):
    """执行 `tool_enter_plan_mode` 的内部逻辑。"""
    path = agent.enter_plan_mode(args["topic"], path=args.get("path"))
    return f"mode: plan\nplan path: {path}"


def tool_exit_plan_mode(agent, args):
    """执行 `tool_exit_plan_mode` 的内部逻辑。"""
    agent.exit_plan_mode()
    return "mode: default"
