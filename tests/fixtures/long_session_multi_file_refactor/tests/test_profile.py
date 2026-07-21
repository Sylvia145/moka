"""Pico 自动化测试模块。"""
from src.main import greeting, report
from src.profile import getUserName


def test_greeting_uses_user_name():
    """执行 `test_greeting_uses_user_name` 的内部逻辑。"""
    assert greeting({"name": " ada "}) == "Hello, Ada"
    assert getUserName({"name": "grace"}) == "Grace"
    assert report({"name": "alan"}) == "User: Alan"
