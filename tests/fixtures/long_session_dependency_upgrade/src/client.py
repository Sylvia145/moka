"""Pico 自动化测试模块。"""
import requests


def build_session():
    """执行 `build_session` 的内部逻辑。"""
    session = requests.Session()
    session.trust_env = True
    return session
