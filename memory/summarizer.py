"""对话摘要器 —— 滚动累积 + 结构化格式 + 自动压缩。

当对话历史超过阈值时，将旧消息批量压缩为结构化摘要。
摘要随对话推进滚动更新，超出长度限制时自动压缩。

用法：
    from memory.summarizer import ConversationSummarizer
    summarizer = ConversationSummarizer()
    new_summary = await summarizer.summarize(old_msgs, existing_summary, provider)
"""

from loguru import logger


# 每次摘要的触发阈值（pending 消息数）
SUMMARIZE_TRIGGER = 12

# 摘要最大长度（字符数，超出后压缩）
SUMMARY_MAX_CHARS = 500

# 每次摘要取最旧的消息数
SUMMARIZE_BATCH_SIZE = 8

# 摘要 Prompt —— V3.1 结构化格式（区分事实/状态/互动）
SUMMARY_PROMPT = """\
请用以下结构化格式总结对话。每个字段一到两句。不超过150字。

【用户事实】对方明确提供的信息（如："对方说今天排练了""对方提到喜欢某物"）
【用户状态】对方当前的状态（如："对方今天很累""对方心情不错"）
【关系互动】对方在这段对话中的互动需求（如："对方希望有人听他说话"）

规则：
- 只描述对方。不描述 AI 说了什么、做了什么、表达了什么。
- AI 的陪伴性回应（如"我陪你""我在呢"）不要进入摘要。
- 如果 AI 说了"我陪你去"之类的话 → 这不是事实，是对话表达。不要写成"和AI一起去了某处"。
- 没有值得记录的内容就写"无"。
- 不要写完整句子。用短语。"""

# 压缩 Prompt —— V3.1 超长摘要合并（保持来源区分）
COMPRESS_PROMPT = """\
以下是两段对话摘要。请合并为一段，用同样的结构化格式：

【用户事实】（合并去重）
【用户状态】（主要状态）
【关系互动】（合并去重）

控制在200字以内。
规则同上：不描述 AI。不把对话表达转成事实。"""


class ConversationSummarizer:
    """对话摘要器。"""

    async def summarize(
        self,
        messages: list[dict[str, str]],
        existing_summary: str,
        provider,
    ) -> str:
        """将一批消息压缩为结构化摘要，并与已有摘要合并。

        Args:
            messages: 待摘要的消息列表
            existing_summary: 已有的累计摘要（首次为空字符串）
            provider: LLM Provider

        Returns:
            新的累计摘要
        """
        if not messages:
            return existing_summary

        # 构建对话文本
        conversation = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content'][:100]}"
            for m in messages
        )

        # 如果有已有摘要，合并模式
        if existing_summary:
            prompt = (
                f"已有摘要：\n{existing_summary}\n\n"
                f"新对话：\n{conversation}\n\n"
                f"请将以上合并为一段结构化摘要。控制在200字以内。"
            )
            system = COMPRESS_PROMPT
        else:
            prompt = conversation
            system = SUMMARY_PROMPT

        try:
            result = await provider.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=system,
            )
            summary = result.strip()
            logger.debug(f"对话摘要完成 ({len(summary)} 字)")
            return summary
        except Exception as e:
            logger.warning(f"对话摘要失败: {e}")
            return existing_summary
