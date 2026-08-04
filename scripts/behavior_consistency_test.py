"""V4 Stage 0 行为一致性测试。

与 scripts/baseline.json 对比当前行为：
- 8 表 DB checksum 100% 一致（硬指标）
- 每个 case 的业务断言全部通过
- memory_updated metadata 一致

用法（先运行 baseline_capture.py 建立基线）：
    python scripts/baseline_capture.py
    python scripts/behavior_consistency_test.py

不修改任何业务代码。
"""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---- 数据库隔离：使用独立验证库（在 import baseline_capture 之前设置）----
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///data/test_consistency_verify.db"
os.environ["APP_DEBUG"] = "false"
os.environ["APP_LOG_LEVEL"] = "WARNING"

from baseline_capture import execute_all  # noqa: E402


def main() -> int:
    baseline_path = PROJECT_ROOT / "scripts" / "baseline.json"
    if not baseline_path.exists():
        print("[consistency] baseline.json 不存在 —— 先运行 scripts/baseline_capture.py")
        return 1

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = asyncio.run(execute_all())

    print(
        f"[consistency] baseline tag={baseline['meta']['tag']} "
        f"commit={baseline['meta']['commit'][:8]}"
    )
    print(
        f"[consistency] current  tag={current['meta']['tag']} "
        f"commit={current['meta']['commit'][:8]}"
    )

    failures: list[str] = []

    for case_name in baseline["cases"]:
        if case_name not in current["cases"]:
            failures.append(f"{case_name}: 缺失")
            continue

        base = baseline["cases"][case_name]
        curr = current["cases"][case_name]

        # 1. DB checksum（硬指标）
        for table, base_cs in base["checksums"].items():
            curr_cs = curr["checksums"].get(table)
            if curr_cs != base_cs:
                failures.append(f"{case_name}/{table}: checksum 不一致")

        # 2. 业务断言
        for name, passed in curr["assertions"].items():
            if not passed:
                failures.append(f"{case_name}/{name}: 断言失败")

        # 3. memory_updated metadata
        base_meta = [(r["input"], r["memory_updated"]) for r in base["responses"]]
        curr_meta = [(r["input"], r["memory_updated"]) for r in curr["responses"]]
        if base_meta != curr_meta:
            failures.append(f"{case_name}: memory_updated metadata 不一致")

    if failures:
        print(f"[consistency] FAIL — {len(failures)} 项不一致:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("[consistency] ALL PASS — 行为与 baseline 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
