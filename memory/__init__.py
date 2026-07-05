"""长期记忆模块。

提供记忆的存储、检索、压缩和遗忘功能。
通过抽象基类 MemoryStore 支持多种后端（SQLite / 向量数据库）。
"""

from memory.base import MemoryStore
from memory.manager import MemoryManager

__all__ = ["MemoryStore", "MemoryManager"]
