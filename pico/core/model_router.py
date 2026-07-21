"""Pico 运行时实现模块。"""

from __future__ import annotations


class ModelClientRouter:
    def __init__(self, main_client, vision_client=None, vision_client_factory=None):
        """初始化对象状态。"""
        self.main_client = main_client
        self._vision_client = vision_client
        self._vision_client_factory = vision_client_factory

    def default_client(self):
        """执行 `default_client` 的内部逻辑。"""
        return self.main_client

    def vision_client(self):
        """执行 `vision_client` 的内部逻辑。"""
        if self._vision_client is not None:
            return self._vision_client
        if self._vision_client_factory is None:
            return self.main_client
        self._vision_client = self._vision_client_factory()
        return self._vision_client

    def client_for_input(self, model_input):
        """执行 `client_for_input` 的内部逻辑。"""
        if getattr(model_input, "image_count", 0):
            return self.vision_client()
        return self.main_client
