"""Pico 自动化测试模块。"""
import requests


def fetch_json(url):
    """执行 `fetch_json` 的内部逻辑。"""
    response = requests.get(url, verify=False)
    return response.json()
