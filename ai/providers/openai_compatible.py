"""OpenAI 兼容 API 提供商。

适用于 DeepSeek、OpenAI、Qwen、vLLM 等所有兼容 OpenAI Chat Completions 格式的服务。
"""

from openai import AsyncOpenAI

from config.settings import get_settings


class OpenAICompatibleProvider:
    """OpenAI 兼容 LLM 提供商。

    封装 AsyncOpenAI 客户端，提供统一的 chat completion 接口。

    使用方式：
        provider = OpenAICompatibleProvider()
        response = await provider.chat(messages=[...])
    """

    def __init__(self) -> None:
        """初始化 OpenAI 兼容客户端。

        从全局配置读取 base_url、api_key、model 等参数。
        """
        settings = get_settings()
        self.model = settings.ai.model
        self.max_tokens = settings.ai.max_tokens
        self.temperature = settings.ai.temperature

        self.client = AsyncOpenAI(
            base_url=settings.ai.base_url,
            api_key=settings.ai.api_key,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> str:
        """发送聊天请求并返回文本回复。

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}, ...]
            system_prompt: 系统提示（可选），会插入到 messages 最前面

        Returns:
            LLM 返回的文本内容

        Raises:
            ValueError: API key 未配置时抛出
            RuntimeError: API 调用失败时抛出
        """
        if not self.client.api_key:
            raise ValueError(
                "LLM API Key 未配置。请设置环境变量 AI_LLM_API_KEY 或检查 .env 文件。"
            )

        # 构造完整消息列表
        full_messages: list[dict[str, str]] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
            from loguru import logger
            logger.debug(f"[Provider] System Prompt ({len(system_prompt)} chars):\n{system_prompt}")
        full_messages.extend(messages)
        from loguru import logger
        logger.debug(f"[Provider] History messages: {len(messages)} 条")

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        except Exception as e:
            raise RuntimeError(f"LLM API 调用失败: {e}") from e

        # 提取回复文本
        choice = response.choices[0]
        content = choice.message.content or ""
        return content
