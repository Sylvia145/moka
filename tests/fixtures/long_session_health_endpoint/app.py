"""Pico 自动化测试模块。"""
try:
    from flask import Flask
except Exception:
    class _Response:
        def __init__(self, payload, status_code):
            """执行 `__init__` 的内部逻辑。"""
            self._payload = payload
            self.status_code = status_code

        def get_json(self):
            """执行 `get_json` 的内部逻辑。"""
            return self._payload

    class _Client:
        def __init__(self, app):
            """执行 `__init__` 的内部逻辑。"""
            self.app = app

        def get(self, path):
            """执行 `get` 的内部逻辑。"""
            handler = self.app.routes[path]
            result = handler()
            if isinstance(result, tuple):
                payload, status_code = result
            else:
                payload, status_code = result, 200
            return _Response(payload, status_code)

    class Flask:
        def __init__(self, name):
            """执行 `__init__` 的内部逻辑。"""
            self.name = name
            self.routes = {}

        def route(self, path):
            """执行 `route` 的内部逻辑。"""
            def decorator(fn):
                """执行 `decorator` 的内部逻辑。"""
                self.routes[path] = fn
                return fn
            return decorator

        def test_client(self):
            """执行 `test_client` 的内部逻辑。"""
            return _Client(self)


app = Flask(__name__)


@app.route("/")
def index():
    """执行 `index` 的内部逻辑。"""
    return {"status": "running"}, 200
