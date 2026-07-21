"""Pico 自动化测试模块。"""
from src.profile import getUserName


def render_user(user):
    """执行 `render_user` 的内部逻辑。"""
    return f"User: {getUserName(user)}"
