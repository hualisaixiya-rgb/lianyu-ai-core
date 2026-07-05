#!/usr/bin/env python
"""命令行聊天测试脚本。

在终端直接与 AI 对话，用于验证 LLM 连接和对话流程。
不依赖任何 Adapter，直接调用 AICore。

使用方式：
    uv run python scripts/chat_cli.py

内置命令：
    /clear   - 清除当前对话历史
    /history - 显示当前对话历史
    /db      - 查看数据库状态
    /reload  - 从数据库重新加载历史
    /exit    - 退出程序
    /help    - 显示帮助
"""

import asyncio
import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.core import AICore, ChatContext
from config.settings import get_settings
from database.engine import init_db
from database.repository import MessageRepository
from utils.logger import setup_logger
from loguru import logger


# 终端颜色代码（Windows 也支持）
class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_banner() -> None:
    """打印欢迎横幅。"""
    settings = get_settings()
    print()
    print(f"{Colors.CYAN}{'=' * 50}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.MAGENTA}  绘梨衣 AI Core - 命令行聊天测试{Colors.RESET}")
    print(f"{Colors.CYAN}{'=' * 50}{Colors.RESET}")
    print(f"  模型: {Colors.GREEN}{settings.ai.model}{Colors.RESET}")
    print(f"  地址: {Colors.GREEN}{settings.ai.base_url}{Colors.RESET}")
    print(f"  数据库: {Colors.GREEN}{settings.database.url}{Colors.RESET}")
    print(f"  角色: {Colors.GREEN}{settings.character.name}{Colors.RESET}")
    print()
    print(f"  {Colors.YELLOW}输入消息开始聊天{Colors.RESET}")
    print(f"  {Colors.YELLOW}/clear 清除  /history 历史  /db 状态{Colors.RESET}")
    print(f"  {Colors.YELLOW}/reload 重载  /exit 退出  /help 帮助{Colors.RESET}")
    print(f"{Colors.CYAN}{'=' * 50}{Colors.RESET}")
    print()


async def handle_command(core: AICore, user_id: str, command: str) -> bool:
    """处理内置命令。

    Args:
        core: AI Core 实例
        user_id: 用户 ID
        command: 命令字符串（不含 / 前缀）

    Returns:
        True 表示应该退出程序
    """
    cmd = command.strip().lower()

    if cmd in ("exit", "quit"):
        print(f"\n{Colors.YELLOW}再见！{Colors.RESET}\n")
        return True

    elif cmd == "clear":
        await core.clear_session("cli", user_id)
        print(f"{Colors.GREEN}✓ 对话历史已清除（重新加载将从清除后的记录开始）{Colors.RESET}\n")
        return False

    elif cmd == "history":
        history = core.get_history("cli", user_id)
        if not history:
            print(f"{Colors.YELLOW}暂无对话历史{Colors.RESET}\n")
        else:
            print(f"\n{Colors.CYAN}--- 对话历史 ({len(history)} 条) ---{Colors.RESET}")
            for i, msg in enumerate(history, 1):
                role = "👤 你" if msg["role"] == "user" else "🤖 AI"
                content = msg["content"].replace("\n", "\n    ")
                # 截断过长的消息
                if len(content) > 120:
                    content = content[:120] + "..."
                print(f"  {i}. {role}: {content}")
            print(f"{Colors.CYAN}--- 结束 ---{Colors.RESET}\n")
        return False

    elif cmd == "db":
        count = await MessageRepository.count_messages("cli", user_id)
        print(f"\n{Colors.CYAN}--- 数据库状态 ---{Colors.RESET}")
        print(f"  平台: cli")
        print(f"  用户: {user_id}")
        print(f"  数据库消息数: {count} 条")
        print(f"  内存缓存消息数: {len(core.get_history('cli', user_id))} 条")
        settings = get_settings()
        print(f"  数据库路径: {settings.database.url}")
        print(f"{Colors.CYAN}--- 结束 ---{Colors.RESET}\n")
        return False

    elif cmd == "reload":
        history = await core.reload_history("cli", user_id)
        print(f"{Colors.GREEN}✓ 已从数据库重新加载 {len(history)} 条历史消息{Colors.RESET}\n")
        return False

    elif cmd == "help":
        print(f"""
{Colors.CYAN}可用命令：{Colors.RESET}
  /clear   - 清除对话历史（开始新话题）
  /history - 显示当前对话历史
  /db      - 查看数据库状态
  /reload  - 从数据库重新加载历史
  /exit    - 退出程序
  /help    - 显示此帮助

{Colors.CYAN}提示：{Colors.RESET}
  聊天记录会自动保存到 SQLite 数据库。
  重启程序后，首次聊天会自动恢复历史。
  输入 /db 可以查看数据库中保存的消息数。
""")
        return False

    else:
        print(f"{Colors.RED}未知命令: /{cmd}，输入 /help 查看帮助{Colors.RESET}\n")
        return False


async def main() -> None:
    """主函数：启动命令行聊天循环。"""
    # 初始化日志（只显示 WARNING 以上）
    setup_logger("WARNING")

    settings = get_settings()
    if not settings.ai.api_key or settings.ai.api_key == "sk-placeholder-key":
        print(f"{Colors.RED}错误：请先在 .env 文件中配置 AI_LLM_API_KEY{Colors.RESET}")
        sys.exit(1)

    # 初始化数据库（自动创建表）
    try:
        await init_db()
        print(f"{Colors.GREEN}✓ 数据库已初始化{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}数据库初始化失败: {e}{Colors.RESET}")
        sys.exit(1)

    # 初始化 AI Core
    try:
        core = AICore()
    except Exception as e:
        logger.error(f"初始化 AI Core 失败: {e}")
        print(f"{Colors.RED}初始化失败: {e}{Colors.RESET}")
        sys.exit(1)

    print_banner()

    user_id = "cli-user"
    """CLI 固定用户 ID"""

    # 检查是否有历史消息，提示用户
    existing_count = await MessageRepository.count_messages("cli", user_id)
    if existing_count > 0:
        print(f"{Colors.YELLOW}📋 发现 {existing_count} 条历史消息，首次聊天将自动加载{Colors.RESET}\n")

    # 聊天循环
    while True:
        try:
            user_input = input(f"{Colors.BOLD}{Colors.GREEN}你: {Colors.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Colors.YELLOW}再见！{Colors.RESET}\n")
            break

        if not user_input:
            continue

        # 处理命令
        if user_input.startswith("/"):
            should_exit = await handle_command(core, user_id, user_input[1:])
            if should_exit:
                break
            continue

        # 构造上下文并发送给 AI Core
        context = ChatContext(
            platform="cli",
            platform_user_id=user_id,
            message=user_input,
            username="cli-user",
        )

        # 显示等待状态
        print(f"{Colors.YELLOW}🤖 思考中...{Colors.RESET}", end="\r")

        try:
            response = await core.chat(context)
            # 清除"思考中..."行，打印回复
            print(f"{' ' * 30}", end="\r")
            print(f"{Colors.BOLD}{Colors.CYAN}AI: {Colors.RESET}{response.content}")
            print()
        except Exception as e:
            logger.error(f"聊天异常: {e}")
            print(f"{Colors.RED}错误: {e}{Colors.RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
