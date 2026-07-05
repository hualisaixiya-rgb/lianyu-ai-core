"""Telegram Adapter。

将 Telegram 消息转换为 AI Core 可理解的 ChatContext，
并将 AI Core 的 ChatResponse 转换回 Telegram 消息格式。

这是 Adapter 模式的实现 —— Telegram 只是一个"翻译官"，
所有 AI 逻辑都在 ai/ 模块中。
"""

from adapters.telegram.bot import TelegramBot

__all__ = ["TelegramBot"]
