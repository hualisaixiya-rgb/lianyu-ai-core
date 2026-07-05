"""AI Core - 核心推理引擎。

这是整个项目的核心，所有消息处理都通过此模块完成。
对外暴露统一的 chat 接口，内部组合 Memory、Character、Prompt、Tools 模块。
"""

from ai.core import AICore

__all__ = ["AICore"]
