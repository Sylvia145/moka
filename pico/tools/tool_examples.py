"""Prompt-format examples for built-in tools."""

from .agents import AGENT_TOOL_EXAMPLES
from .ask_user import ASK_USER_TOOL_EXAMPLES
from .media import MEDIA_TOOL_EXAMPLES
from .plan import PLAN_TOOL_EXAMPLES
from .todos import TODO_TOOL_EXAMPLES

TOOL_EXAMPLES = {
    "list_files": '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
    "read_file": '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":80}}</tool>',
    "search": '<tool>{"name":"search","args":{"pattern":"binary_search","path":"."}}</tool>',
    "run_shell": '<tool>{"name":"run_shell","args":{"command":"uv run --with pytest python -m pytest -q","timeout":20}}</tool>',
    "write_file": '<tool name="write_file" path="binary_search.py"><content>def binary_search(nums, target):\n    return -1\n</content></tool>',
    "patch_file": '<tool name="patch_file" path="binary_search.py"><old_text>return -1</old_text><new_text>return mid</new_text></tool>',
    **MEDIA_TOOL_EXAMPLES,
    **TODO_TOOL_EXAMPLES,
    **AGENT_TOOL_EXAMPLES,
    **PLAN_TOOL_EXAMPLES,
    **ASK_USER_TOOL_EXAMPLES,
}


def tool_example(name):
    return TOOL_EXAMPLES.get(name, "")
