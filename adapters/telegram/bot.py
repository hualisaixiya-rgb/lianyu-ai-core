"""Telegram Bot 适配器。

基于 python-telegram-bot 库实现。
负责：
1. 接收 Telegram 消息
2. 转换为 ChatContext
3. 调用 AI Core
4. 将回复发送回 Telegram
"""

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from ai.core import AICore, ChatContext
from config.settings import get_settings
from loguru import logger
from utils.response_renderer import render_for_user


class TelegramBot:
    """Telegram Bot 适配器。

    封装 python-telegram-bot 的初始化和消息处理。
    不包含任何 AI 逻辑，所有推理委托给 AICore。

    使用方式：
        bot = TelegramBot(ai_core)
        await bot.start()
    """

    def __init__(self, ai_core: AICore | None = None) -> None:
        """初始化 Telegram Bot。

        Args:
            ai_core: AI Core 实例。为 None 时自动创建。
        """
        self.settings = get_settings()
        self.ai_core = ai_core or AICore()
        self._app: Application | None = None
        logger.info("TelegramBot 初始化完成")

    def _build_app(self) -> Application:
        """构建 python-telegram-bot Application 实例。

        使用显式 HTTPXRequest 配置：
        - 超时从默认 5s 提升到 15~30s（适应代理链路延迟）
        - 连接池从默认 256 降到 8（避免代理断开后复用死连接）

        Returns:
            配置好的 Application 实例
        """
        token = self.settings.telegram.bot_token
        if not token:
            raise ValueError(
                "Telegram Bot Token 未配置。请设置环境变量 TELEGRAM_BOT_TOKEN。"
            )

        # 构建自定义 HTTPXRequest（替代 builder.proxy() 的默认配置）
        request_kwargs = {}
        proxy_url = self.settings.telegram.proxy
        if proxy_url:
            request_kwargs["proxy"] = proxy_url
            logger.info(f"Telegram 使用代理: {proxy_url}")

        request = HTTPXRequest(
            connection_pool_size=8,       # 默认 256 → 8，减少代理死连接命中
            connect_timeout=15.0,          # 默认 5s → 15s，代理链路需要更长时间
            read_timeout=30.0,             # 默认 5s → 30s，Telegram API 可能延迟
            write_timeout=15.0,            # 默认 5s → 15s
            pool_timeout=5.0,              # 默认 1s → 5s
            **request_kwargs,
        )

        bot = Bot(token=token, request=request)
        app = Application.builder().bot(bot).build()

        # 注册命令处理器
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("help", self._handle_help))

        # 注册文本消息处理器（必须放在最后，否则会拦截命令）
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        return app

    async def start(self) -> None:
        """启动 Bot 轮询。

        开始接收 Telegram 消息并处理。
        """
        self._app = self._build_app()
        logger.info("Telegram Bot 启动中...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram Bot 已启动，等待消息...")

    async def stop(self) -> None:
        """停止 Bot。

        优雅关闭 Bot 和所有后台任务。
        """
        if self._app:
            logger.info("Telegram Bot 正在停止...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram Bot 已停止")

    # ============================================================
    # 命令处理器
    # ============================================================

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /start 命令。"""
        user = update.effective_user
        username = user.first_name or user.username or "陌生人"
        await update.message.reply_text(
            f"……你好。\n"
            f"我是绘梨衣。"
        )

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /help 命令。"""
        await update.message.reply_text(
            "可用命令：\n"
            "/start - 开始对话\n"
            "/help - 显示帮助\n"
            "你也可以直接发送消息与我聊天！"
        )

    # ============================================================
    # 消息处理器
    # ============================================================

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理用户文本消息。

        这是核心流程：
        1. 从 Telegram Update 提取信息
        2. 构建 ChatContext
        3. 调用 AI Core
        4. 发送回复
        """
        user = update.effective_user
        user_id = str(user.id)
        username = user.username or user.first_name or "未知"
        text = update.message.text

        # 检测引用回复：用户是否回复了某条消息
        reply_to_text: str | None = None
        if update.message.reply_to_message:
            replied = update.message.reply_to_message
            # 提取被引用消息的文本
            if replied.text:
                reply_to_text = replied.text
            elif replied.caption:
                reply_to_text = replied.caption
            if reply_to_text:
                logger.debug(
                    f"检测到引用回复 | 被引用: {reply_to_text[:80]}..."
                )

        logger.debug(f"收到消息: [{user_id}] {username}: {text}")

        # 更新 Agent 活跃时间
        from agent.state import AgentStateRepository
        try:
            await AgentStateRepository.update_user_active("telegram", user_id)
        except Exception:
            pass  # Agent 未初始化时静默跳过

        # 发送"正在输入..."状态（独立异常处理，失败不影响主流程）
        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="typing",
            )
        except Exception:
            pass  # 代理波动时 send_chat_action 可能超时，不阻塞聊天

        # 构建 ChatContext 并调用 AI Core
        chat_context = ChatContext(
            platform="telegram",
            platform_user_id=user_id,
            message=text,
            username=username,
            reply_to_message=reply_to_text,
        )

        try:
            response = await self.ai_core.chat(chat_context)
            # 表达层：修复格式漂移 + 按场景调节表达强度（用户消息上下文），再发送
            user_reply = render_for_user(response.content, text)
            # 带重试的发送（代理偶尔不稳）
            await self._reply_with_retry(update, user_reply)
        except Exception as e:
            logger.error(f"处理消息失败: {e}")

    async def _reply_with_retry(self, update: Update, text: str, max_retries: int = 2) -> None:
        """带重试的回复发送。

        Telegram API 可能因代理波动超时，重试提高成功率。

        Args:
            update: Telegram Update 对象
            text: 要发送的文本
            max_retries: 最大重试次数
        """
        import asyncio

        for attempt in range(max_retries + 1):
            try:
                await update.message.reply_text(text)
                return
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"发送回复失败（第{attempt+1}次），1秒后重试: {e}")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"发送回复失败（已重试{max_retries}次）: {e}")
