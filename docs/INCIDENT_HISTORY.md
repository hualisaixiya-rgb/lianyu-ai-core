# Incident History — LianyuAI 服务器事故记录

> 每次故障追加一条 SOA 编号，记录现象、根因、修复、预防措施。
>
> 故障排查协议见 [CLAUDE.md § 服务器故障排查协议](../CLAUDE.md)。
> 日常运行观察见 [SERVER_OBSERVATION.md](SERVER_OBSERVATION.md)。

## SOA 快速索引

| SOA# | 时间 | 故障 | 类型 | 状态 |
|------|------|------|------|------|
| [SOA-001](#soa-001) | 2026-07 | `date.timedelta` AttributeError → 关系系统静默失败 | 代码 Bug | ✅ 已修复 v3.8.1 |
| [SOA-002](#soa-002) | 2026-08-01 | Telegram Conflict — 重复 Bot 实例 | NSSM 配置 | ✅ 已修复 |
| [SOA-003](#soa-003) | 2026-08-01 | UV Launcher → 全服务双实例（每服务 2 进程） | NSSM 配置 | ✅ 已修复 |
| [SOA-004](#soa-004) | 2026-08-02 | FlClashCore 代理退化 → Bot 无法连接 Telegram | 基础设施 | ⚠️ watchdog v2 已加强 |
| [SOA-005](#soa-005) | 2026-08-02 晚 | 代理短暂中断触发 getUpdates 长轮询僵死（连接池未隔离） | 适配器 polling | 🔧 请求隔离已提交 fd88498（待合 main） |
| [SOA-006](#soa-006) | 2026-08-12 | Watchdog 增强与熔断改造（proxy-watchdog 分层诊断 + 熔断） | 治理/修复项 | ✅ 已合并 feff3d8 |
| [SOA-007](#soa-007) | 2026-08-14 | getUpdates 静默停止（代理健康）→ polling-check 重启恢复 | 适配器 polling | 🔧 待合并 SOA-005 隔离 |

---

## SOA-001

**时间：** 2026-07（自基线 `39ba7ed` 起存在，2026-08-01 排查 V3.8 故障时发现）

**发现者：** V3.8 部署后用户反馈"绘梨衣像重新认识用户"

### 故障现象

- 用户询问"想我了吗" → AI 回复"虽然才刚见面"
- 用户询问"我们之前发生过什么事情吗" → AI 却能正确回忆排练事件
- 日常聊天中 AI 无关系连续感，但回忆过去时正常

### 根因

**代码 Bug：`memory/stores/relationship_store.py:94` `date.timedelta` 拼写错误。**

```python
from datetime import datetime, date     # line 13 — timedelta 未导入

# line 94-96:
if last_date == today - date.timedelta(days=1):    # ❌ date.timedelta 不存在
```

`date` 是 `datetime.date` 类，没有 `timedelta` 属性。正确用法是 `timedelta(days=1)`。

**错误链：**
```
touch() (已有用户) → date.timedelta(days=1)
  → 💥 AttributeError
  → ai/core.py:257 except Exception → logger.debug()（生产环境静默）
  → get_timeline_context() 从未被调用
  → System Prompt 无【近期事件记录】区块
  → DAILY_CHAT / DEEP_TALK 下 AI 无关系连续感
```

**RECALL_PAST 为何正常：** `ai/core.py:376` 在 RECALL_PAST 意图下**独立**调用 `get_timeline_context()`，不经过上述 try/except 块。

**为何 V3.8 前未暴露：** messages 表有 127 条完整历史，LLM 可从对话推断关系。V3.8 部署期间 messages 表被清空，对话历史太短，关系依赖完全落在已损坏的 Timeline 注入上。

### 修复

**Commit:** `cb12bf6` (v3.8.1-stable)

1. `memory/stores/relationship_store.py:13` — `from datetime import datetime, date` → `from datetime import datetime, date, timedelta`
2. `memory/stores/relationship_store.py:94,96` — `date.timedelta` → `timedelta`
3. `tests/test_relationship_store.py` — 新增 60 行测试覆盖

### 预防措施

- `except Exception` 日志级别从 `logger.debug` 提升至 `logger.warning`（待后续版本）
- 关系注入失败的异常不应被静默吞掉

---

## SOA-002

**时间：** 2026-08-01

**发现者：** Telegram 发送消息后 AI 不回复，日志停在 11:10，16:30 发现时已闲置 5h 23min

### 故障现象

- Telegram 消息可发送，但 AI 完全无回复
- 日志中出现 `telegram.error.Conflict: terminated by other getUpdates request`

### 根因

**Telegram Bot 多实例运行。** 两个 Python 进程同时向 Telegram API 轮询消息，Telegram 服务器的去重机制会踢掉旧连接，导致消息投递到已被踢的连接 → 消息丢失。

### 修复

`nssm restart LianyuTelegram`（临时恢复）。后续由 SOA-003 修复彻底解决根因。

### 预防措施

- 出现 Bot 无响应时，先检查 `E:\AI\logs\telegram_stderr.log` 是否有 `Conflict`
- 存在 Conflict 时检查 Python 进程数

---

## SOA-003

**时间：** 2026-08-02 凌晨

**发现者：** SOA-002 复发 — LianyuTelegram 重启 26 小时后再次不回复

### 故障现象

- Telegram AI 不回复
- Python 进程数 = **6 个**（每服务 2 个）
- Telegram stderr 出现 16 次 `Conflict`

### 排查过程

1. NSSM 状态：三个服务均 SERVICE_RUNNING
2. Python 进程数：6 个（预期 3 个）
3. 进程树：每个 NSSM 子进程下有一个孙进程，运行相同脚本但使用不同 Python 解释器
4. `.venv\Scripts\python.exe` 经检查实为 Python Launcher（`py.exe`）

### 根因

**UV 虚拟环境的 Windows Launcher 机制导致 NSSM 误判进程退出。**

```
.venv\Scripts\python.exe → 实际是 Python Launcher (py.exe)
  → 启动系统 Python
  → Launcher 立即退出
  → NSSM AppExit = Default Restart 误判为"进程崩溃"
  → 重启 Launcher → 又一个系统 Python
  → 总进程数翻倍
```

### 修复

NSSM 配置修改：Application 从 `.venv\Scripts\python.exe` 改为**系统 Python 直连路径**，同时设置 `PYTHONPATH=.venv\Lib\site-packages`。

### 预防措施

- 服务器每次重启后确认 Python 进程数 = 3
- UV 升级后重新验证 Launcher 行为是否改变
- 出现 Bot 无响应时优先检查进程数

---

## SOA-004

**时间：** 2026-08-02（同日复发 2 次 — 中午 + 傍晚）

**发现者：** Telegram 可发送但 AI 不回复；诊断发现代理层故障

### 故障现象

- Telegram 消息可发送，AI 无回复
- 无 `Conflict` 错误（非重复实例）
- AI Core Web API 正常（排除代码问题）
- 最后一条 Telegram 消息后 Bot 日志完全停滞

### 根因

**FlClashCore 代理节点随时间退化。** 代理进程长时间运行（首次 38h，复发仅 1h15min），代理节点/连接链路逐渐不稳定，从间歇性故障发展为持续返回 502 Bad Gateway。

**错误演进链：**
```
httpx.ConnectError → httpx.ReadError → httpx.RemoteProtocolError → Bad Gateway
     (连接失败)         (读取超时)         (服务端断开)              (代理不可用)
```

**联动缺失加剧停机：** 代理被单独重启后，Bot 持有失效连接不重连，即使代理已恢复，Bot 仍无法收消息。

### 修复

1. **短期恢复：** 重启 FlClash → 代理恢复 → `nssm restart LianyuTelegram` → Bot 重连
2. **长期防护：** 部署 `scripts/proxy-watchdog.ps1`

### 预防措施

| 措施 | 实现 | 状态 |
|------|------|------|
| 代理健康监控 + 联动恢复 | 每 5 分钟 curl getMe 检测，连续 3 次失败 → 重启代理 + Bot | ✅ 脚本已就位，待注册 Task Scheduler |
| 代理定时重启 | 建议每日凌晨重启（防止长时间退化） | ⬜ 待评估 |
| Bot 层 NetworkError 告警 | 持续 N 次失败后写告警日志 | ⬜ 待后续 |

**proxy-watchdog.ps1 覆盖范围：**
- ✅ SOA-004 类代理退化全自动恢复（最大停机 ~15min = 3×5min 检测窗口）
- ❌ SOA-002/003 类重复实例（需人工排查，NSSM 配置修复后理论上已消除）

---

## SOA-005

**时间：** 2026-08-02 19:22 起

**发现者：** 用户报告 Telegram 不回复（SOA-004 恢复后 2h 再次发生）

### 故障现象

- Telegram 可发送，AI 不回复
- 所有 NSSM 服务运行正常（3 进程）
- 代理当前正常（getMe 通过）
- 但 Bot 自 19:22 后无任何消息活动

### 根因

**Bot getUpdates 长轮询连接未隔离 —— 一次短暂代理中断（< 5 分钟）即导致 polling 僵死，Watchdog 阈值过高未能触发恢复。**

深层根因：getUpdates 长轮询与普通 API（reply_text / send_chat_action）共用同一 `connection_pool_size=8` 连接池。
代理中断只是触发器；结构性的脆弱点是「连接池未隔离」。

故障链：
```
代理短暂中断（< 5 分钟）
  → Bot long-polling 连接断开
  → python-telegram-bot 重试耗尽 / 长退避
  → Watchdog 20:24 检测到失败（1/3）
  → Watchdog 20:29 检测到代理自行恢复
  → 计数器重置为 0 — 阈值 3 未达到
  → Bot 从未被重启 → 僵尸状态持续
```

**与 SOA-004 的本质区别：**
| | SOA-004 | SOA-005 |
|------|---------|----------|
| 代理故障时长 | > 15 分钟（持续） | < 5 分钟（短暂） |
| Watchdog 检测 | 3 次连续失败 → 触发 | 1 次失败 → 未触发 |
| Bot 状态 | 代理恢复后 Bot 无连接 | 同 |
| 根因 | Watchdog 发现并恢复 ✅ | Watchdog **漏检** ❌ |

**核心矛盾：** Bot 比代理更脆弱。一次不到 5 分钟的代理中断就能杀死 Bot 连接，但旧版 Watchdog 阈值 = 3（15 分钟）永远不会触发。

### 修复

**即时恢复（2026-08-02，不修改代码）：** 调整 `proxy-watchdog.ps1` 恢复逻辑：

1. 状态文件新增 `bot_needs_restart` 标记
2. **Tier 1（SOA-005）：** 代理任何一次失败后恢复 → 立即重启 Bot
3. **Tier 2（SOA-004）：** 连续 3 次失败 → 重启 FlClash + Bot（保留）

**深层修复（请求隔离）：** 独立 `get_updates_request` 连接池（`connection_pool_size=1`），
与普通 API 池（`connection_pool_size=8`）隔离 —— 已提交 commit `fd88498`（分支 `fix/soa005-merge`，待合 main）。

### 预防措施

| 措施 | 实现 | 状态 |
|------|------|------|
| 两段式恢复 | `bot_needs_restart` 标记 — 代理恢复即重启 Bot | ✅ 已写入 watchdog v2 |
| 降低漏检风险 | Tier 1 不需要阈值，单次故障即标记 | ✅ |
| Bot 死连接检测 | 将来可加入"距上次消息超过 N 分钟"检测 | ⬜ 待评估 |

---

## SOA-006

**类型：** 🛠️ 治理措施 / 修复项（非事故）

**时间：** 2026-08-12（commit `feff3d8`）

**动机：** SOA-004/005 暴露 proxy-watchdog 盲点 —— 当全部上游代理节点（Shadowsocks/Hysteria2）同时不可达时，watchdog 误判为 FlClash 崩溃，陷入无限 Tier 2 重启循环（30+ 次 / 数小时），无诊断可见性。

**改动：** `scripts/proxy-watchdog.ps1`

1. **分层诊断**（替代单一二进制健康检查）：
   - `PROCESS_DEAD` — FlClashCore 进程崩溃
   - `PORT_NOT_LISTENING` — 进程存活但 7890 端口未绑定
   - `UPSTREAM_UNREACHABLE_TG` — 端口 OK、Telegram 不可达、普通网络 OK
   - `UPSTREAM_UNREACHABLE_ALL` — 所有上游不可达（节点/订阅故障）
2. **熔断（circuit breaker）**：
   - 3 次 Tier 2 失败 → 冷却 30 分钟
   - `UPSTREAM_UNREACHABLE_ALL` → 快速通道冷却（跳过无意义重启）
   - `UPSTREAM_UNREACHABLE_TG` → 不再重启 FlClash

**状态：** ✅ 已合并 main（feff3d8）。属对 SOA-004 代理退化及 SOA-005「代理触发环节」的治理改造
（仅覆盖代理层监测与恢复，不含 getUpdates 连接池隔离），非独立事故。

---

## SOA-007

**时间：** 2026-08-14 ~09:56–10:26（约 30 分钟）

**发现者：** 用户报告"有一段时间不回复用户，之后又恢复"

### 故障现象

- 用户 ~10:11 发送"早上好"无回复，约 10:26 恢复后收到积压消息并回复
- 代理全程健康（proxy-watchdog 每 5 分钟 `Proxy chain: OK`，09:54→10:29 无间断）
- Bot 进程存活（NSSM `SERVICE_RUNNING`，无崩溃）
- 无任何可时间关联的错误日志（AI 日志 03:04→10:26 零记录；stderr 轮询错误无时间戳）

### 排查时间线

| 时间 | 事件 |
|------|------|
| 09:56:09 | 最后一次 polling-check "健康（409 Conflict）" |
| ~09:56–10:11 | Bot getUpdates 静默停止 |
| 10:11:05 | polling-check "无 409"（1/2） |
| 10:26:05 | polling-check "无 409"（2/2）→ 触发恢复 |
| 10:26:07 | nssm restart LianyuTelegram |
| 10:26:17 | 恢复轮询，立即收到积压"早上好"并回复 |

> **polling-check 检测机制：** 外部 `getUpdates` 调用 — 返回 `409 Conflict` = Bot 仍在 polling（健康）；返回 `200 OK` = Bot 不在 polling（判定失败）。连续 2 次失败 → 重启 LianyuTelegram。

### 根因

**Bot polling 循环静默停滞 — 代理正常但 getUpdates 无连接。** 与 SOA-005 的触发机制不同：本次故障发生期间代理持续健康，并非由代理中断直接触发；但两者的结构性根因相同，均指向 getUpdates 长轮询与普通 API 共用 HTTPXRequest 连接池。

停滞的具体机制无法 100% 定位（轮询错误写 stderr 且无时间戳）。最强诱因指向**未隔离的单一 HTTPXRequest 连接池**：`getUpdates` 长轮询与普通 API 请求（`reply_text`/`send_chat_action`）共用同一个 `connection_pool_size=8` 的池，正是 SOA-005 request isolation 要解决的故障模式。

**分层判定：**

| 层 | 判定 |
|----|------|
| 代理层 | ❌ 排除（proxy-watchdog 全程 OK） |
| 进程层 | ❌ 排除（SERVICE_RUNNING 无崩溃） |
| AI/LLM 层 | ❌ 排除（故障期无消息进入 handler） |
| 适配器 polling 层 | ✅ **确认（getUpdates 停止）** |

### 修复

- **临时恢复：** `nssm restart LianyuTelegram`（由 polling-check 自动触发）
- **根因修复（已提交待合并）：** SOA-005 request isolation — 独立 `get_updates_request` 连接池
  （分支 `fix/soa005-merge`，commit `fd88498`，尚未合并到 main）

### 预防措施

| 措施 | 状态 |
|------|------|
| 合并 SOA-005 连接池隔离（get_updates_request 独立池，commit fd88498） | 🔧 已提交，待合 main |
| 轮询错误补时间戳（当前 stderr 无时间戳，无法定位根因） | ⬜ 待做 |

---

## 附录

### 故障诊断速查

| 症状 | 第一检查点 | 可能 SOA |
|------|-----------|----------|
| AI 不回复 + `Conflict` 日志 | Python 进程数 > 3 | SOA-002 / SOA-003 |
| AI 不回复 + 无 Conflict + 进程数 = 3 + 代理持续不可用 | `curl --proxy` 测试代理 | SOA-004 |
| AI 不回复 + 无 Conflict + 进程数 = 3 + 代理当前正常 | Bot 日志停滞 + Watchdog 日志 | SOA-005 |
| AI 不回复 + 代理正常 + getUpdates 无 409 | polling-check 日志 | SOA-007 |
| AI 行为异常（如"刚见面"）+ API 正常 | 版本检查 / 数据库检查 | SOA-001 |
| 全服务宕机 | NSSM status 三项 | 新增 |

### 运维脚本清单

| 路径 | 用途 | 运行方式 |
|------|------|----------|
| `scripts/backup.ps1` | 每日数据库备份 | Task Scheduler 3:00 AM |
| `scripts/deploy.ps1` | GitHub Webhook 自动部署 | webhook_server.py 触发 |
| `scripts/proxy-watchdog.ps1` | 代理健康检查 + 联动恢复 | Task Scheduler 每 5 分钟 |
| `scripts/telegram-polling-check.ps1` | Bot polling 存活检测（getUpdates 409） | Task Scheduler 每 15 分钟 |

---

> **最后更新：** 2026-08-14（SOA-007 记录 getUpdates 静默停止事件；SOA-005 请求隔离已提交待合并）
> **维护规则：** 每次新故障在末尾追加 SOA-XXX，不覆盖已有记录，同步更新顶部索引表。
