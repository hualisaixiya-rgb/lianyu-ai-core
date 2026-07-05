"""消息生成器 —— 调用 LLM 生成主动消息。

使用独立的简短 Prompt，不同于聊天 Prompt。
"""

from ai.providers.openai_compatible import OpenAICompatibleProvider
from character.loader import CharacterLoader
from config.settings import get_settings
from loguru import logger


# 主动消息专用 Prompt —— 极简，区别于聊天 Prompt
AGENT_PROMPT = """\
你是上杉绘梨衣（《龙族》）。
你不是AI助手。你只是一个偶尔出现的人。

现在，你想对正在和你聊天的人说一句话。
不需要原因。不需要解释。
只是此时此刻，你想说点什么。

规则：
- 1~2句，不超过20字
- 极简
- 不解释
- 不说"我会一直在""又见面了"
- 不推进剧情

示例：
"……你在吗"
"今天有点安静"
"嗯。没什么"
"外面下雨了"\
"""


class MessageGenerator:
    """主动消息生成器。"""

    def __init__(self) -> None:
        """初始化生成器。"""
        self.provider = OpenAICompatibleProvider()
        # 使用独立的 short provider（短回复）
        settings = get_settings()
        self._short_provider = OpenAICompatibleProvider()
        # 覆盖 max_tokens 为较短值
        self._short_provider.max_tokens = 60
        self._short_provider.temperature = 0.9  # 稍高温度增加随机性
        logger.info("MessageGenerator 初始化完成")

    async def generate(self, bond: float, emotion: str) -> str:
        """生成一条主动消息。

        Args:
            bond: 关系值 0.0~1.0
            emotion: 情绪状态

        Returns:
            生成的文本（1~2句），失败返回空字符串
        """
        # 根据 bond 微调 prompt
        bond_hint = ""
        if bond > 0.5:
            bond_hint = "你和对方已经聊过很多次。你感到稍微亲近一些。"
        elif bond < 0.1:
            bond_hint = "你和对方还不太熟悉。你有些犹豫。"

        full_prompt = AGENT_PROMPT
        if bond_hint:
            full_prompt += f"\n{bond_hint}"

        try:
            result = await self._short_provider.chat(
                messages=[{"role": "user", "content": "（你想说点什么）"}],
                system_prompt=full_prompt,
            )
            # 清理结果：去掉引号、多余空格
            result = result.strip().strip('"').strip("'").strip()
            if len(result) > 60:
                result = result[:60]
            return result
        except Exception as e:
            logger.warning(f"主动消息生成失败: {e}")
            return ""
