"""Voice Chat 语音对话模块。

独立于 Telegram / CLI，提供语音交互能力。

流程：录音 → STT → AICore.chat() → TTS → 播放
"""
