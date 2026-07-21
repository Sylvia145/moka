"""Pico 自动化测试模块。"""
from app import app


def test_index():
    """执行 `test_index` 的内部逻辑。"""
    response = app.test_client().get("/")
    assert response.status_code == 200
