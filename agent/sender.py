"""消息发送器 —— 通过 Telegram Bot 向用户推送主动消息。"""

from loguru import logger


class MessageSender:
    """消息发送器。

    封装 Telegram Bot 引用，向指定用户发送主动消息。
    """

    def __init__(self) -> None:
        """初始化发送器（延迟绑定 Bot 实例）。"""
        self._bot = None
        self._app = None
        logger.debug("MessageSender 初始化（Bot 引用待绑定）")

    def bind(self, bot_app) -> None:
        """绑定 python-telegram-bot Application 实例。

        Args:
            bot_app: telegram.ext.Application 实例
        """
        self._app = bot_app
        self._bot = bot_app.bot
        logger.info("MessageSender 已绑定 Telegram Bot")

    async def send(self, chat_id: str, text: str) -> bool:
        """发送消息到指定用户。

        Args:
            chat_id: Telegram chat_id（即 platform_user_id）
            text: 消息文本

        Returns:
            是否发送成功
        """
        if not self._bot:
            logger.warning("MessageSender 未绑定 Bot，跳过发送")
            return False

        if not text.strip():
            logger.debug("消息为空，跳过发送")
            return False

        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
            logger.info(f"主动消息已发送 -> {chat_id}: {text}")
            return True
        except Exception as e:
            logger.error(f"发送失败 -> {chat_id}: {e}")
            return False
