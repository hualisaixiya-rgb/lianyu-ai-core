"""V4 Stage 0 行为基线捕获脚本。

在拆分前建立 V3.8.1 当前行为基线（scripts/baseline.json）。

设计：
- MockProvider：确定性 LLM（按 system_prompt 关键词返回固定响应），
  使所有 LLM 依赖路径在测试环境中结果确定，DB checksum 可重复。
- _create_background_task mock：后台任务入队，由调用方同步执行
  （不 sleep 等待，保持超时 + 静默失败语义）。
- 覆盖 3 个最小 case：普通聊天 / 身份确认 / 后台任务副作用。
- checksum：8 表按 id 排序，完整行内容 sha256。

用法：
    python scripts/baseline_capture.py
    python scripts/behavior_consistency_test.py   # 对比基线

不修改任何业务代码。
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ================================================================
# 数据库隔离 —— 必须在 import 任何项目模块之前
# （behavior_consistency_test.py 会先设置自己的 DATABASE_URL，
#   这里用条件设置允许外部覆盖）
# ================================================================
BASELINE_DB = "data/test_consistency_baseline.db"
VERIFY_DB = "data/test_consistency_verify.db"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{BASELINE_DB}"
if "APP_DEBUG" not in os.environ:
    os.environ["APP_DEBUG"] = "false"
if "APP_LOG_LEVEL" not in os.environ:
    os.environ["APP_LOG_LEVEL"] = "WARNING"

# ================================================================
# 项目模块（此时才 import）
# ================================================================
from sqlalchemy import text as sql_text

from database.engine import init_db
from database.session import AsyncSessionLocal
from ai.core import AICore, ChatContext
import ai.core as core_module
import archive.conversation_archive as _conversation_archive

# ================================================================
# 确定性 LLM 提供者
# ================================================================

# 后台任务调用队列（由 _sync_background_task 收集，调用方同步执行）
background_queue: list = []
background_calls: int = 0


class MockProvider:
    """确定性 LLM 提供者。

    按 system_prompt 关键词返回固定响应 —— 与真实 LLM 的随机性解耦，
    使 DB 终态完全确定，checksum 可跨运行重复。
    """

    model = "mock-deterministic"
    max_tokens = 64
    temperature = 0.0

    # (关键词, 固定响应) —— 按优先级匹配
    RESPONSES = [
        ("记忆提取", '{"profile_fields":{},"memories":[]}'),
        (
            "关系事件",
            # 注意 summary 必须 >= 10 字（relationship_store 生成阈值）
            '{"summary":"模拟关系事件摘要，今天用户分享了日常生活。","emotion":"平静",'
            '"relationship_meaning":"测试","topic":"测试","importance":5}',
        ),
        ("总结", "这是一段超过二十个字的模拟对话摘要，记录了今天用户聊天的内容。嗯。"),
        ("合并", "这是一段超过二十个字的模拟对话摘要，记录了今天用户聊天的内容。嗯。"),
        ("提炼", '{"category":"understanding","content":"模拟关系理解","importance":5,"confidence":5}'),
        ("状态提取", '{"location":"","activity":"","temperature_feeling":"","sky":"","wind":"","user_mood":"","crowd":""}'),
    ]
    DEFAULT_REPLY = "嗯……好的。"

    async def chat(self, messages, system_prompt=None):
        sp = system_prompt or ""
        for keyword, resp in self.RESPONSES:
            if keyword in sp:
                return resp
        return self.DEFAULT_REPLY


def _sync_background_task(coro, timeout: float = 30.0):
    """测试环境：后台任务入队，由调用方同步执行。

    保持生产语义：
    - 超时（30s）→ 静默取消
    - 异常 → 静默（不污染主流程）
    - 返回 None：chat() 不依赖返回值
    """
    global background_calls
    background_calls += 1
    background_queue.append(coro)
    return None


# ================================================================
# checksum
# ================================================================

TABLES = [
    "users",
    "messages",
    "memory_records",
    "user_profiles",
    "profile_history",
    "relationship_metrics",
    "relationship_timeline",
    "relationship_memories",
]

# 排除时间戳列：created_at/updated_at 是运行环境固有差异（两次运行时间不同），
# first_chat_at/last_chat_at 依赖运行时刻 —— 均与拆分行为无关，不参与一致性对比。
# 业务列（total_chats/consecutive_days/name/status/summary 等）全部保留。
EXCLUDED_COLUMNS = {
    "created_at",
    "updated_at",
    "first_chat_at",
    "last_chat_at",
}


async def db_checksum() -> dict[str, str]:
    """8 表 checksum：按主键（id）排序，完整行内容 sha256（排除时间戳列）。"""
    checksums: dict[str, str] = {}
    async with AsyncSessionLocal.get_session() as session:
        for table in TABLES:
            result = await session.execute(
                sql_text(f"SELECT * FROM {table} ORDER BY id")
            )
            cols = [d[0] for d in result.cursor.description]
            rows = result.all()
            h = hashlib.sha256()
            for row in rows:
                values = [
                    v for i, v in enumerate(row) if cols[i] not in EXCLUDED_COLUMNS
                ]
                h.update(repr(tuple(values)).encode("utf-8"))
            checksums[table] = h.hexdigest()
    return checksums


# ================================================================
# 测试用例（第一阶段：3 个最小 case）
# ================================================================

CASES = {
    "case1_basic_chat": {
        "description": "普通聊天 — 验证基础状态写入",
        "inputs": [
            ("cc1-user", "你好"),
            ("cc1-user", "在吗"),
        ],
    },
    "case2_identity_flow": {
        "description": "身份声明/确认 — 验证 Step 6a pending→confirmed 同轮可见",
        "inputs": [
            ("cc2-user", "我叫测试员"),
            ("cc2-user", "对，就叫测试员"),
        ],
    },
    "case3_background_tasks": {
        "description": "后台任务 — 验证 summarize/timeline/consolidate 确定性副作用",
        # 8 轮：第 6 轮触发摘要（summary 落库），第 7 轮才触发 timeline（判断用旧 summary）
        "inputs": [
            ("cc3-user", "今天天气不错"),
            ("cc3-user", "我最近在学画画"),
            ("cc3-user", "画了一幅水彩画"),
            ("cc3-user", "好累啊"),
            ("cc3-user", "我想早点休息"),
            ("cc3-user", "晚安"),
            ("cc3-user", "明天还要排练"),
            ("cc3-user", "我先睡了"),
        ],
    },
}


# ================================================================
# 执行
# ================================================================

def _reset_db() -> None:
    """删除当前 DATABASE_URL 指向的数据库文件（全新环境）。"""
    url = os.environ["DATABASE_URL"]
    path = url.split("///", 1)[1]
    db_file = PROJECT_ROOT / path
    if db_file.exists():
        db_file.unlink()


def _git_meta() -> dict:
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"], cwd=PROJECT_ROOT, text=True
        ).strip()
        return {"commit": head, "tag": tag}
    except Exception:
        return {"commit": "unknown", "tag": "unknown"}


async def _drain_background() -> None:
    """同步执行所有排队后台任务（无 sleep）。保持超时 + 静默失败语义。"""
    while background_queue:
        coro = background_queue.pop(0)
        try:
            await asyncio.wait_for(coro, timeout=30.0)
        except asyncio.TimeoutError:
            pass  # 超时静默（与生产语义一致）
        except Exception:
            pass  # 异常静默（与生产语义一致）


async def execute_all() -> dict:
    """全新环境执行全部 case，返回完整结果（供 baseline 保存 / 一致性对比）。"""
    global background_calls, background_queue

    _reset_db()
    await init_db()

    # ---- 测试注入（不修改业务代码）----
    background_calls = 0
    background_queue = []
    core_module._create_background_task = _sync_background_task

    # 归档写文件屏蔽（避免污染 archives/）
    _conversation_archive.save = lambda *a, **k: None

    # Prompt spy（Case 2 同轮可见性验证）
    # 注意：_build_system_prompt 是同步方法（chat() 中无 await），spy 必须保持同步
    captured_prompts: list[dict] = []
    _orig_build = AICore._build_system_prompt

    def _spy_build(self, **kwargs):
        captured_prompts.append(
            {
                "profile_context": kwargs.get("profile_context", ""),
                "intent": kwargs.get("intent"),
            }
        )
        return _orig_build(self, **kwargs)

    AICore._build_system_prompt = _spy_build

    core = AICore(provider=MockProvider())

    results: dict = {}
    for case_name, case in CASES.items():
        responses = []
        for uid, msg in case["inputs"]:
            ctx = ChatContext(platform="test", platform_user_id=uid, message=msg)
            resp = await core.chat(ctx)
            await _drain_background()
            responses.append(
                {
                    "input": msg,
                    # 不保存随机 LLM 内容 —— 只保存确定性 metadata
                    "memory_updated": resp.memory_updated,
                }
            )

        checksums = await db_checksum()
        assertions = await _run_assertions(case_name, core, captured_prompts)

        results[case_name] = {
            "description": case["description"],
            "inputs": [i[1] for i in case["inputs"]],
            "responses": responses,
            "checksums": checksums,
            "assertions": assertions,
            "background_calls_at_end": background_calls,
        }

    return {
        "meta": {
            "tag": _git_meta()["tag"],
            "commit": _git_meta()["commit"],
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "provider": "mock-deterministic",
            "background": "sync-executed",
        },
        "cases": results,
    }


async def _run_assertions(case_name: str, core: AICore, captured_prompts: list[dict]) -> dict:
    """每个 case 的业务断言。返回 {断言名: 是否通过}。"""
    checksums = await db_checksum()
    assertions: dict = {}

    async with AsyncSessionLocal.get_session() as session:
        if case_name == "case1_basic_chat":
            users = (
                await session.execute(sql_text("SELECT COUNT(*) FROM users"))
            ).scalar()
            messages = (
                await session.execute(sql_text("SELECT COUNT(*) FROM messages"))
            ).scalar()
            metrics = (
                await session.execute(
                    sql_text(
                        "SELECT total_chats FROM relationship_metrics "
                        "WHERE platform_user_id='cc1-user'"
                    )
                )
            ).scalar()
            assertions["users==1"] = users == 1
            assertions["messages==4"] = messages == 4
            assertions["metrics_total_chats==2"] = metrics == 2

        elif case_name == "case2_identity_flow":
            hist = (
                await session.execute(
                    sql_text(
                        "SELECT status FROM profile_history "
                        "WHERE platform_user_id='cc2-user'"
                    )
                )
            ).all()
            profile = (
                await session.execute(
                    sql_text(
                        "SELECT name FROM user_profiles "
                        "WHERE platform_user_id='cc2-user'"
                    )
                )
            ).scalar()
            assertions["profile_history_1_confirmed"] = (
                len(hist) == 1 and hist[0][0] == "confirmed"
            )
            assertions["user_profiles_name==测试员"] = profile == "测试员"

            # 同轮可见性：第二轮（确认轮）build_prompt 的 profile_context 含名字
            second_turn = captured_prompts[-1]
            assertions["same_turn_name_visible"] = (
                "测试员" in second_turn.get("profile_context", "")
            )

        elif case_name == "case3_background_tasks":
            messages = (
                await session.execute(
                    sql_text(
                        "SELECT COUNT(*) FROM messages "
                        "WHERE platform_user_id='cc3-user'"
                    )
                )
            ).scalar()
            metrics = (
                await session.execute(
                    sql_text(
                        "SELECT total_chats FROM relationship_metrics "
                        "WHERE platform_user_id='cc3-user'"
                    )
                )
            ).scalar()
            timeline = (
                await session.execute(
                    sql_text(
                        "SELECT COUNT(*) FROM relationship_timeline "
                        "WHERE platform_user_id='cc3-user'"
                    )
                )
            ).scalar()
            rel_mem = (
                await session.execute(
                    sql_text(
                        "SELECT COUNT(*) FROM relationship_memories "
                        "WHERE platform_user_id='cc3-user'"
                    )
                )
            ).scalar()
            assertions["messages==16"] = messages == 16
            assertions["metrics_total_chats==8"] = metrics == 8
            assertions["timeline==1"] = timeline == 1
            # 记录真实行为：generate_timeline_if_needed 返回 None（无 return），
            # consolidate 链路（rel_memories 写入）当前不触发 —— 拆后若被错误触发，checksum 会暴露
            assertions["rel_memories==0"] = rel_mem == 0

            # 摘要副作用：内存 summary 被更新（>20 字）
            session_obj = core._sessions.get("test:cc3-user")
            assertions["summary_updated"] = bool(
                session_obj and len(session_obj.summary) > 20
            )

            # 后台任务触发计数（全局累计，确定性）：
            #   case1 (2 轮): 2 extract                          = 2
            #   case2 (2 轮): 2 extract                          = 2
            #   case3 (8 轮): 8 extract + 1 summarize
            #                 + 2 timeline + 2 growth           = 13
            #   （consolidate 不触发 —— generate_timeline_if_needed 无 return）
            #   合计 = 17
            assertions["background_calls==17"] = background_calls == 17

    return assertions


async def main() -> None:
    result = await execute_all()
    out = PROJECT_ROOT / "scripts" / "baseline.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[baseline_capture] tag={result['meta']['tag']} commit={result['meta']['commit'][:8]}")
    all_pass = True
    for case_name, case in result["cases"].items():
        passed = all(case["assertions"].values())
        all_pass = all_pass and passed
        print(
            f"  {case_name}: {'PASS' if passed else 'FAIL'} "
            f"({sum(case['assertions'].values())}/{len(case['assertions'])} assertions)"
        )
        if not passed:
            for k, v in case["assertions"].items():
                if not v:
                    print(f"    - {k}")
    print(f"[baseline_capture] {'ALL PASS' if all_pass else 'FAILED'} -> baseline.json saved")
    if not all_pass:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
