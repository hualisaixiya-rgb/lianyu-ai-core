"""多模态输出分层系统。

将 AICore.chat() 的原始输出与"展示方式"彻底解耦。
不同终端使用不同的渲染函数，AI 核心逻辑不受任何影响。

用法：
    from utils.response_renderer import render_for_cli, render_for_tts

    response = await core.chat(ctx)

    # CLI / Telegram 保留完整人格
    print(render_for_cli(response.content))

    # Voice TTS 去除括号内容
    tts.speak(render_for_tts(response.content))
"""

import re


def render_for_cli(text: str) -> str:
    """CLI / Telegram 渲染：原样返回，保留完整人格输出。

    Args:
        text: AICore.chat() 原始输出

    Returns:
        原样文本
    """
    return text


def render_for_tts(text: str) -> str:
    """Voice TTS 渲染：去除括号内容，适合语音朗读。

    - 删除中文全角括号及内容：（...）
    - 删除英文半角括号及内容：(...)
    - 清理多余空格

    Args:
        text: AICore.chat() 原始输出

    Returns:
        净化后的纯朗读文本
    """
    text = re.sub(r"（[^）]*）", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def render_for_storage(text: str) -> str:
    """数据库存储渲染：去除括号后保存。

    括号动作描写进入 DB → 下次加载为历史上下文 →
    模型看到括号风格 → 继续生成括号 → 形成不可控的自循环。
    此函数在保存前清洗，打破循环。

    Args:
        text: AICore.chat() 原始输出

    Returns:
        去除括号后的纯文本
    """
    text = re.sub(r"（[^）]*）", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_for_api(text: str) -> dict[str, str]:
    """API 渲染：返回所有格式，供前端选择。

    Args:
        text: AICore.chat() 原始输出

    Returns:
        {"raw": ..., "cli": ..., "tts": ...}
    """
    return {
        "raw": text,
        "cli": render_for_cli(text),
        "tts": render_for_tts(text),
    }
