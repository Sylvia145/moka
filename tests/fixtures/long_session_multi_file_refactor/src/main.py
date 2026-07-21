"""Pico 自动化测试模块。"""
from src.profile import getUserName
from src.report import render_user


def greeting(user):
    """执行 `greeting` 的内部逻辑。"""
    return f"Hello, {getUserName(user)}"


def report(user):
    """执行 `report` 的内部逻辑。"""
    return render_user(user)
