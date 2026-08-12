# SOA-006 Watchdog 增强方案 — 验证测试计划

## 审计结论（测试前发现的代码问题）

> **状态**: Bug #1 和 Bug #2 已修复。Bug #3 为低优先级，暂不处理。
> **修复日期**: 2026-08-12

### Bug #1 (HIGH): UPSTREAM_UNREACHABLE_TG 落入 Tier 2 升级路径 ✅ 已修复

**位置**：`Test-ProxyChain` 行 237-244 + 主循环行 614-658

**代码路径追踪**：
```
行 240-241: InternetOK=true 时 Stage=UPSTREAM_UNREACHABLE_TG
行 614:     if ($stage -eq "UPSTREAM_UNREACHABLE_ALL") → FALSE，不拦截
行 637:     if ($inCooldown) → FALSE（第一次）
行 644:     cooldown 检查 → FALSE
行 652-658: 进入正常升级，failures>=3 时触发 Tier 2
```

**影响**：Telegram API 暂时不可达（但代理本身正常运行）时，连续 3 次检测会触发 FlClash 重启。重启 FlClash 不能修复 Telegram API 问题，这是**无效重启**，直接违背 SOA-006 的防止无限重启目标。

**修复方案**：在行 614 之后增加：
```powershell
# UPSTREAM_UNREACHABLE_TG means proxy works, only Telegram is down
# Tier 2 (FlClash restart) won't help — record and wait
if ($stage -eq "UPSTREAM_UNREACHABLE_TG") {
    Write-Log "UPSTREAM_UNREACHABLE_TG — proxy OK, Telegram API may be temporarily unreachable. Skipping Tier 2." "WARN"
    Write-State $failures $true $state.tier2_streak $null
    exit 0
}
```

### Bug #2 (MEDIUM): InternetOK 误判 — curl exit 0 不代表上游可达

**位置**：`Test-ProxyChain` 行 226-233

**问题**：当所有上游节点失效时，FlClashCore 代理通常会返回 HTTP 502/503 错误响应。curl 收到这个 HTTP 错误响应后退出码为 0（HTTP 连接成功），于是 `InternetOK = true`，最终 Stage 被判定为 `UPSTREAM_UNREACHABLE_TG` 而非 `UPSTREAM_UNREACHABLE_ALL`。

**影响**：
1. 快速熔断通道（行 614-633）被绕过 — 真正的全节点失效被误判为 Telegram 问题
2. 实际上是 `UPSTREAM_UNREACHABLE_ALL` 但被诊断为 `UPSTREAM_UNREACHABLE_TG`
3. 可能落入 Tier 2 升级路径（见 Bug #1）

**验证方法**：检查 FlClashCore 在所有上游节点不可达时，对 `gstatic.com/generate_204` 返回什么：
- 如果返回 HTTP 502 → InternetOK 误判为 true → 需要修复
- 如果超时无响应 → InternetOK 正确为 false → 无问题

等待实际测试验证。

**修复方案（如确认）**：用 `curl -w '%{http_code}' -o NUL` 检查 HTTP 状态码：
```powershell
$LASTEXITCODE = 0
$httpCode = ""
try {
    $httpCode = curl.exe -s -o NUL -w "%{http_code}" --proxy $ProxyUrl $TestUrl `
        --connect-timeout 5 --max-time 10 2>$null
    if ($LASTEXITCODE -eq 0 -and $httpCode -match '^(200|204|301|302)') {
        $diag.InternetOK = $true
    }
} catch {}
```

### Bug #3 (LOW): Get-BotToken 失败返回 UPSTREAM_UNREACHABLE_TG

**位置**：`Test-ProxyChain` 行 208-211

**问题**：`.env` 无法读取或 token 缺失时，直接返回 `UPSTREAM_UNREACHABLE_TG`，没有检测过 Internet 连通性。这会把本地配置问题误报为上游问题。

**影响**：低调，因为 `.env` 故障罕见且通常伴随其他症状。可在验证后再修复。

### 关注 #4: fast-track cooldown 的 strike 计数混合使用 `tier2_streak`

**位置**：行 621: `$fastStrike = [int]($state.tier2_streak) + 1`

`tier2_streak` 既被 Tier 2 失败递增（行 667），又被 UPSTREAM_UNREACHABLE_ALL fast-track 使用（行 621）。这导致：1 次 Tier 2 失败 + 1 次 UPSTREAM_UNREACHABLE_ALL = 立即进入 cooldown。

**评估**：这是合理的。因为 Tier 2 刚重启了 FlClash，重启后发现全节点不可达 → 再次重启也不可能修复 → 应该熔断。**不需要修复**，但需要在测试 5 中验证这个混合场景。

---

## 测试环境准备

| 项目 | 值 |
|------|-----|
| 脚本路径 | `E:\AI\lianyu-ai-core\scripts\proxy-watchdog.ps1` |
| 状态文件 | `E:\AI\lianyu-ai-core\.proxy-watchdog-state` |
| 日志文件 | `E:\AI\lianyu-ai-core\logs\proxy-watchdog.log` |
| FlClash 路径 | `$env:APPDATA\com.follow\clash\` |
| 代理端口 | 127.0.0.1:7890 |
| FailThreshold | 3 |
| CircuitBreakerMaxTier2 | 3 |
| CooldownFastTrackStrike | 2 |

**测试前备份**：
```powershell
Copy-Item .proxy-watchdog-state .proxy-watchdog-state.bak
```

---

## 测试 1：正常状态

**目的**：验证健康代理不触发任何恢复动作。

**前提**：FlClashCore 正常运行，7890 端口正常，代理能访问 Telegram 和互联网。

**步骤**：
```powershell
# 重置状态文件
@'
{"consecutive_failures":0,"bot_needs_restart":false,"tier2_streak":0,"cooldown_until":null,"last_updated":""}
'@ | Set-Content .proxy-watchdog-state -Encoding UTF8

# 执行 watchdog
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
```

**预期结果**：
- [ ] 日志输出 `Proxy chain: OK — all layers healthy`
- [ ] `$LASTEXITCODE` = 0
- [ ] 状态文件内容不变（无 Write-State 调用）
- [ ] 没有触发任何进程重启
- [ ] FlClashCore / FlClash / LianyuTelegram 进程数不变

---

## 测试 2：FlClashCore 进程死亡

**目的**：验证 Stage 1 诊断 + Tier 2 正常恢复流程。

**前提**：FlClash 和 FlClashCore 正常运行。

**步骤**：
```powershell
# 1. 重置状态
@'
{"consecutive_failures":0,"bot_needs_restart":false,"tier2_streak":0,"cooldown_until":null,"last_updated":""}
'@ | Set-Content .proxy-watchdog-state -Encoding UTF8

# 2. 记录当前进程
Get-Process FlClashCore, FlClash -ErrorAction SilentlyContinue | Select Name, Id

# 3. 模拟：杀死 FlClashCore（保留 FlClash 进程）
Stop-Process -Name FlClashCore -Force

# 4. 确认 FlClashCore 已死
Get-Process FlClashCore -ErrorAction SilentlyContinue  # 应无输出

# 5. 执行 watchdog（第 1 次 — 记录失败）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
# 预期日志: PROCESS_DEAD, failures=1, 等待更多失败

# 6. 再执行 2 次（第 2、3 次 — 累计到 3 次触发 Tier 2）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
# 第 3 次预期: TIER 2 RECOVERY triggered → FlClash restarted → proxy ready
```

**预期结果**：
- [ ] 第 1 次：日志显示 `PROCESS_DEAD` + `ProcessAlive: false`
- [ ] 第 1 次：`failures=1/3, waiting...`
- [ ] 第 2 次：`failures=2/3, waiting...`
- [ ] 第 3 次：触发 Tier 2，日志显示 `TIER 2 RECOVERY`
- [ ] FlClash 被重新拉起（检查进程）
- [ ] FlClashCore 进程恢复
- [ ] 7890 端口恢复监听
- [ ] `Test-ProxyChain` 最终返回 OK
- [ ] 状态文件重置为全 0
- [ ] 没有进入 cooldown

---

## 测试 3：7890 端口异常（Core 存活但端口不监听）

**目的**：验证 Stage 2 诊断的准确性。

**前提**：FlClashCore 在运行，Port 7890 被占用（模拟：用其他进程监听 7890，或 kill Core 后等待数十秒 Core 内重启未完成）。

**步骤**：
```powershell
# 1. 等 FlClash 完全启动后，用 netsh 临时阻断 7890（或用防火墙规则）
# 方案 A：临时防火墙规则
New-NetFirewallRule -Name "TEST_BLOCK_7890" -Direction Outbound -LocalPort 7890 -Protocol TCP -Action Block

# 2. 执行 watchdog
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1

# 3. 检查日志中的诊断信息
Select-String -Path logs/proxy-watchdog.log -Pattern "PORT_NOT_LISTENING" | Select-Object -Last 1

# 4. 清理
Remove-NetFirewallRule -Name "TEST_BLOCK_7890"
```

**预期结果**：
- [ ] 日志显示 `PORT_NOT_LISTENING`
- [ ] 诊断信息中 `ProcessAlive: true`, `PortOpen: false`
- [ ] 不会误报为 `PROCESS_DEAD`
- [ ] 不会误报为 `UPSTREAM_UNREACHABLE_ALL`（因为端口不通，Stage 3 根本没执行）

---

## 测试 4：上游节点全部失效（SOA-006 核心场景）

**目的**：验证全节点失效时不会无限重启 FlClash，而是快速进入 cooldown。

**模拟方案**：Core 运行、端口正常，但代理无法访问任何外部网站。
由于无法真正让 32 个节点全部失效，采用以下模拟方式之一：
- **方案 A**（推荐）：临时修改防火墙规则，阻断 FlClashCore 所有出站连接
- **方案 B**：在 `config.yaml` proxies 中临时把 server 改成无效地址，重启 FlClash

**步骤（方案 A）**：
```powershell
# 1. 重置状态
@'
{"consecutive_failures":0,"bot_needs_restart":false,"tier2_streak":0,"cooldown_until":null,"last_updated":""}
'@ | Set-Content .proxy-watchdog-state -Encoding UTF8

# 2. 找到 FlClashCore 的 PID
$pid = (Get-Process FlClashCore).Id

# 3. 用 Windows 防火墙阻断 FlClashCore 的所有出站 TCP
New-NetFirewallRule -Name "TEST_BLOCK_FLCLASH_UPSTREAM" `
    -Direction Outbound -Program "%ProgramFiles%\FlClash\FlClashCore.exe" `
    -Protocol TCP -RemotePort 1-65535 -Action Block

# 4. 等待 10 秒让现有连接超时

# 5. 执行 watchdog（连续 3 次，模拟 3 个 5 分钟周期）
# 第 1 次
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
Get-Content .proxy-watchdog-state

# 第 2 次（应触发 fast-track cooldown）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
Get-Content .proxy-watchdog-state

# 第 3 次（应在 cooldown 中）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
Get-Content .proxy-watchdog-state

# 6. 清理
Remove-NetFirewallRule -Name "TEST_BLOCK_FLCLASH_UPSTREAM"

# 7. 恢复后执行一次（应自动退出 cooldown）
Start-Sleep 5
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
Get-Content .proxy-watchdog-state
```

**预期结果**：
- [ ] 第 1 次：`UPSTREAM_UNREACHABLE_ALL` + `fastStrike=1` + `skipping Tier 2`
- [ ] 第 1 次：`subscription` 和 `config` 健康检查已执行
- [ ] 第 2 次：`fastStrike=2` → `CIRCUIT BREAKER FAST-TRACK` → `CRITICAL`
- [ ] 第 2 次：状态文件有 `cooldown_until`
- [ ] **关键**：整个过程 0 次 FlClash 重启（与 SOA-006 的 30+ 次对比）
- [ ] 第 3 次：`CIRCUIT BREAKER ACTIVE — Tier 2 suppressed`
- [ ] 清理后恢复：proxy 恢复 → `CIRCUIT BREAKER RESET` → 全清零

---

## 测试 5：Tier 2 连续失败 → Cooldown

**目的**：验证真实 FlClash 崩溃 + 反复重启失败的场景下，熔断机制的触发和状态持久化。

**模拟方案**：删除 FlClash.exe 或将其改名，使 Tier 2 的 `Restart-FlClash` 无法启动 FlClash。

**步骤**：
```powershell
# 1. 重置状态
@'
{"consecutive_failures":0,"bot_needs_restart":false,"tier2_streak":0,"cooldown_until":null,"last_updated":""}
'@ | Set-Content .proxy-watchdog-state -Encoding UTF8

# 2. 备份并移除 FlClash.exe（模拟无法启动）
$exePath = (Get-Process FlClash -ErrorAction SilentlyContinue | Select-Object -First 1).Path
if (-not $exePath) { $exePath = "C:\Program Files\FlClash\FlClash.exe" }
Copy-Item $exePath "$exePath.bak"
Rename-Item $exePath "$exePath.disabled"

# 3. 杀死 FlClashCore（触发 PROCESS_DEAD）
Stop-Process -Name FlClashCore -Force -ErrorAction SilentlyContinue
Stop-Process -Name FlClash -Force -ErrorAction SilentlyContinue

# 4. 连续执行 watchdog 6 次（模拟 6 个 5-min 周期，共 30 分钟）
# 前 3 次累积到 FailThreshold，后 3 次触发 Tier 2 但都失败
for ($i=1; $i -le 6; $i++) {
    Write-Host "=== Cycle $i ==="
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
    $state = Get-Content .proxy-watchdog-state -Raw | ConvertFrom-Json
    Write-Host "  failures=$($state.consecutive_failures) tier2_streak=$($state.tier2_streak) cooldown=$($state.cooldown_until)"
    Start-Sleep 2
}

# 5. 恢复 FlClash.exe
Rename-Item "$exePath.disabled" $exePath

# 6. 手动启动 FlClash（模拟人工干预）
Start-Process $exePath -WindowStyle Hidden

# 7. 等待 30 秒代理就绪，再执行 watchdog
Start-Sleep 30
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
Get-Content .proxy-watchdog-state

# 8. 清理备份
Remove-Item "$exePath.bak" -ErrorAction SilentlyContinue
```

**预期结果**：
- [ ] Cycle 1-2：`failures=1-2`，`PROCESS_DEAD`，等待中
- [ ] Cycle 3：`failures=3` → Tier 2 触发 → FlClash.exe 不存在 → `Restart-FlClash` 返回 false → `tier2_streak=1`
- [ ] Cycle 4-5：`failures=4-5` → Tier 2 再触发 → 失败 → `tier2_streak=2-3`
- [ ] Cycle 6：`tier2_streak=3 >= 3` → `CIRCUIT BREAKER OPEN` → `CRITICAL`
- [ ] **总共执行了 3 次 FlClash 重启尝试**（不是 30+ 次）
- [ ] Cycle 6 后状态文件：`cooldown_until` 不为空
- [ ] 恢复后：proxy 恢复 → 状态清零

---

## 测试 6：Cooldown 期间代理自行恢复

**目的**：验证代理在 cooldown 期间恢复后，能自动清零所有状态。

**步骤**：
```powershell
# 1. 手动设置状态为 cooldown 中
$cooldownUntil = (Get-Date).AddMinutes(10).ToString("yyyy-MM-ddTHH:mm:ss")
@"
{"consecutive_failures":9,"bot_needs_restart":true,"tier2_streak":3,"cooldown_until":"$cooldownUntil","last_updated":"2026-08-12T00:00:00"}
"@ | Set-Content .proxy-watchdog-state -Encoding UTF8

# 2. 确保代理当前正常（FlClashCore 运行，7890 OK）
# 3. 执行 watchdog
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1

# 4. 检查状态是否清零
Get-Content .proxy-watchdog-state
```

**预期结果**：
- [ ] 日志：`Proxy chain: OK — all layers healthy`
- [ ] 日志：`CIRCUIT BREAKER RESET — proxy recovered`
- [ ] 日志：`Proxy recovered after previous failure(s). Triggering bot restart.`
- [ ] Tier 1 触发（重启 Bot）
- [ ] 状态文件：`consecutive_failures=0, tier2_streak=0, cooldown_until=null`
- [ ] 下次 watchdog 执行时正常静默退出

---

## 综合验证标准

| 验证项 | 标准 | SOA-006 对比 |
|--------|------|------------|
| UPSTREAM_UNREACHABLE_ALL 时 Tier 2 次数 | **0 次** | 之前 30+ 次 |
| PROCESS_DEAD 时 Tier 2 次数上限 | **最多 3 次**（CircuitBreakerMaxTier2） | 之前无限 |
| Cooldown 后是否继续重启 | **不重启** | 之前继续重启 |
| 误判导致无效重启 | **已消除**（UPSTREAM_UNREACHABLE_TG 不走 Tier 2） | 无此诊断 |
| Cooldown 期间代理恢复 | **自动清零** | 无此机制 |
| 状态文件持久化 | **新增 cooldown 状态** | 仅 failure count |
| 人工干预指导 | **CRITICAL 日志列出检查步骤** | 无 |

## 测试清理

测试完成后执行：
```powershell
# 恢复状态文件
Copy-Item .proxy-watchdog-state.bak .proxy-watchdog-state -Force

# 清理防火墙规则
Remove-NetFirewallRule -Name "TEST_BLOCK_*" -ErrorAction SilentlyContinue

# 确保 FlClash 正常运行
Get-Process FlClashCore, FlClash -ErrorAction SilentlyContinue
```
