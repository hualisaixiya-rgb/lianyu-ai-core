"""多模态输出分层系统。

将 AICore.chat() 的原始输出与"展示方式"彻底解耦。
不同终端使用不同的渲染函数，AI 核心逻辑不受任何影响。

V4 Stage 0.5 Expression Layer：新增 render_for_user（最终用户可见输出），
对句首省略号循环 / 多行模板化 / 相邻句重复 / 长度膨胀 4 类格式漂移做规范化。

用法：
    from utils.response_renderer import render_for_cli, render_for_tts, render_for_user

    response = await core.chat(ctx)

    # CLI / Telegram 保留完整人格
    print(render_for_cli(response.content))

    # 最终用户可见输出（Telegram / API）—— 修复格式漂移
    send(render_for_user(response.content))

    # Voice TTS 去除括号内容
    tts.speak(render_for_tts(response.content))
"""

import re

from ai.expression import apply_expression, infer_spec, collapse_lines, dedup_adjacent_sentences, normalize_ellipsis_prefix

# render_for_storage 允许的最大行数（最宽松档，只拦极端模板化）
_STORAGE_MAX_LINES = 4


def render_for_user(text: str, user_msg: str | None = None) -> str:
    """用户可见输出渲染（Telegram / API / 其他前端）。

    应用表达层全部规则（按内容 + 用户消息上下文推断 chat/daily/emotion/deep 规格）：
    - Stage 0.5：句首省略号规范化 / 多行压缩 / 相邻句重复检测 / 最大长度保护
    - Stage 0.6 表达强度调节：
      * 用户轻量问候 → chat 档（删句首省略号，25 字/2 行收紧）
      * 用户高情绪 → 保留深情表达（不降档）
      * 普通输入 + 高浓度文学回复（意象堆叠/承诺式）→ deep 降 emotion 收紧

    只修复格式漂移与呈现强度，不改变人格与语义。正常输出幂等。
    不传 user_msg → 行为与 Stage 0.5 一致（向后兼容）。
    """
    return apply_expression(text, infer_spec(text, user_msg))


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

    V4 Stage 0.5 增加幂等规范化（句首省略号 / 多行模板化 / 相邻重复）：
    这些规则只改写"漂移输出"，对正常文本零影响，
    同时防止膨胀格式写回历史 → 从源头打破"输出表达层自强化循环"。
    注意：不含长度截断（超长回复的截断只发生在 render_for_user，不影响 DB 原始性）。

    Args:
        text: AICore.chat() 原始输出

    Returns:
        去除括号后的纯文本
    """
    text = re.sub(r"（[^）]*）", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = normalize_ellipsis_prefix(text)
    text = collapse_lines(text, _STORAGE_MAX_LINES)
    text = dedup_adjacent_sentences(text)
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
