"""Prompt 管理。

将系统 Prompt / Memory Prompt / 工具 Prompt 等
从代码中分离到模板文件，便于独立维护和版本控制。
"""

from prompt.manager import PromptManager

__all__ = ["PromptManager"]
