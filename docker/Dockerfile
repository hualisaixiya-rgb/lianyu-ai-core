# ============================================================
# 绘梨衣 AI Core - Docker 镜像
# ============================================================

FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install uv

# 复制依赖文件
COPY pyproject.toml .

# 安装 Python 依赖
RUN uv sync --no-dev

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data /app/logs

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "app.main"]
