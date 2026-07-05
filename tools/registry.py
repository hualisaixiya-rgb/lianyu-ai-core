"""工具注册表。

管理所有可用工具的注册、发现和调用。
"""

from collections.abc import Callable
from typing import Any

from loguru import logger


class ToolRegistry:
    """工具注册表。

    提供工具的注册、查找和调用功能。
    每个工具有唯一名称，以及对应的处理函数。

    使用方式：
        registry = ToolRegistry()
        registry.register("calculator", calculator_handler)
        result = await registry.call("calculator", expression="1+1")
    """

    def __init__(self) -> None:
        """初始化工具注册表。"""
        self._tools: dict[str, Callable[..., Any]] = {}
        logger.info("ToolRegistry 初始化完成")

    def register(self, name: str, handler: Callable[..., Any]) -> None:
        """注册一个工具。

        Args:
            name: 工具名称（唯一标识）
            handler: 工具处理函数（支持异步）

        Raises:
            ValueError: 工具名已存在
        """
        if name in self._tools:
            raise ValueError(f"工具已注册: {name}")
        self._tools[name] = handler
        logger.debug(f"工具已注册: {name}")

    def unregister(self, name: str) -> None:
        """移除一个工具。

        Args:
            name: 工具名称
        """
        if name in self._tools:
            del self._tools[name]
            logger.debug(f"工具已移除: {name}")

    def list_tools(self) -> list[str]:
        """列出所有已注册的工具名。

        Returns:
            工具名列表
        """
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        """检查工具是否存在。

        Args:
            name: 工具名称

        Returns:
            是否存在
        """
        return name in self._tools

    async def call(self, name: str, **kwargs: Any) -> Any:
        """调用一个工具。

        Args:
            name: 工具名称
            **kwargs: 传递给工具的命名参数

        Returns:
            工具的返回值

        Raises:
            KeyError: 工具不存在
            Exception: 工具执行过程中的异常
        """
        if name not in self._tools:
            raise KeyError(f"工具不存在: {name}")

        handler = self._tools[name]
        logger.info(f"调用工具: {name}({kwargs})")

        try:
            result = handler(**kwargs)
            # 支持异步和同步处理函数
            if hasattr(result, "__await__"):
                result = await result
            return result
        except Exception as e:
            logger.error(f"工具 {name} 执行失败: {e}")
            raise
