# ============================================================
# 绘梨衣 AI Core - 常用命令
# ============================================================

.PHONY: help install dev test lint format run clean docker-build docker-up docker-down

help:  ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## 安装生产依赖
	uv sync --no-dev

dev:  ## 安装全部依赖（含开发工具）
	uv sync

test:  ## 运行测试
	uv run pytest -v

lint:  ## 代码检查
	uv run ruff check .

format:  ## 代码格式化
	uv run ruff format .

run:  ## 启动应用
	uv run python -m app.main

clean:  ## 清理临时文件
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov

docker-build:  ## 构建 Docker 镜像
	docker compose -f docker/docker-compose.yaml build

docker-up:  ## 启动 Docker 服务
	docker compose -f docker/docker-compose.yaml up -d

docker-down:  ## 停止 Docker 服务
	docker compose -f docker/docker-compose.yaml down
