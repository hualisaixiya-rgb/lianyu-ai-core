"""身份确认流程模块。

V4 Stage 0 Phase B2：从 ai/core.py 纯搬移，行为 100% 一致。

IdentityFlow 是 Orchestrator 子组件：
- 不拥有数据库
- 不修改 memory 模块 / profile_store 逻辑
- 只协调已有 Profile/Memory 流程（pending → confirmed → 写入 user_profiles）

红线：resolve_pending 必须由 Orchestrator 在 Step 6a 同步 await，
在 Step 7（构建 Prompt）之前完成 —— 禁止后台化，禁止 create_task。
"""

from loguru import logger


class IdentityFlow:
    """身份三级确认流程协调器。

    依赖通过构造注入：profile_store（用于读取旧值 / 查询已确认姓名）。

    方法均为同步 await 调用（async/sync 类型与 V3.8.1 一致）。
    """

    def __init__(self, profile_store) -> None:
        """初始化。

        Args:
            profile_store: ProfileStore 实例（只读使用，不修改其逻辑）
        """
        self.profile_store = profile_store

    async def has_pending(self, platform: str, platform_user_id: str) -> bool:
        """检查是否有待确认的身份记录。"""
        from database.models.profile import ProfileHistory
        from database.session import AsyncSessionLocal
        from sqlalchemy import select, func as sql_func

        try:
            async with AsyncSessionLocal.get_session() as session:
                stmt = select(sql_func.count()).select_from(ProfileHistory).where(
                    ProfileHistory.platform == platform,
                    ProfileHistory.platform_user_id == platform_user_id,
                    ProfileHistory.status == "pending",
                )
                result = await session.execute(stmt)
                return result.scalar_one() > 0
        except Exception as e:
            logger.debug(f"Pending identity 查询失败: {e}")
            return False

    @staticmethod
    def looks_like_confirmation(message: str) -> bool:
        """检测消息是否为身份确认语句。"""
        msg = message.strip()

        # 排除普通问候语
        greetings = {"早上好", "上午好", "中午好", "下午好", "晚上好",
                     "你好", "你好呀", "嗨", "早"}
        if msg in greetings:
            return False

        if len(msg) > 15:
            return False

        # 只接受明确的确认语义
        confirm_words = [
            "对", "就叫", "就这个", "就它", "就按",
            "嗯", "可以", "行", "是的", "没错",
            "确定了", "就这样", "不改了",
            "好的", "记住", "记住了", "确认",
        ]
        return any(kw in msg for kw in confirm_words)

    async def resolve_pending(
        self, platform: str, platform_user_id: str, confirm_msg: str
    ) -> None:
        """消费最近的 pending 身份记录 → confirmed → 写入 user_profiles。

        在 chat() 主流程中、build_prompt() 之前调用。
        同一轮内 LLM 就能看到更新后的 Profile。
        """
        from database.models.profile import ProfileHistory
        from database.session import AsyncSessionLocal
        from sqlalchemy import desc, select, update as sql_update

        try:
            async with AsyncSessionLocal.get_session() as session:
                # 读取最近的 pending 记录
                stmt = (
                    select(ProfileHistory)
                    .where(
                        ProfileHistory.platform == platform,
                        ProfileHistory.platform_user_id == platform_user_id,
                        ProfileHistory.status == "pending",
                    )
                    .order_by(desc(ProfileHistory.created_at))
                    .limit(1)
                )
                result = await session.execute(stmt)
                pending = result.scalar_one_or_none()

                if pending is None:
                    return

                # 更新 profile_history → confirmed
                pid = pending.id
                from sqlalchemy import text
                await session.execute(
                    text("UPDATE profile_history SET status='confirmed', evidence=:ev WHERE id=:id"),
                    {"ev": f"{pending.evidence or ''}; confirmed: {confirm_msg[:100]}", "id": pid},
                )

                # 写入 user_profiles
                from database.models.profile import UserProfile
                from sqlalchemy import select as sel
                stmt2 = sel(UserProfile).where(
                    UserProfile.platform == platform,
                    UserProfile.platform_user_id == platform_user_id,
                )
                r2 = await session.execute(stmt2)
                row = r2.scalar_one_or_none()
                if row is None:
                    row = UserProfile(
                        platform=platform, platform_user_id=platform_user_id,
                        **{pending.field_name: pending.new_value},
                    )
                    session.add(row)
                else:
                    setattr(row, pending.field_name, pending.new_value)

                await session.flush()
                logger.info(
                    f"Pending resolved: [{platform}:{platform_user_id}] "
                    f"{pending.field_name}={pending.new_value!r} → confirmed"
                )
        except Exception as e:
            logger.warning(f"Pending resolution 失败: {e}")

    async def create_pending(self, context, intent: str) -> None:
        """绕过 LLM + upsert，直接在 profile_history 创建 pending。

        不修改 user_profiles。

        Args:
            context: 聊天上下文（duck typing：platform / platform_user_id / message）
            intent: NAME_INTRO / NICKNAME_SET / NAME_CHANGE_REQUEST
        """
        import re
        from database.models.profile import ProfileHistory
        from database.session import AsyncSessionLocal

        msg = context.message.strip()
        value = None
        field_name = "name"

        if intent == "NAME_INTRO":
            field_name = "name"
            for pat in [r"我叫(.+)", r"我的名字[是叫](.+)", r"我是(.+)"]:
                m = re.match(pat, msg)
                if m:
                    raw = m.group(1).strip()
                    value = re.split(r"[，,。！!？?、…\s]+", raw)[0].strip()
                    break
        elif intent == "NICKNAME_SET":
            field_name = "nickname"
            for pat in [r"(?:以后|以后你|你以后|你可以|可以|平时)?(?:喊|叫)我(.+)"]:
                m = re.search(pat, msg)
                if m:
                    raw = m.group(1).strip()
                    raw = re.split(r"[，,。！!？?、…\s]+", raw)[0].strip()
                    value = re.sub(r"[吧呀啊哦嘛呢吗]$", "", raw).strip()
                    break
        elif intent == "NAME_CHANGE_REQUEST":
            field_name = "name"
            for pat in [r"把名字改成(.+)", r"名字改成(.+)", r"改[个成]名字[为叫]?(.+)",
                       r"改名[为叫]?(.+)"]:
                m = re.match(pat, msg)
                if m:
                    raw = m.group(1).strip()
                    value = re.split(r"[，,。！!？?、…\s]+", raw)[0].strip()
                    break

        if not value or len(value) > 20:
            return

        # 过滤非名字值：疑问词、占位符
        invalid_names = {"什么", "啥", "谁", "哪个", "test", "测试", "名字"}
        if value.strip() in invalid_names:
            return

        # 读旧值
        old_value = None
        try:
            profile = await self.profile_store.get(
                context.platform, context.platform_user_id
            )
            if profile:
                old_value = profile.get_field(field_name)
        except Exception as e:
            logger.debug(f"Profile 读取旧值失败: {e}")

        from memory.extractor import MemoryExtractor
        confidence = MemoryExtractor._compute_confidence(context.message, field_name)

        # 直接写 profile_history，不修改 user_profiles
        try:
            async with AsyncSessionLocal.get_session() as session:
                entry = ProfileHistory(
                    platform=context.platform,
                    platform_user_id=context.platform_user_id,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=value,
                    confidence=confidence,
                    evidence=context.message[:500],
                    status="pending",
                )
                session.add(entry)
            logger.info(
                f"Profile pending: [{context.platform}:{context.platform_user_id}] "
                f"intent={intent} {field_name}={value!r} conf={confidence}"
            )
        except Exception as e:
            logger.warning(f"Profile pending 创建失败: {e}")

    async def get_confirmed_name(
        self, platform: str, platform_user_id: str
    ) -> tuple[str | None, str]:
        """获取用户姓名及其确认级别（V3.5）。

        三级回退：
        1. user_profiles.name → 返回 ("name", "confirmed")
        2. profile_history 最近 7 天的 NAME_INTRO/NICKNAME_SET pending
           → 返回 ("name", "candidate")
        3. 都未找到 → 返回 (None, "")

        candidate 有时限：只取 7 天内最新的 pending 记录，避免旧身份污染。
        """
        from datetime import datetime, timedelta

        # L1: confirmed（user_profiles）
        try:
            profile = await self.profile_store.get(
                platform, platform_user_id
            )
            if profile and profile.name:
                return (profile.name, "confirmed")
        except Exception as e:
            logger.debug(f"Profile confirmed name 查询失败: {e}")

        # L2: candidate（最近 7 天的 pending profile_history）
        try:
            from database.models.profile import ProfileHistory
            from database.session import AsyncSessionLocal
            from sqlalchemy import desc, select

            cutoff = datetime.now() - timedelta(days=7)
            async with AsyncSessionLocal.get_session() as session:
                stmt = (
                    select(ProfileHistory)
                    .where(
                        ProfileHistory.platform == platform,
                        ProfileHistory.platform_user_id == platform_user_id,
                        ProfileHistory.field_name.in_(["name", "nickname"]),
                        ProfileHistory.status == "pending",
                        ProfileHistory.created_at >= cutoff,
                    )
                    .order_by(desc(ProfileHistory.created_at))
                    .limit(1)
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if row and row.new_value:
                    return (row.new_value, "candidate")
        except Exception as e:
            logger.debug(f"Profile candidate name 查询失败: {e}")

        return (None, "")
