@echo off
echo ============================================================
echo  GPT-SoVITS 独立环境安装指南
echo ============================================================
echo.
echo  GPT-SoVITS 运行在独立的 conda 环境中，不会影响当前项目。
echo.
echo  步骤：
echo.
echo  1. 安装 Miniconda（如未安装）：
echo     https://docs.conda.io/en/latest/miniconda.html
echo.
echo  2. 创建独立环境（在项目目录外）：
echo     conda create -n gptsovits python=3.10 -y
echo     conda activate gptsovits
echo.
echo  3. 克隆 GPT-SoVITS：
echo     git clone https://github.com/RVC-Boss/GPT-SoVITS.git C:\GPT-SoVITS
echo     cd C:\GPT-SoVITS
echo.
echo  4. 安装依赖：
echo     pip install -r requirements.txt
echo.
echo  5. 下载预训练模型（按官方文档）：
echo     放入 GPT_SoVITS/pretrained_models/
echo.
echo  6. 启动 API 服务：
echo     python api_v2.py
echo     （默认监听 http://localhost:9880）
echo.
echo  7. 准备参考音频：
echo     将不同情绪的干净人声 WAV（2-8秒，22050Hz mono）
echo     放入本项目 voice/gptsovits/ 目录：
echo       speaker_neutral.wav
echo       speaker_happy.wav
echo       speaker_sad.wav
echo       speaker_calm.wav
echo.
echo  8. 配置 .env：
echo     TTS_GPTSOVITS_URL=http://localhost:9880
echo.
echo  9. 启动语音聊天：
echo     双击 run_voice.bat
echo     （自动使用 GPT-SoVITS，不可用时降级到 EdgeTTS）
echo.
echo ============================================================
echo  当前项目不受任何影响。GPT-SoVITS 是独立服务。
echo ============================================================
pause
