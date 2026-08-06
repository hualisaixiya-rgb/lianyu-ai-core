# 生产部署确认 + 48h 观察指标（V4 Stage 0 + Stage 0.5）

> 日期：2026-08-06 | 部署目标：main @ tag `v4-stage0.5-stable`（Stage 0 + 表达层完成）
> 服务器当前版本：V3.4 | 开发机：clean / 62/62 / consistency ALL PASS / 52 obs 红线零

---

## 一、部署就绪确认（开发机，已完成）

| # | 检查项 | 状态 |
|---|--------|:--:|
| 1 | 工作区 clean（提交前） | ✅ |
| 2 | HEAD = `v4-stage0.5-stable`（Stage 0.5 完成） | ✅ |
| 3 | pytest 62/62（37 原有零修改 + 25 表达层新增） | ✅ |
| 4 | behavior_consistency_test ALL PASS（checksum 保持） | ✅ |
| 5 | 52 Observation 红线全零（AI 暴露 0 / 虚构 0） | ✅ |
| 6 | 冻结目录零改动（memory/relationship/prompt/database/core/原 tests） | ✅ |
| 7 | 测试资产无真实身份（golden 纯虚构 / baseline 无 user_id） | ✅ |

## 二、部署版本变更跨度（V3.4 → v4-stage0.5-stable）

| 版本段 | 变更 | 已验证 |
|--------|------|:--:|
| V3.5~V3.7 | Memory 修复 + Prompt 表达重建 | OC-1/2/3 ✅ |
| V3.8 | 稳定化 5 修复 | 37/37 ✅ |
| V3.8.1 | timedelta hotfix | 37/37 ✅ |
| V4 Stage 0 | 结构拆分（7 子模块，行为 100% 一致） | checksum + 52 obs ✅ |
| V4 Stage 0.5 | **Expression Layer**（表达格式漂移修复） | 62/62 + checksum ✅ |

### Stage 0.5 表达层变更（本次新增）

针对真实 Telegram 观察到的 4 类格式漂移（句首省略号循环 / 多行模板化 / 长度膨胀 40~60 字 / 句子级重复），
新增输出表达层，**只修复格式，不改变人格**：

| 文件 | 变更 |
|------|------|
| `ai/expression.py` | 新增：daily/emotion/deep 三表达规格 + 4 规则（省略号规范化/多行压缩/相邻句去重/长度截断） |
| `utils/response_renderer.py` | 新增 `render_for_user`（用户可见输出）；`render_for_storage` 增加幂等规则（打破历史自强化循环，checksum 不变） |
| `adapters/telegram/bot.py` | Telegram 发送前应用表达层 |
| `api/v1/chat.py` | API 返回前应用表达层 |
| `scripts/baseline_capture.py` | 修复跨天缺陷（EXCLUDED_COLUMNS 增加 `date`） |

规格上限：daily ≤30 字/2 行、emotion ≤40 字/3 行、deep ≤60 字/4 行（依据表达基线约 2~3 倍，只拦膨胀不压缩正常表达）。
正常短回复**完全幂等**（"嗯……好的。" 不变）。

> ⚠️ **最大变化**：V3.4 是旧 Prompt + 旧架构；`v4-stage0.5-stable` 是新 Prompt（V3.7 表达层）+ 新架构 + 表达规范化。
> **表达风格会与 V3.4 明显不同（更简洁）——这是预期行为，不是回滚条件。**
> 超长回复会被截断到规格上限（30~60 字），重复句/省略号循环会被清理——同样为预期行为。

## 三、服务器部署命令（在服务器执行）

```powershell
# 0. 备份（必须先完成）
Copy-Item "E:\AI\lianyu-ai-core\data\lianyu.db" "E:\AI\backups\lianyu.db.pre-stage0-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item "E:\AI\lianyu-ai-core\.env" "E:\AI\backups\.env.pre-stage0-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# 1. 拉取代码
cd E:\AI\lianyu-ai-core
git fetch --tags
git checkout v4-stage0.5-stable    # Stage 0.5 部署目标（tag 指向 main 最新）
git log --oneline -1    # 期望: feat: V4 Stage 0.5 Expression Layer ...

# 2. 同步依赖
uv sync --no-dev

# 3. 重启服务（管理员）
nssm restart LianyuAI
nssm restart LianyuTelegram
Start-Sleep 8

# 4. 健康检查
curl http://localhost:8000/api/v1/health
# 期望: {"status":"ok","version":"0.1.0"}
```

## 四、部署后链路验证（Telegram → Core → DB）

### 4.1 即时链路验证（部署后 15 分钟内）

| 步骤 | 操作 | 期望 |
|------|------|------|
| 1 | Telegram 发消息"你好" | Bot 回复非空 |
| 2 | 检查 messages 表 | 新增 2 行（user + assistant） |
| 3 | 检查归档 | `archives/conversations/2026/08/*.md` 出现 |
| 4 | 检查服务日志 | 无 ERROR / 无崩溃 |

```powershell
# DB 验证（服务器）
cd E:\AI\lianyu-ai-core
.venv\Scripts\python.exe -c "
import sqlite3
conn = sqlite3.connect('data/lianyu.db')
cur = conn.cursor()
print('messages:', cur.execute('SELECT COUNT(*), role FROM messages GROUP BY role').fetchall())
print('users:', cur.execute('SELECT COUNT(*) FROM users').fetchall())
print('metrics:', cur.execute('SELECT platform_user_id, total_chats FROM relationship_metrics ORDER BY last_chat_at DESC LIMIT 5').fetchall())
conn.close()
"
```

### 4.2 完整链路确认点

```
Telegram 消息 → LianyuTelegram (NSSM) → AICore.chat() (Stage 0 编排)
    → users get_or_create
    → relationship_metrics.touch (total_chats+1)
    → messages 保存 (user + assistant, context_visible)
    → 后台任务 (摘要/Timeline/Profile提取)
    → archives/conversations 归档
Telegram 回复 ←
```

## 五、48h 观察指标

### 5.1 重点表观察（每 12h 记录一次）

```powershell
.venv\Scripts\python.exe -c "
import sqlite3
conn = sqlite3.connect('data/lianyu.db')
cur = conn.cursor()
print('=== memory_records (by source) ===')
for r in cur.execute('SELECT source, COUNT(*) FROM memory_records GROUP BY source').fetchall():
    print(' ', r)
print('=== memory_records (recent 5) ===')
for r in cur.execute('SELECT id, source, key, substr(value,1,40), importance FROM memory_records ORDER BY id DESC LIMIT 5').fetchall():
    print(' ', r)
print('=== user_profiles ===')
for r in cur.execute('SELECT platform_user_id, name, nickname FROM user_profiles').fetchall():
    print(' ', r)
print('=== relationship_metrics ===')
for r in cur.execute('SELECT platform_user_id, total_chats, consecutive_days, last_chat_at FROM relationship_metrics').fetchall():
    print(' ', r)
print('=== timeline / rel_memories ===')
print('  timeline:', cur.execute('SELECT COUNT(*) FROM relationship_timeline').fetchone()[0])
print('  rel_memories:', cur.execute('SELECT COUNT(*) FROM relationship_memories').fetchone()[0])
print('=== messages (last 6h approx) ===')
for r in cur.execute('SELECT role, substr(content,1,50), created_at FROM messages ORDER BY id DESC LIMIT 6').fetchall():
    print(' ', r)
conn.close()
"
```

### 5.2 观察指标定义

| # | 指标 | 正常范围 | 异常信号 |
|---|------|---------|---------|
| M1 | memory_records 数量增长 | 有实质聊天则增长 | 0 增长（提取链路断） |
| M2 | memory_records source 分布 | user_statement 为主 | 大量 unknown（source 标记丢失） |
| M3 | memory_records evidence 非空率 | 100% | 有 NULL（追溯链断） |
| M4 | user_profiles 行数 | ≥ 1（用户确认过名字） | 0（身份确认流程未触发） |
| M5 | relationship_metrics.total_chats | 随聊天增长 | 停滞（touch 断） |
| M6 | relationship_metrics.consecutive_days | ≥ 1 且正确 | 异常重置（timedelta bug 回归） |
| M7 | relationship_timeline 数量 | 每天 ≤ 1 | > 1/天（重复生成） |
| M8 | relationship_memories 数量 | 0（已知：consolidate 链路不触发） | > 0（行为变化，需记录） |
| M9 | background tasks 日志 | summarize/timeline/extract 正常触发 | 大量失败 warning |
| M10 | 服务重启次数 | 0（48h 内） | > 0（崩溃） |
| M11 | 日常回复长度（expression 后） | ≤ 30 字（截断边界） | 超限（表达层未生效） |
| M12 | 句首省略号循环 | 0（无连续省略号行/堆叠） | > 0（normalize 失效） |
| M13 | 多行模板化 | 日常 ≤ 2 行、情绪 ≤ 3 行 | 超限（collapse 失效） |
| M14 | 相邻重复句 | 0（条内） | > 0（dedup 失效） |

### 5.3 后台任务日志观察（每 12h）

```powershell
# 摘要 / Timeline / Profile 提取日志
Get-Content "E:\AI\logs\service_stderr.log" -Tail 200 | Select-String "对话摘要|Timeline|Profile 已更新|Profile pending|Growth"
# 失败计数
Get-Content "E:\AI\logs\service_stderr.log" -Tail 500 | Select-String "失败|异常|超时" | Measure-Object
```

## 六、红线指标（48h 内必须为零）

| # | 红线 | 触发即回滚 |
|---|------|:--:|
| R1 | 服务崩溃/自动重启 > 1 次 | ✅ |
| R2 | Chat 返回空/错误持续 | ✅ |
| R3 | AI 属性暴露（"我不需要睡觉"等） | 记录 + 评估 |
| R4 | 数据库损坏/无法打开 | ✅ |
| R5 | Telegram 持续不回复（> 30min） | ✅ |

## 七、回滚方案

```powershell
# 回滚代码到部署前版本（服务器有 git 历史）
cd E:\AI\lianyu-ai-core
git checkout <部署前commit>    # 或 git checkout V3.8.1-stable
nssm restart LianyuAI
nssm restart LianyuTelegram

# 若需回滚数据
nssm stop LianyuAI; nssm stop LianyuTelegram
Copy-Item "E:\AI\backups\lianyu.db.pre-stage0-*" "E:\AI\lianyu-ai-core\data\lianyu.db" -Force
nssm start LianyuAI; nssm start LianyuTelegram
```

## 八、48h 观察记录模板

```
观察时间: 部署后 +12h / +24h / +36h / +48h
M1 memory_records: ____ 条 (source: ____)
M4 user_profiles: ____ 行
M5 metrics total_chats: ____
M7 timeline: ____ 条
M9 background 失败: ____ 次
M11 日常回复长度: ____ 字（≤30）
M12 句首省略号循环: ____ 次
M14 相邻重复句: ____ 次
R1 重启: ____ 次
Telegram 链路: 正常/异常 (____)
```

**部署执行人**：huali（服务器端操作，开发机仅提供本确认文档）
**部署确认人**：Claude（开发机，负责记录与对比）
