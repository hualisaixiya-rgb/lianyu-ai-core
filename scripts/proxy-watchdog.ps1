# ============================================================
# LianyuAI — 代理健康检查 + 联动恢复（增强版 watchdog）
#
# 用途：检测 FlClashCore 代理是否正常转发 Telegram API。
#
# 三段式恢复：
#   Tier 1（SOA-005）：代理任何一次故障后恢复 → 重启 Bot
#   Tier 2（SOA-004）：连续 3 次故障 → 重启 FlClash → 重启 Bot
#   Circuit Breaker：连续 Tier 2 失败 → 进入 Cooldown，停止自动恢复
#
# 增强功能（SOA-006 后）：
#   - 代理链路分层诊断（进程 → 端口 → 上游连通性）
#   - Tier 2 熔断机制（防止无限重启）
#   - 订阅/配置健康检查
#
# 部署：Windows Task Scheduler，每 5 分钟触发。
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/proxy-watchdog.ps1
#
# 设计约束：
#   - 不引入外部依赖（仅 PowerShell + curl.exe）
#   - 不修改项目代码
#   - 状态文件记录失败计数 + 熔断状态
# ============================================================

param(
    [int]$TimeoutSec = 10,
    [int]$FailThreshold = 3,
    [string]$StateFile = "E:\AI\lianyu-ai-core\.proxy-watchdog-state",
    [string]$LogFile  = "E:\AI\lianyu-ai-core\logs\proxy-watchdog.log"
)

$ProxyUrl  = "http://127.0.0.1:7890"
$TestUrl   = "https://www.gstatic.com/generate_204"   # FlClash 内置连通性检测 URL

# ---- Circuit breaker configuration ----
$CircuitBreakerMaxTier2  = 3     # 连续 Tier 2 失败 N 次后进入 Cooldown
$CircuitCooldownMinutes  = 30    # Cooldown 时长（仅监控，不重启）
$CooldownFastTrackStrike = 2     # UPSTREAM_UNREACHABLE_ALL 连续 N 次直接进入 Cooldown

# ---- FlClash config paths ----
$FlClashDataDir = "$env:APPDATA\com.follow\clash"
$FlClashPrefs   = "$FlClashDataDir\shared_preferences.json"
$FlClashDb      = "$FlClashDataDir\database.sqlite"
$FlClashConfig  = "$FlClashDataDir\config.yaml"

# ================================================================
# Helpers
# ================================================================

function Write-Log {
    param([string]$Msg, [string]$Level = "INFO")
    $ts   = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    $line = "$ts [$Level] $Msg"
    Write-Host $line
    try {
        $logDir = Split-Path $LogFile -Parent
        if (-not (Test-Path $logDir)) {
            New-Item -ItemType Directory -Force -Path $logDir -ErrorAction Stop | Out-Null
        }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction Stop
    } catch {
        Write-Host "$ts [ERROR] Write-Log failed: $_"
    }
}

function Read-State {
    <#
    Returns a hashtable with all state fields.
    Missing/corrupt state → clean defaults.
    #>
    $default = @{
        consecutive_failures = 0
        bot_needs_restart    = $false
        tier2_streak         = 0
        cooldown_until       = $null
        last_updated         = ""
    }
    if (-not (Test-Path $StateFile)) { return $default }
    try {
        $json = Get-Content $StateFile -Raw -ErrorAction Stop | ConvertFrom-Json
        return @{
            consecutive_failures = [int]($json.consecutive_failures)
            bot_needs_restart    = ($json.bot_needs_restart -eq $true)
            tier2_streak         = [int]($json.tier2_streak)
            cooldown_until       = if ($json.cooldown_until) { $json.cooldown_until } else { $null }
            last_updated         = if ($json.last_updated) { $json.last_updated } else { "" }
        }
    } catch {
        Write-Log "State file corrupt, resetting to defaults" "WARN"
        return $default
    }
}

function Write-State {
    param(
        [int]$Failures,
        [bool]$BotNeedsRestart,
        [int]$Tier2Streak = 0,
        [string]$CooldownUntil = $null
    )
    $data = @{
        consecutive_failures = $Failures
        bot_needs_restart    = $BotNeedsRestart
        tier2_streak         = $Tier2Streak
        cooldown_until       = $CooldownUntil
        last_updated         = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    }
    # Atomic write: temp file → rename
    $tempFile = "$StateFile.tmp"
    try {
        $data | ConvertTo-Json | Set-Content $tempFile -Encoding UTF8 -ErrorAction Stop
        Move-Item -Force $tempFile $StateFile -ErrorAction Stop
    } catch {
        Write-Log "Failed to write state file: $_" "ERROR"
        Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
    }
}

# ---- Read Bot Token from project .env ----
function Get-BotToken {
    $envPath = "E:\AI\lianyu-ai-core\.env"
    if (-not (Test-Path $envPath)) { return $null }
    $found = Select-String -Path $envPath -Pattern '^TELEGRAM_BOT_TOKEN=([^#]+)' | Select-Object -First 1
    if (-not $found) { return $null }
    return ($found.Line -split '=', 2)[1].Trim()
}

# ---- Determine if currently in cooldown ----
function Test-InCooldown {
    param($State)
    if (-not $State.cooldown_until) { return $false }
    try {
        $until = [datetime]::Parse($State.cooldown_until)
        return (Get-Date) -lt $until
    } catch {
        return $false
    }
}

# ---- Determine if cooldown has expired ----
function Test-CooldownExpired {
    param($State)
    if (-not $State.cooldown_until) { return $true }
    try {
        $until = [datetime]::Parse($State.cooldown_until)
        return (Get-Date) -ge $until
    } catch {
        return $true
    }
}

# ================================================================
# Proxy Chain Diagnostics (SOA-006 Enhancement 2)
# ================================================================

function Test-ProxyChain {
    <#
    Layered health check replacing binary Test-ProxyHealth.
    Returns a diagnostic hashtable:
      Healthy      : $true | $false
      Stage        : "OK" | "PROCESS_DEAD" | "PORT_NOT_LISTENING" |
                     "UPSTREAM_UNREACHABLE_TG" | "UPSTREAM_UNREACHABLE_ALL"
      ProcessAlive : $true | $false
      PortOpen     : $true | $false
      TelegramOK   : $true | $false
      InternetOK   : $true | $false
    #>
    $diag = @{
        Healthy      = $false
        Stage        = "PROCESS_DEAD"
        ProcessAlive = $false
        PortOpen     = $false
        TelegramOK   = $false
        InternetOK   = $false
    }

    # ---- Stage 1: Process Liveness ----
    $coreProcess = Get-Process -Name "FlClashCore" -ErrorAction SilentlyContinue
    if (-not $coreProcess) {
        $diag.Stage = "PROCESS_DEAD"
        return $diag
    }
    $diag.ProcessAlive = $true

    # ---- Stage 2: Port Binding ----
    $portOpen = $false
    try {
        $tcpTest = Test-NetConnection -ComputerName 127.0.0.1 -Port 7890 `
            -InformationLevel Quiet -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
        if ($tcpTest) { $portOpen = $true }
    } catch {
        # Fallback: raw TCP socket attempt
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("127.0.0.1", 7890)
            $portOpen = $true
            $tcp.Close()
        } catch {}
    }
    if (-not $portOpen) {
        $diag.Stage = "PORT_NOT_LISTENING"
        return $diag
    }
    $diag.PortOpen = $true

    # ---- Stage 3: Upstream Connectivity (Telegram) ----
    $botToken = Get-BotToken
    if (-not $botToken) {
        Write-Log "Cannot read BotToken for Telegram health check" "ERROR"
        $diag.Stage = "UPSTREAM_UNREACHABLE_TG"
        return $diag
    }
    $botApiUrl = "https://api.telegram.org/bot$botToken/getMe"

    $LASTEXITCODE = 0
    try {
        $result = curl.exe -s --proxy $ProxyUrl $botApiUrl `
            --connect-timeout $TimeoutSec `
            --max-time ($TimeoutSec + 5) 2>$null
        if ($LASTEXITCODE -eq 0 -and $result -match '"ok"\s*:\s*true') {
            $diag.TelegramOK = $true
        }
    } catch {}

    # ---- Stage 3b: Upstream Connectivity (General Internet) ----
    # Use HTTP status code to distinguish real connectivity from proxy error pages.
    # When upstream nodes are dead, FlClash may return HTTP 502/503 — curl exits 0
    # (HTTP connection to proxy succeeded) but the internet is NOT actually reachable.
    $LASTEXITCODE = 0
    $httpCode = ""
    try {
        $httpCode = curl.exe -s -o NUL -w "%{http_code}" --proxy $ProxyUrl $TestUrl `
            --connect-timeout 5 --max-time 10 2>$null
        # Only accept HTTP 2xx/3xx as "internet reachable".
        # 5xx = proxy error (upstream dead), 000 = connection failure, 4xx = client error
        if ($LASTEXITCODE -eq 0 -and $httpCode -match '^[23]\d\d$') {
            $diag.InternetOK = $true
        }
    } catch {}

    # ---- Determine overall stage ----
    if ($diag.TelegramOK) {
        $diag.Healthy = $true
        $diag.Stage = "OK"
    } elseif ($diag.InternetOK) {
        $diag.Stage = "UPSTREAM_UNREACHABLE_TG"
    } else {
        $diag.Stage = "UPSTREAM_UNREACHABLE_ALL"
    }

    return $diag
}

function Test-ProxyHealth {
    <# Legacy wrapper — used by Restart-FlClash wait loop. #>
    $diag = Test-ProxyChain
    return $diag.Healthy
}

# ================================================================
# Subscription / Config Health Checks (SOA-006 Enhancement 3)
# ================================================================

function Test-SubscriptionAge {
    <#
    Reads FlClash database to check when subscription was last updated.
    Returns: @{ Success = $true|$false; AgeHours = float; Status = "OK"|"WARN"|"ERROR"|"UNKNOWN" }
    #>
    $result = @{ Success = $false; AgeHours = -1; Status = "UNKNOWN"; Message = "" }

    if (-not (Test-Path $FlClashPrefs)) {
        $result.Message = "shared_preferences.json not found"
        return $result
    }
    if (-not (Test-Path $FlClashDb)) {
        $result.Message = "database.sqlite not found"
        return $result
    }

    try {
        # Read current profile ID
        $prefs = Get-Content $FlClashPrefs -Raw -ErrorAction Stop | ConvertFrom-Json
        $flutterConfig = $prefs.'flutter.config' | ConvertFrom-Json
        $profileId = $flutterConfig.currentProfileId
        if (-not $profileId) {
            $result.Message = "No currentProfileId in FlClash preferences"
            return $result
        }

        # Read profiles table — SQLite via .NET (no external module needed)
        $connString = "Data Source=$FlClashDb;Version=3;Read Only=True;"
        # Use System.Data.SQLite if available, otherwise fall back to raw binary search
        try {
            Add-Type -Path "$FlClashDataDir\System.Data.SQLite.dll" -ErrorAction Stop
            $conn = New-Object System.Data.SQLite.SQLiteConnection($connString)
            $conn.Open()
            $cmd = $conn.CreateCommand()
            $cmd.CommandText = "SELECT updated_at FROM profiles WHERE id = @id LIMIT 1"
            $param = $cmd.Parameters.AddWithValue("@id", $profileId)
            $updatedAt = $cmd.ExecuteScalar()
            $conn.Close()

            if ($updatedAt -and $updatedAt -ne [DBNull]::Value) {
                $lastUpdate = [datetime]::Parse($updatedAt.ToString())
                $result.AgeHours = ((Get-Date) - $lastUpdate).TotalHours
                $result.Success = $true

                if ($result.AgeHours -lt 24) {
                    $result.Status = "OK"
                } elseif ($result.AgeHours -lt 72) {
                    $result.Status = "WARN"
                } else {
                    $result.Status = "ERROR"
                }
                $result.Message = "Last updated: $($lastUpdate.ToString('yyyy-MM-dd HH:mm:ss')) ($([math]::Round($result.AgeHours, 1))h ago)"
            } else {
                $result.Message = "Profile $profileId not found in database"
            }
        } catch [System.Management.Automation.MethodInvocationException] {
            # System.Data.SQLite.dll not available — try alternative approach
            Write-Log "System.Data.SQLite not available, using file-based subscription check" "DEBUG"
            # Check if the profile YAML file exists and its modification time
            $profileYaml = "$FlClashDataDir\profiles\$profileId.yaml"
            if (Test-Path $profileYaml) {
                $lastWrite = (Get-Item $profileYaml).LastWriteTime
                $result.AgeHours = ((Get-Date) - $lastWrite).TotalHours
                $result.Success = $true
                if ($result.AgeHours -lt 24) { $result.Status = "OK" }
                elseif ($result.AgeHours -lt 72) { $result.Status = "WARN" }
                else { $result.Status = "ERROR" }
                $result.Message = "Profile file: $($lastWrite.ToString('yyyy-MM-dd HH:mm:ss')) ($([math]::Round($result.AgeHours, 1))h ago)"
            } else {
                $result.Message = "Profile YAML not found and SQLite unavailable"
            }
        }
    } catch {
        $result.Message = "Subscription check error: $_"
    }

    return $result
}

function Test-ConfigIntegrity {
    <#
    Checks FlClash config.yaml for structural health.
    Returns: @{ Success = $true|$false; ProxyCount = int; GroupCount = int; Status = "OK"|"WARN"|"FATAL" }
    #>
    $result = @{ Success = $false; ProxyCount = 0; GroupCount = 0; Status = "FATAL"; Message = "" }

    if (-not (Test-Path $FlClashConfig)) {
        $result.Message = "config.yaml not found at $FlClashConfig"
        return $result
    }

    try {
        $size = (Get-Item $FlClashConfig).Length
        if ($size -lt 500) {
            $result.Status = "FATAL"
            $result.Message = "config.yaml too small ($size bytes) — likely empty or corrupt"
            return $result
        }

        $lines = Get-Content $FlClashConfig -ErrorAction Stop
        $inProxies = $false; $inGroups = $false
        foreach ($line in $lines) {
            $trimmed = $line.TrimStart()
            if ($trimmed -match '^proxies\s*:') {
                $inProxies = $true; $inGroups = $false; continue
            }
            if ($trimmed -match '^proxy-groups\s*:') {
                $inGroups = $true; $inProxies = $false; continue
            }
            # New top-level key (column-0, no indentation) → exit section
            if ($line -match '^[a-zA-Z][a-zA-Z0-9_-]*\s*:' -and $line -notmatch '^\s') {
                $inProxies = $false; $inGroups = $false
            }
            if ($inProxies -and $line -match '^  - \w') {
                $result.ProxyCount++
            }
            if ($inGroups -and $line -match '^  - \w') {
                $result.GroupCount++
            }
        }

        $result.Success = $true

        if ($result.ProxyCount -eq 0) {
            $result.Status = "FATAL"
            $result.Message = "0 proxy nodes in config.yaml — subscription may have failed"
        } elseif ($result.ProxyCount -lt 5) {
            $result.Status = "WARN"
            $result.Message = "Only $($result.ProxyCount) proxy nodes — unusually few"
        } elseif ($result.GroupCount -eq 0) {
            $result.Status = "WARN"
            $result.Message = "$($result.ProxyCount) nodes but 0 proxy groups — routing may be broken"
        } else {
            $result.Status = "OK"
            $result.Message = "$($result.ProxyCount) proxy nodes, $($result.GroupCount) groups"
        }
    } catch {
        $result.Message = "Config integrity check error: $_"
    }

    return $result
}

# ================================================================
# Recovery Functions
# ================================================================

# ---- Find FlClash.exe path (4-level fallback) ----
function Find-FlClashPath {
    # 1: running process
    $proc = Get-Process -Name "FlClash" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($proc) {
        try {
            if ($proc.Path) { return $proc.Path }
        } catch {
            # Access denied (e.g., SYSTEM-owned process) — fall through
        }
    }

    # 2: Scheduled Task
    try {
        $task = Get-ScheduledTask -TaskName "FlClashAutoStart" -ErrorAction SilentlyContinue
        if ($task -and $task.Actions[0].Execute) {
            $taskPath = $task.Actions[0].Execute
            # Strip arguments if present (e.g., "C:\...\FlClash.exe" --minimized)
            if ($taskPath -match '^"([^"]+\.exe)"') {
                return $matches[1]
            } elseif ($taskPath -match '^(\S+\.exe)') {
                return $matches[1]
            }
            if (Test-Path $taskPath) { return $taskPath }
        }
    } catch {}

    # 3: Startup registry
    try {
        $startup = Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue |
            Where-Object { $_.Command -like "*FlClash*" } | Select-Object -First 1
        if ($startup) {
            $cmd = $startup.Command
            # Strip arguments (e.g., "C:\...\FlClash.exe" --minimized)
            if ($cmd -match '^"([^"]+\.exe)"') {
                return $matches[1]
            } elseif ($cmd -match '^(\S+\.exe)') {
                return $matches[1]
            }
        }
    } catch {}

    # 4: default path
    $defaultPath = "C:\Program Files\FlClash\FlClash.exe"
    if (Test-Path $defaultPath) { return $defaultPath }

    return $null
}

# ---- Restart FlClash proxy (Tier 2 recovery) ----
function Restart-FlClash {
    Write-Log "Restarting FlClash..." "WARN"

    $exePath = Find-FlClashPath
    if (-not $exePath) {
        Write-Log "Cannot find FlClash.exe — aborting" "ERROR"
        return $false
    }
    if (-not (Test-Path $exePath)) {
        Write-Log "FlClash.exe not found at: $exePath" "ERROR"
        return $false
    }
    Write-Log "FlClash path: $exePath"

    # Kill child before parent, with post-kill verification
    $coreProcs = Get-Process -Name "FlClashCore" -ErrorAction SilentlyContinue
    if ($coreProcs) {
        $coreProcs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        # Verify Core is dead
        $survivor = Get-Process -Name "FlClashCore" -ErrorAction SilentlyContinue
        if ($survivor) {
            Write-Log "FlClashCore survived first kill — force killing again" "WARN"
            $survivor | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }

    $flProcs = Get-Process -Name "FlClash" -ErrorAction SilentlyContinue
    if ($flProcs) {
        $flProcs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        # Verify FlClash is dead
        $survivor = Get-Process -Name "FlClash" -ErrorAction SilentlyContinue
        if ($survivor) {
            Write-Log "FlClash survived first kill — force killing again" "WARN"
            $survivor | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }

    # Launch FlClash with correct working directory
    $flClashDir = Split-Path $exePath -Parent
    try {
        Start-Process -FilePath $exePath -WorkingDirectory $flClashDir `
            -WindowStyle Hidden -ErrorAction Stop
        Write-Log "FlClash started (workdir: $flClashDir)"
    } catch {
        Write-Log "Failed to start FlClash: $_" "ERROR"
        return $false
    }

    # Wait for FlClashCore process to appear
    $waited = 0
    $wallStart = Get-Date
    while ($waited -lt 15) {
        Start-Sleep -Seconds 2; $waited += 2
        $core = Get-Process -Name "FlClashCore" -ErrorAction SilentlyContinue
        if ($core) { break }
    }

    # Wait for proxy to become healthy
    $waited = 0
    while ($waited -lt 30) {
        Start-Sleep -Seconds 3; $waited += 3
        if (Test-ProxyHealth) {
            $elapsed = [math]::Round(((Get-Date) - $wallStart).TotalSeconds, 0)
            Write-Log "Proxy ready after ${elapsed}s (poll: ${waited}s)"
            return $true
        }
    }

    $elapsed = [math]::Round(((Get-Date) - $wallStart).TotalSeconds, 0)
    Write-Log "Proxy not ready within ${elapsed}s" "WARN"
    return $false
}

# ---- Restart Telegram Bot only (Tier 1 recovery) ----
function Restart-TelegramBot {
    Write-Log "Restarting LianyuTelegram (bot recovery)..." "WARN"
    try {
        $out = cmd /c "nssm restart LianyuTelegram" 2>&1 | Out-String
        Write-Log "nssm restart: $($out.Trim())"
        if ($out -match "Can't open service|Access is denied|OpenService") {
            Write-Log "nssm restart FAILED (permission). Task may need RunLevel=Highest." "ERROR"
            return $false
        }
        Start-Sleep -Seconds 5
        $st = cmd /c "nssm status LianyuTelegram" 2>&1 | Out-String
        Write-Log "LianyuTelegram status: $($st.Trim())"
        if ($st -match "SERVICE_RUNNING") {
            return $true
        }
        Write-Log "LianyuTelegram not in SERVICE_RUNNING state" "WARN"
        return $false
    } catch {
        Write-Log "nssm restart failed: $_" "ERROR"
        return $false
    }
}

# ================================================================
# Main — Three-Tier Recovery with Circuit Breaker
# ================================================================

$state    = Read-State
$inCooldown = Test-InCooldown $state
$cooldownExpired = Test-CooldownExpired $state

# ---- Run proxy chain diagnostics ----
$diag = Test-ProxyChain

if ($diag.Healthy) {
    # ================================================================
    # PROXY IS HEALTHY
    # ================================================================
    Write-Log "Proxy chain: OK — all layers healthy"

    # Check if we're recovering from cooldown
    if ($inCooldown -or $state.tier2_streak -gt 0) {
        Write-Log "CIRCUIT BREAKER RESET — proxy recovered. Cooldown cleared, all counters reset." "INFO"
    }

    if ($state.bot_needs_restart) {
        # Tier 1 (SOA-005): proxy had failed, now recovered → restart Bot
        Write-Log "Proxy recovered after previous failure(s). Triggering bot restart." "WARN"
        $ok = Restart-TelegramBot
        if ($ok) {
            Write-State 0 $false 0 $null
            Write-Log "Tier 1 recovery complete. State reset."
        } else {
            Write-State 0 $true 0 $null
            Write-Log "Bot restart failed — will retry next check" "WARN"
        }
    } elseif ($state.consecutive_failures -gt 0 -or $state.tier2_streak -gt 0) {
        # Proxy self-recovered, everything was reset above
        Write-Log "Proxy recovered (unexpected). Resetting all counters."
        Write-State 0 $false 0 $null
    }
    # else: everything normal, silent
    exit 0
}

# ================================================================
# PROXY IS UNHEALTHY
# ================================================================

$state.consecutive_failures++
$state.bot_needs_restart = $true
$failures = $state.consecutive_failures

$stage = $diag.Stage

Write-Log "Proxy chain: $stage — $(if ($diag.ProcessAlive) {'Core alive'} else {'Core DEAD'}) | port=$(if ($diag.PortOpen) {'open'} else {'CLOSED'}) | TG=$(if ($diag.TelegramOK) {'OK'} else {'FAIL'}) | net=$(if ($diag.InternetOK) {'OK'} else {'FAIL'})"

# ---- If UPSTREAM_UNREACHABLE_ALL: run subscription/config checks ----
if ($stage -eq "UPSTREAM_UNREACHABLE_ALL") {
    $subAge = Test-SubscriptionAge
    Write-Log "Subscription: [$($subAge.Status)] $($subAge.Message)"
    $cfgIntegrity = Test-ConfigIntegrity
    Write-Log "Config: [$($cfgIntegrity.Status)] $($cfgIntegrity.Message)"

    # Fast-track cooldown: multiple consecutive UPSTREAM_UNREACHABLE_ALL
    $fastStrike = [int]($state.tier2_streak) + 1
    if ($fastStrike -ge $CooldownFastTrackStrike) {
        $cooldownUntil = (Get-Date).AddMinutes($CircuitCooldownMinutes).ToString("yyyy-MM-ddTHH:mm:ss")
        Write-Log "CIRCUIT BREAKER FAST-TRACK — $stage detected $fastStrike consecutive times" "CRITICAL"
        Write-Log "All upstream nodes appear unreachable. Subscription: [$($subAge.Status)] Config: [$($cfgIntegrity.Status)]" "CRITICAL"
        Write-Log "Entering COOLDOWN until $cooldownUntil. No automated Tier 2 will be attempted." "CRITICAL"
        Write-Log "Manual check: verify subscription provider and node availability." "CRITICAL"
        Write-State $failures $true $fastStrike $cooldownUntil
        exit 0  # Exit 0: watchdog functioned correctly, detected unfixable condition
    }
    Write-State $failures $true $fastStrike $null
    Write-Log "UPSTREAM_UNREACHABLE_ALL strike $fastStrike/$CooldownFastTrackStrike — skipping Tier 2 (restart won't help)" "WARN"
    exit 0
}

# ---- UPSTREAM_UNREACHABLE_TG: proxy works, only Telegram is unreachable ----
# Tier 2 (FlClash restart) is pointless here — FlClash is not the problem.
# Just record the failure and wait; Telegram may recover on its own.
if ($stage -eq "UPSTREAM_UNREACHABLE_TG") {
    Write-Log "UPSTREAM_UNREACHABLE_TG — proxy OK, Telegram API unreachable. Skipping Tier 2." "WARN"
    Write-Log "Internet through proxy is working; issue is Telegram-specific or token-related."
    Write-State $failures $true $state.tier2_streak $null
    exit 0
}

# ---- Check if circuit breaker is active ----
if ($inCooldown) {
    Write-Log "CIRCUIT BREAKER ACTIVE — Cooldown until $($state.cooldown_until). Tier 2 suppressed." "CRITICAL"
    Write-Log "Failure #$failures | reason: $stage | tier2_streak: $($state.tier2_streak)"
    Write-State $failures $true $state.tier2_streak $state.cooldown_until
    exit 0
}

if ($cooldownExpired -and $state.tier2_streak -ge $CircuitBreakerMaxTier2) {
    Write-Log "COOLDOWN EXPIRED — proxy still unhealthy after $CircuitCooldownMinutes minutes" "CRITICAL"
    Write-Log "Failure #$failures | reason: $stage | tier2_streak: $($state.tier2_streak)" "CRITICAL"
    Write-Log "MANUAL INTERVENTION REQUIRED — automated recovery exhausted" "CRITICAL"
    Write-State $failures $true $state.tier2_streak $null
    exit 0
}

# ---- Normal escalation ----
Write-Log "Proxy health check FAILED ($failures/$FailThreshold) | bot_needs_restart=$true | reason=$stage"

if ($failures -lt $FailThreshold) {
    Write-State $failures $true $state.tier2_streak $null
    Write-Log "Waiting for $FailThreshold consecutive failures before FlClash restart (currently $failures)."
    exit 0
}

# === Tier 2 (SOA-004): sustained failure → restart FlClash + Bot ===
$tier2Attempt = [int]($state.tier2_streak) + 1
Write-Log "=== TIER 2 RECOVERY (attempt $tier2Attempt/$CircuitBreakerMaxTier2): $failures consecutive failures ===" "WARN"

$recovered = Restart-FlClash
if (-not $recovered) {
    $newStreak = $tier2Attempt
    Write-Log "Tier 2 attempt $tier2Attempt FAILED. Streak: $newStreak/$CircuitBreakerMaxTier2" "ERROR"

    if ($newStreak -ge $CircuitBreakerMaxTier2) {
        # Circuit breaker opens
        $cooldownUntil = (Get-Date).AddMinutes($CircuitCooldownMinutes).ToString("yyyy-MM-ddTHH:mm:ss")
        Write-Log "==============================================" "CRITICAL"
        Write-Log "CIRCUIT BREAKER OPEN — $CircuitBreakerMaxTier2 consecutive Tier 2 failures" "CRITICAL"
        Write-Log "Proxy has been down since $($state.last_updated) with $failures consecutive failures" "CRITICAL"
        Write-Log "Further automated recovery is SUSPENDED until $cooldownUntil" "CRITICAL"
        Write-Log "Manual intervention may be required — check:" "CRITICAL"
        Write-Log "  1. Is FlClash able to start? (check Windows Event Log)" "CRITICAL"
        Write-Log "  2. Are upstream proxy nodes reachable? (check subscription provider)" "CRITICAL"
        Write-Log "  3. Is cache.db corrupt? ($FlClashDataDir\cache.db)" "CRITICAL"
        Write-Log "==============================================" "CRITICAL"
        Write-State $failures $true $newStreak $cooldownUntil
        exit 0
    } else {
        Write-State $failures $true $newStreak $null
        exit 0
    }
}

# FlClash restarted + proxy ready → restart Bot
$ok = Restart-TelegramBot
if ($ok) {
    Write-State 0 $false 0 $null
    Write-Log "Tier 2 recovery complete. Proxy + Bot restarted. State reset."
} else {
    Write-State 0 $true 0 $null
    Write-Log "Bot restart failed after FlClash recovery — will retry next check" "WARN"
}

Write-Log "=== RECOVERY DONE ==="
exit 0
