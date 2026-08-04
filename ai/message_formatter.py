"""用户消息格式化模块。

V4 Stage 0 Phase A2：从 ai/core.py 纯搬移，行为 100% 一致。

格式化发送给 LLM 的用户消息。当用户引用回复了机器人的某条消息时，
将被引用内容作为前缀注入，帮助模型理解"用户正在回复哪句话"。

注意：使用 duck typing（不 import ChatContext），避免与 ai/core.py 循环依赖。
"""


def format_user_message(context) -> str:
    """格式化发送给 LLM 的用户消息。

    当用户引用回复了机器人的某条消息时，
    将被引用内容作为前缀注入，
    帮助模型理解"用户正在回复哪句话"。

    Args:
        context: 聊天上下文（需要 reply_to_message / message 属性）

    Returns:
        格式化后的用户消息（可能含引用前缀）
    """
    if not context.reply_to_message:
        return context.message

    # 格式：[用户正在回复你之前说的这段话]\n「被引用内容」\n[用户接着问]\n<当前消息>
    quoted = context.reply_to_message.strip()
    return (
        f"[用户正在回复你之前说的这段话]\n"
        f"绘梨衣：「{quoted}」\n"
        f"[用户接着问]\n"
        f"{context.message}"
    )
