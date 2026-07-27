"""读图工具。

读取图片文件，调用视觉模型分析图片内容，返回文字描述。
原理：
  1. 图片 base64 编码
  2. 调用纯视觉模型（如 GPT-4V / GPT-4o-mini）
  3. 结果发回给主模型使用

由于主聊天模型（如 DeepSeek）可能不支持视觉输入，
本工具使用独立的视觉模型配置（VISION_* 环境变量）。

使用方式：
    result = await read_image(image_path="screenshot.png")
    result = await read_image(image_path="photo.jpg", question="图中有几个人？")
"""

import base64
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from loguru import logger

from config.settings import get_settings


# 支持的图片格式及其 MIME 类型
_MIME_MAP: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _get_mime_type(path: Path) -> str:
    """根据文件扩展名获取 MIME 类型。

    Args:
        path: 图片文件路径

    Returns:
        对应的 MIME 类型字符串

    Raises:
        ValueError: 不支持的图片格式
    """
    suffix = path.suffix.lower()
    if suffix not in _MIME_MAP:
        raise ValueError(
            f"不支持的图片格式: {suffix}，"
            f"支持的格式: {list(_MIME_MAP.keys())}"
        )
    return _MIME_MAP[suffix]


def _encode_image(path: Path) -> str:
    """将图片文件编码为 base64 字符串。

    直接读取文件二进制内容并编码，不做额外处理。

    Args:
        path: 图片文件路径

    Returns:
        base64 编码后的字符串
    """
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def read_image(
    image_path: str,
    question: Optional[str] = None,
) -> str:
    """读取并分析图片内容。

    将图片编码为 base64 后发送给视觉模型进行分析，
    返回模型对图片的文字描述。主模型可通过工具调用获取此描述，
    从而间接获得"看图"能力。

    Args:
        image_path: 图片文件路径（支持绝对路径和相对路径）
        question: 针对图片的具体问题。不传则让模型自由描述图片内容。

    Returns:
        视觉模型对图片的分析结果（纯文本）

    Raises:
        FileNotFoundError: 图片文件不存在
        ValueError: 图片格式不支持，或视觉模型 API Key 未配置
        RuntimeError: 视觉模型 API 调用失败
    """
    settings = get_settings()
    vision_config = settings.vision

    # 检查视觉模型 API Key
    if not vision_config.api_key:
        raise ValueError(
            "视觉模型 API Key 未配置。"
            "请在 .env 中设置 VISION_API_KEY=你的key"
        )

    # 解析并验证图片路径
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"图片文件不存在: {path}")
    if not path.is_file():
        raise ValueError(f"路径不是文件: {path}")

    # 获取 MIME 类型
    mime_type = _get_mime_type(path)

    # 图片 base64 编码
    logger.info(f"[read_image] 正在编码图片: {path}")
    base64_image = _encode_image(path)
    logger.info(
        f"[read_image] 图片编码完成，base64 长度: {len(base64_image)} 字符"
    )

    # 构造视觉模型请求
    prompt = question or "请详细描述这张图片的内容。"

    # 使用独立的视觉模型客户端（与主聊天模型分离）
    client = AsyncOpenAI(
        base_url=vision_config.base_url,
        api_key=vision_config.api_key,
    )

    messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64_image}",
                    },
                },
            ],
        }
    ]

    try:
        logger.info(
            f"[read_image] 正在调用视觉模型: {vision_config.model}"
        )
        response = await client.chat.completions.create(
            model=vision_config.model,
            messages=messages,
            max_tokens=vision_config.max_tokens,
        )
        result = response.choices[0].message.content or ""
        logger.info(f"[read_image] 视觉模型返回: {len(result)} 字符")
        return result

    except Exception as e:
        raise RuntimeError(f"视觉模型调用失败: {e}") from e
