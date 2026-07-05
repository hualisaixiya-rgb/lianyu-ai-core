"""工具调用模块。

提供工具注册、发现和调用的统一框架。
内置工具和外部工具（MCP、自定义）都通过此模块注册。
"""

from tools.registry import ToolRegistry

__all__ = ["ToolRegistry"]
