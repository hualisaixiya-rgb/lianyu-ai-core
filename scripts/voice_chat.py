#!/usr/bin/env python
"""语音对话系统 —— Voice Chat。

流程：录音 → 语音识别 → AICore.chat() → 语音合成 → 播放

使用方式：
    uv run python scripts/voice_chat.py

依赖安装：
    uv sync                           # 基础依赖
    uv pip install faster-whisper sounddevice soundfile pydub edge-tts numpy

按键：
    Enter  - 开始 5 秒录音
    q+Enter - 退出
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.core import AICore, ChatContext
from config.settings import get_settings
from database.engine import init_db
from voice.recorder import Recorder
from voice.stt import WhisperSTT
from voice.tts import create_tts
from voice.player import play_audio
from utils.logger import setup_logger, get_logger
from utils.response_renderer import render_for_tts


# 输出目录
OUTPUT_DIR = Path("data/voice")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def print_banner():
    """打印欢迎信息。"""
    settings = get_settings()
    print()
    print("=" * 50)
    print("  绘梨衣 AI Core - 语音对话模式")
    print("=" * 50)
    print(f"  模型: {settings.ai.model}")
    print(f"  STT: faster-whisper (small)")
    print(f"  TTS: GPT-SoVITS (音色克隆) → EdgeTTS fallback")
    print()
    print("  [Enter] 开始录音（5秒）")
    print("  [q + Enter] 退出")
    print("=" * 50)
    print()


async def main():
    """主函数：语音对话循环。"""
    setup_logger("WARNING")
    logger = get_logger()

    settings = get_settings()
    if not settings.ai.api_key or settings.ai.api_key == "sk-placeholder-key":
        print("错误：请先在 .env 中配置 AI_LLM_API_KEY")
        sys.exit(1)

    # 初始化数据库
    await init_db()

    # 初始化组件
    print("初始化中...")
    core = AICore()
    stt = WhisperSTT(model_size="small", device="cpu", compute_type="int8")
    tts = create_tts(backend="auto")  # edge → sapi 自动降级
    recorder = Recorder()
    print("初始化完成！")
    print_banner()

    turn = 0
    while True:
        # 等待用户按键
        try:
            cmd = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if cmd == "q":
            print("再见！")
            break
        if cmd != "":
            # 非空非 q → 当作文本输入
            text = cmd
        else:
            # Enter → 录音
            print("\n[录音中... 请说话]")
            audio_path = OUTPUT_DIR / f"input_{turn:03d}.wav"
            recorder.record_to_file(audio_path, duration=5)

            # STT
            print("[识别中...]")
            text = stt.transcribe(audio_path)
            if not text:
                print("[未识别到语音，请重试]")
                continue
            print(f"你说: {text}")

        # 调用 AI Core（复用现有聊天逻辑）
        print("[思考中...]")
        ctx = ChatContext(
            platform="voice",
            platform_user_id="voice-user",
            message=text,
            username="voice-user",
        )
        response = await core.chat(ctx)

        print(f"绘梨衣: {response.content}")

        # TTS（先清洗括号内容，避免朗读动作描写）
        print("[合成语音...]")
        clean_text = render_for_tts(response.content)
        output_path = OUTPUT_DIR / f"output_{turn:03d}.mp3"
        await tts.synthesize(clean_text, output_path)

        # 播放（SAPI 自己播放，不需要外部播放器）
        if tts.needs_playback:
            play_audio(output_path)

        turn += 1
        print()


if __name__ == "__main__":
    asyncio.run(main())
