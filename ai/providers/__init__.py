"""LLM 提供商适配层。

每个提供商实现统一的 LLMProvider 接口，
方便切换 DeepSeek / OpenAI / Qwen 等。
"""

from ai.providers.openai_compatible import OpenAICompatibleProvider

__all__ = ["OpenAICompatibleProvider"]
