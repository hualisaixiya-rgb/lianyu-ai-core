#!/usr/bin/env python
"""XTTS 测试脚本 —— 输入文字试听，不需要启动整个聊天程序。

用法:
    uv run python scripts/test_xtts.py                          # 自动选择 TTS
    uv run python scripts/test_xtts.py --text "你好，我是绘梨衣"  # 自定义文本
    uv run python scripts/test_xtts.py --backend edge            # 强制使用 EdgeTTS
    uv run python scripts/test_xtts.py --backend xtts --speaker voice/erii.wav
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.tts import create_tts
from voice.player import play_audio
from utils.logger import setup_logger

DEFAULT_TEXT = "你好。我是绘梨衣。今天天气很好。"


async def main():
    parser = argparse.ArgumentParser(description="XTTS 测试")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="要合成的文本")
    parser.add_argument("--backend", default="auto", help="TTS 后端: auto/xtts/edge/sapi")
    parser.add_argument("--speaker", default="", help="XTTS speaker_wav 路径")
    parser.add_argument("--output", default="data/voice/test_output.wav", help="输出文件路径")
    args = parser.parse_args()

    setup_logger("INFO")

    print(f"文本: {args.text}")
    print(f"后端: {args.backend}")
    print()

    # 创建 TTS
    kwargs = {}
    if args.speaker:
        kwargs["speaker_wav"] = args.speaker
    tts = create_tts(backend=args.backend, **kwargs)

    # 合成
    print("合成中...")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await tts.synthesize(args.text, str(output_path))

    # 播放
    if tts.needs_playback:
        print(f"播放: {output_path}")
        play_audio(output_path)
    else:
        print("TTS 已直接朗读")

    print("完成！")


if __name__ == "__main__":
    asyncio.run(main())
