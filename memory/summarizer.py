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

# 摘要 Prompt —— 结构化格式
SUMMARY_PROMPT = """\
请用以下结构化格式总结对话。每个字段一到两句。不超过150字。

事件：（你们聊了什么话题）
情绪：（对方情绪如何：平静/开心/难过/疲惫/兴奋/其他）
偏好：（对方提到的新偏好或习惯，没有就写"无"）
人物：（提到了谁，没有就写"无"）

不要写完整句子。用短语。
不要描述AI做了什么或说了什么。只描述用户。"""

# 压缩 Prompt —— 超长摘要合并
COMPRESS_PROMPT = """\
以下是两段对话摘要。请合并为一段，用同样的结构化格式：

事件：（合并话题）
情绪：（主要情绪）
偏好：（合并偏好，去重）
人物：（合并人物，去重）

控制在200字以内。"""


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
