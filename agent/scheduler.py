"""调度器 —— 定时循环，触发主动消息决策与发送。

每 tick 对所有用户执行：
1. 检查是否应发送 → decision.should_send()
2. 生成消息 → generator.generate()
3. 发送消息 → sender.send()
4. 更新状态 → state.record_sent()
"""

import asyncio

from agent.decision import hours_since, should_send
from agent.generator import MessageGenerator
from agent.sender import MessageSender
from agent.state import AgentState, AgentStateRepository
from config.settings import get_settings
from database.engine import init_db
from database.repository import UserRepository
from loguru import logger


class AgentScheduler:
    """被动代理调度器。

    定时运行，管理主动消息的完整生命周期。

    使用方式：
        scheduler = AgentScheduler()
        scheduler.bind_telegram(app)
        await scheduler.run_forever()
    """

    def __init__(
        self,
        tick_minutes: int = 10,
    ) -> None:
        """初始化调度器。

        Args:
            tick_minutes: 每次 tick 的间隔分钟数（5~30）
        """
        self.tick_seconds = max(5, min(30, tick_minutes)) * 60
        self.generator = MessageGenerator()
        self.sender = MessageSender()
        self._running = False
        logger.info(
            f"AgentScheduler 初始化完成 | tick={tick_minutes}min | "
            f"上限={AgentStateRepository.DAILY_MAX}条/天 | "
            f"冷却={AgentStateRepository.COOLDOWN_MINUTES}min"
        )

    def bind_telegram(self, bot_app) -> None:
        """绑定 Telegram Bot Application 实例。

        Args:
            bot_app: telegram.ext.Application
        """
        self.sender.bind(bot_app)

    async def run_forever(self) -> None:
        """启动调度循环（阻塞运行）。"""
        self._running = True
        logger.info(f"AgentScheduler 启动 | 间隔={self.tick_seconds}s")

        # 初始化数据库
        await init_db()

        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"调度 tick 异常: {e}")

            await asyncio.sleep(self.tick_seconds)

    async def run_once(self) -> int:
        """手动执行一次 tick（用于测试）。

        Returns:
            本次发送的消息数
        """
        await init_db()
        return await self._tick()

    def stop(self) -> None:
        """停止调度循环。"""
        self._running = False
        logger.info("AgentScheduler 已停止")

    # ================================================================
    # 内部方法
    # ================================================================

    async def _tick(self) -> int:
        """执行一次调度周期。

        Returns:
            本次发送的消息数
        """
        sent_count = 0

        # 获取所有用户
        users = await UserRepository.get_all_users()
        if not users:
            logger.debug("无注册用户，跳过 tick")
            return 0

        for user in users:
            try:
                if await self._process_user(user.platform, user.platform_user_id):
                    sent_count += 1
            except Exception as e:
                logger.error(
                    f"处理用户失败 {user.platform}:{user.platform_user_id}: {e}"
                )

        if sent_count > 0:
            logger.info(f"本轮 tick 发送 {sent_count} 条主动消息")

        return sent_count

    async def _process_user(self, platform: str, platform_user_id: str) -> bool:
        """处理单个用户：决策 → 生成 → 发送 → 记录。

        Args:
            platform: 平台标识
            platform_user_id: 用户 ID

        Returns:
            是否成功发送
        """
        # 获取状态
        state = await AgentStateRepository.get_or_create(platform, platform_user_id)

        # 衰减 bond（长时间不互动）
        inactive_hours = hours_since(state.last_user_active_time)
        await AgentStateRepository.decay_bond_for_inactive(
            platform, platform_user_id, inactive_hours
        )

        # 决策
        if not should_send(state):
            return False

        # 生成
        message = await self.generator.generate(
            bond=state.bond,
            emotion=state.emotion,
        )
        if not message:
            return False

        # 发送（chat_id = platform_user_id for Telegram）
        success = await self.sender.send(
            chat_id=platform_user_id,
            text=message,
        )

        if success:
            # 记录
            await AgentStateRepository.record_sent(platform, platform_user_id)
            logger.info(
                f"[{platform}:{platform_user_id}] "
                f"bond={state.bond:.2f} daily={state.daily_message_count + 1}"
            )

        return success
