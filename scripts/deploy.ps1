# ============================================================
# 自动部署脚本
# 由 webhook_server.py 在 GitHub push 事件验证通过后触发
#
# 使用方式（由 webhook 自动调用）：
#   powershell -File deploy.ps1 -TargetHead <commit_hash>
#
# 手动部署：
#   powershell -File deploy.ps1 -TargetHead main
# ============================================================

param(
    [string]$TargetHead = ""
)

$ErrorActionPreference = "Stop"

# ---- 动态检测项目路径（不写死） ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\.."

# ---- 日志目录 ----
$LogDir = "$ProjectRoot\logs\deploy"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$DeployLog = "$LogDir\deploy.log"

# ---- 锁文件 ----
$LockFile = "$ProjectRoot\.deploy.lock"
$LastHeadFile = "$ProjectRoot\.deploy.last_head"

# ---- NSSM 服务列表（从 config/deploy.yaml 读取的可扩展列表） ----
$Services = @("LianyuAI", "LianyuTelegram")

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Level] $Message"
    Write-Host $line
    Add-Content -Path $DeployLog -Value $line -Encoding UTF8
}

function Invoke-CommandSafe {
    param([string]$Command, [string]$Label)
    Write-Log "$Label..."
    try {
        Invoke-Expression $Command 2>&1 | ForEach-Object { Write-Log "  $_" }
        if ($LASTEXITCODE -ne 0) { throw "$Label 失败 (exit=$LASTEXITCODE)" }
        Write-Log "✅ $Label 完成"
    } catch {
        Write-Log "❌ $Label 失败: $_" "ERROR"
        throw
    }
}

function Wait-Healthy {
    param([int]$Retries = 3, [int]$Interval = 5)
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -TimeoutSec 10 -UseBasicParsing
            if ($r.StatusCode -eq 200 -and ($r.Content | ConvertFrom-Json).status -eq "ok") {
                return $true
            }
        } catch {}
        if ($i -lt $Retries) {
            Write-Log "  等待服务就绪... ($i/$Retries)"
            Start-Sleep -Seconds $Interval
        }
    }
    try {
        Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -TimeoutSec 5 -UseBasicParsing | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-ChatApi {
    param([int]$Timeout = 30)
    try {
        $body = @{user_id="deploy-smoke"; message="ping"} | ConvertTo-Json
        $r = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/chat" `
              -Method Post -Body $body -ContentType "application/json" -TimeoutSec $Timeout
        if ($r.reply -and $r.reply.Length -gt 0) {
            $preview = $r.reply.Substring(0, [Math]::Min(50, $r.reply.Length))
            Write-Log "✅ Chat 冒烟测试通过: $preview"
            return $true
        }
        Write-Log "⚠️  Chat 返回空 reply" "WARN"
        return $false
    } catch {
        Write-Log "⚠️  Chat 冒烟测试失败: $_" "WARN"
        return $false
    }
}

function Restart-ServiceSafe {
    param([string]$ServiceName)
    Write-Log "重启 NSSM 服务: $ServiceName"
    try {
        $status = nssm status $ServiceName 2>&1
        Write-Log "  当前状态: $status"
        nssm restart $ServiceName 2>&1 | ForEach-Object { Write-Log "  $_" }
        if ($LASTEXITCODE -ne 0) { throw "nssm restart 失败" }
        Write-Log "  ✅ $ServiceName 已重启"
    } catch {
        Write-Log "❌ 重启 $ServiceName 失败: $_" "ERROR"
        throw
    }
}

function Restore-Git {
    param([string]$OldHead)
    Write-Log "↩️  回滚到 $($OldHead.Substring(0, [Math]::Min(8, $OldHead.Length)))"
    Set-Location $ProjectRoot
    git reset --hard $OldHead 2>&1 | ForEach-Object { Write-Log "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "❌ 回滚失败！请手动检查！" "ERROR"
    }
    try { git stash pop 2>&1 | Out-Null } catch {}
}

# ════════════════════════════════════════════════════════
# 开始部署
# ════════════════════════════════════════════════════════

Write-Log "══════════ 开始部署 ══════════"

# 0. 进入项目目录
Set-Location $ProjectRoot
Write-Log "项目路径: $ProjectRoot"

# 0.5 获取当前 HEAD（用于回滚）
$OldHead = git rev-parse HEAD 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Log "❌ 无法获取当前 HEAD，中止" "ERROR"
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 1
}
Write-Log "当前 HEAD: $($OldHead.Substring(0, [Math]::Min(8, $OldHead.Length)))"

# 0.6 如果 TargetHead 和当前 HEAD 相同 → 跳过（webhook 已做去重，这里是二次保障）
if ($TargetHead -and $TargetHead -eq $OldHead) {
    Write-Log "⏭️  HEAD 未变化 ($($OldHead.Substring(0, 8)))，跳过部署"
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 0
}

# 1. git stash（保留本地未提交修改） + git pull
Write-Log "[1/5] git pull..."
$Stashed = $false
try {
    $stashResult = git stash push -m "auto-deploy-$(Get-Date -Format 'yyyyMMdd-HHmmss')" 2>&1
    if ($LASTEXITCODE -eq 0 -and $stashResult -notmatch "No local changes") {
        $Stashed = $true
        Write-Log "  已 stash 本地修改"
    }
} catch { Write-Log "  无本地修改，跳过 stash" }

try {
    git pull origin main 2>&1 | ForEach-Object { Write-Log "  $_" }
    if ($LASTEXITCODE -ne 0) { throw "git pull 失败" }
} catch {
    Write-Log "❌ git pull 失败" "ERROR"
    if ($Stashed) { try { git stash pop 2>&1 | Out-Null } catch {} }
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 1
}

# 1.5 再次确认 HEAD 已变化
$NewHead = git rev-parse HEAD 2>&1
if ($NewHead -eq $OldHead) {
    Write-Log "⏭️  git pull 后 HEAD 未变化，跳过后续步骤"
    if ($Stashed) { try { git stash pop 2>&1 | Out-Null } catch {} }
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 0
}
Write-Log "  新 HEAD: $($NewHead.Substring(0, [Math]::Min(8, $NewHead.Length)))"

# 2. uv sync
Write-Log "[2/5] uv sync --no-dev..."
try {
    uv sync --no-dev 2>&1 | ForEach-Object { Write-Log "  $_" }
    if ($LASTEXITCODE -ne 0) { throw "uv sync 失败" }
} catch {
    Write-Log "❌ uv sync 失败" "ERROR"
    Restore-Git -OldHead $OldHead
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 1
}

# 3. 重启服务
Write-Log "[3/5] 重启服务..."
$RestartErrors = @()
foreach ($svc in $Services) {
    try {
        $status = nssm status $svc 2>&1
        if ($status -match "SERVICE_RUNNING|SERVICE_STOPPED") {
            Restart-ServiceSafe -ServiceName $svc
        } else {
            Write-Log "  ⚠️  $svc 状态异常: $status，尝试重启" "WARN"
            Restart-ServiceSafe -ServiceName $svc
        }
    } catch {
        $RestartErrors += "$svc : $_"
    }
}
if ($RestartErrors.Count -gt 0) {
    Write-Log "❌ 服务重启失败: $($RestartErrors -join '; ')" "ERROR"
}

# 4. 健康检查
Write-Log "[4/5] 健康检查..."
$healthy = Wait-Healthy -Retries 3 -Interval 5
if (-not $healthy) {
    Write-Log "❌ 健康检查不通过" "ERROR"
    Restore-Git -OldHead $OldHead
    foreach ($svc in $Services) {
        try { nssm restart $svc 2>&1 | Out-Null } catch {}
    }
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 1
}

# 5. Chat API 冒烟测试
Write-Log "[5/5] Chat API 冒烟测试..."
$smokeOk = Test-ChatApi -Timeout 30

# ════════════════════════════════════════════════════════
# 完成
# ════════════════════════════════════════════════════════

# 保存成功 HEAD
$FinalHead = git rev-parse HEAD
$FinalHead | Out-File -FilePath $LastHeadFile -Encoding utf8 -NoNewline

# 释放锁
Remove-Item -Force $LockFile -ErrorAction SilentlyContinue

Write-Log "══════════ 部署完成 ══════════"
Write-Log "HEAD: $($FinalHead.Substring(0, [Math]::Min(8, $FinalHead.Length)))"
Write-Log "健康检查: ✅  |  冒烟测试: $(if ($smokeOk) {'✅'} else {'⚠️'})"

exit 0
