@echo off
cd /d "E:\Visual Studio Code文件\lianyu-ai-core"
echo 安装全部依赖...
uv sync --group voice
echo.
echo 完成！
pause
