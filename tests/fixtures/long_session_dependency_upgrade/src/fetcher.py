"""Pico 自动化测试模块。"""
import requests


def fetch_text(url):
    """执行 `fetch_text` 的内部逻辑。"""
    response = requests.get(url, timeout=None)
    return response.text
