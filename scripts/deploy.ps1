# ============================================================
# Auto-Deploy Script
# Triggered by webhook_server.py after GitHub push verification
#
# Usage (called by webhook):
#   powershell -File deploy.ps1 -TargetHead <commit_hash>
#
# Manual deploy:
#   powershell -File deploy.ps1 -TargetHead main
# ============================================================

param(
    [string]$TargetHead = ""
)

$ErrorActionPreference = "Stop"

# ---- Detect project path dynamically ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\.."

# ---- Log directory ----
$LogDir = "$ProjectRoot\logs\deploy"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$DeployLog = "$LogDir\deploy.log"

# ---- Lock files ----
$LockFile = "$ProjectRoot\.deploy.lock"
$LastHeadFile = "$ProjectRoot\.deploy.last_head"

# ---- NSSM service list ----
$Services = @("LianyuAI", "LianyuTelegram")

# ---- Tool auto-detection (SYSTEM account may not have user PATH) ----
$UvExe = $null
$uvCandidates = @(
    "uv",                                          # PATH
    "C:\Users\huali\.local\bin\uv.exe",            # default uv installer location
    "$env:USERPROFILE\.local\bin\uv.exe",          # current user
    "$ProjectRoot\.venv\Scripts\uv.exe"            # project venv (if uv self-installed)
)
foreach ($candidate in $uvCandidates) {
    try {
        $check = cmd /c "$candidate --version 2>&1"
        if ($LASTEXITCODE -eq 0) {
            $UvExe = $candidate
            break
        }
    } catch {}
}
if (-not $UvExe) {
    Write-Host "[FATAL] uv not found. Checked: $($uvCandidates -join ', ')"
    exit 1
}

$NssmExe = $null
$nssmCandidates = @(
    "nssm",                                        # PATH
    "$env:ProgramFiles\nssm\win64\nssm.exe",
    "${env:ProgramFiles(x86)}\nssm\win64\nssm.exe"
)
# Search winget-style installs (path varies by version)
$wingetBase = "C:\Users\huali\AppData\Local\Microsoft\WinGet\Packages"
if (Test-Path $wingetBase) {
    $nssmDirs = Get-ChildItem -Path $wingetBase -Directory -Filter "NSSM.NSSM_*" -ErrorAction SilentlyContinue
    foreach ($dir in $nssmDirs) {
        $exe = Get-ChildItem -Path $dir.FullName -Recurse -Filter "nssm.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($exe) { $nssmCandidates += $exe.FullName }
    }
}
# Also check huali LOCALAPPDATA directly
$hualiLocal = "C:\Users\huali\AppData\Local\Microsoft\WinGet\Packages"
if (Test-Path $hualiLocal) {
    $nssmDirs = Get-ChildItem -Path $hualiLocal -Directory -Filter "NSSM.NSSM_*" -ErrorAction SilentlyContinue
    foreach ($dir in $nssmDirs) {
        $exe = Get-ChildItem -Path $dir.FullName -Recurse -Filter "nssm.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($exe -and $nssmCandidates -notcontains $exe.FullName) { $nssmCandidates += $exe.FullName }
    }
}
# Also try Get-Command (works if PS can resolve it)
try {
    $psNssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
    if ($psNssm) { $nssmCandidates = @($psNssm) + $nssmCandidates }
} catch {}
foreach ($candidate in $nssmCandidates) {
    try {
        $check = cmd /c "$candidate version 2>&1"
        if ($LASTEXITCODE -eq 0) {
            $NssmExe = $candidate
            break
        }
    } catch {}
}
if (-not $NssmExe) {
    Write-Host "[FATAL] nssm not found. Checked: $($nssmCandidates -join ', ')"
    exit 1
}

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Level] $Message"
    Write-Host $line
    Add-Content -Path $DeployLog -Value $line -Encoding UTF8
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
            Write-Log "  Waiting for service... ($i/$Retries)"
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
            Write-Log "[OK] Chat smoke test passed: $preview"
            return $true
        }
        Write-Log "[WARN] Chat returned empty reply" "WARN"
        return $false
    } catch {
        Write-Log "[WARN] Chat smoke test failed: $_" "WARN"
        return $false
    }
}

function Restart-ServiceSafe {
    param([string]$ServiceName)
    Write-Log "Restarting NSSM service: $ServiceName"
    try {
        $status = cmd /c "$NssmExe status $ServiceName 2>&1"
        Write-Log "  Current status: $status"
        $output = cmd /c "$NssmExe restart $ServiceName 2>&1"
        $exit = $LASTEXITCODE
        foreach ($line in $output) { Write-Log "  $line" }
        if ($exit -ne 0) { throw "nssm restart failed (exit=$exit)" }
        Write-Log "  [OK] $ServiceName restarted"
    } catch {
        Write-Log "[FAIL] Restart $ServiceName failed: $_" "ERROR"
        throw
    }
}

function Restore-Git {
    param([string]$OldHead)
    $headShort = $OldHead.Substring(0, [Math]::Min(8, $OldHead.Length))
    Write-Log "[ROLLBACK] Restoring to $headShort"
    Set-Location $ProjectRoot
    $output = cmd /c "git reset --hard $OldHead 2>&1"
    $exit = $LASTEXITCODE
    foreach ($line in $output) { Write-Log "  $line" }
    if ($exit -ne 0) {
        $raw = ($output | Out-String).Trim()
        Write-Log "[FAIL] Rollback failed! (exit=$exit) $raw" "ERROR"
    }
    try { cmd /c "git stash pop 2>&1" | Out-Null } catch {}
}

# ============================================================
# Begin Deployment
# ============================================================

Write-Log "========== START DEPLOY =========="

# 0. Enter project directory
Set-Location $ProjectRoot
Write-Log "Project root: $ProjectRoot"
Write-Log "uv: $UvExe"
Write-Log "nssm: $NssmExe"

# 0.5 Get current HEAD (for rollback)
$rawHead = cmd /c "git rev-parse HEAD 2>&1"
$headExit = $LASTEXITCODE
$OldHead = ($rawHead | Out-String).Trim()
if ($headExit -ne 0) {
    Write-Log "[FAIL] Cannot get current HEAD (exit=$headExit): $OldHead" "ERROR"
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 1
}
Write-Log "Current HEAD: $($OldHead.Substring(0, [Math]::Min(8, $OldHead.Length)))"

# 0.6 Skip if TargetHead equals current HEAD
if ($TargetHead -and $TargetHead -eq $OldHead) {
    Write-Log "[SKIP] HEAD unchanged ($($OldHead.Substring(0, 8))), skipping"
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 0
}

# 1. git stash + git pull
Write-Log "[1/5] git pull..."
$Stashed = $false
try {
    $stashMsg = "auto-deploy-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    $stashOutput = cmd /c "git stash push -m `"$stashMsg`" 2>&1"
    $stashExit = $LASTEXITCODE
    if ($stashExit -eq 0 -and ($stashOutput | Out-String) -notmatch "No local changes") {
        $Stashed = $true
        Write-Log "  Local changes stashed"
    }
} catch { Write-Log "  No local changes, skip stash" }

try {
    $pullOutput = cmd /c "git pull origin main 2>&1"
    $pullExit = $LASTEXITCODE
    foreach ($line in $pullOutput) { Write-Log "  $line" }
    if ($pullExit -ne 0) {
        $raw = ($pullOutput | Out-String).Trim()
        throw "git pull failed (exit=$pullExit)`n--- git output ---`n$raw`n--- end ---"
    }
    Write-Log "[OK] git pull done"
} catch {
    Write-Log "[FAIL] git pull failed: $_" "ERROR"
    if ($Stashed) { try { cmd /c "git stash pop 2>&1" | Out-Null } catch {} }
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 1
}

# 1.5 Confirm HEAD changed
$rawNew = cmd /c "git rev-parse HEAD 2>&1"
$newExit = $LASTEXITCODE
$NewHead = ($rawNew | Out-String).Trim()
if ($newExit -ne 0) {
    Write-Log "[WARN] Cannot get new HEAD after pull (exit=$newExit): $NewHead" "WARN"
}
if ($NewHead -eq $OldHead) {
    Write-Log "[SKIP] HEAD unchanged after git pull, skipping remaining steps"
    if ($Stashed) { try { cmd /c "git stash pop 2>&1" | Out-Null } catch {} }
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 0
}
Write-Log "  New HEAD: $($NewHead.Substring(0, [Math]::Min(8, $NewHead.Length)))"

# 2. uv sync
Write-Log "[2/5] uv sync --no-dev..."
try {
    $uvOutput = cmd /c "$UvExe sync --no-dev 2>&1"
    $uvExit = $LASTEXITCODE
    foreach ($line in $uvOutput) { Write-Log "  $line" }
    if ($uvExit -ne 0) {
        $raw = ($uvOutput | Out-String).Trim()
        throw "uv sync failed (exit=$uvExit)`n--- raw ---`n$raw`n--- end ---"
    }
    Write-Log "[OK] uv sync done"
} catch {
    Write-Log "[FAIL] uv sync failed: $_" "ERROR"
    Restore-Git -OldHead $OldHead
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 1
}

# 3. Restart services
Write-Log "[3/5] Restarting services..."
$RestartErrors = @()
foreach ($svc in $Services) {
    try {
        $svcStatusOutput = cmd /c "$NssmExe status $svc 2>&1"
        $svcStatusText = ($svcStatusOutput | Out-String).Trim()
        if ($svcStatusText -match "SERVICE_RUNNING|SERVICE_STOPPED") {
            Restart-ServiceSafe -ServiceName $svc
        } else {
            Write-Log "  [WARN] $svc status abnormal: $svcStatusText, attempting restart" "WARN"
            Restart-ServiceSafe -ServiceName $svc
        }
    } catch {
        $RestartErrors += "$svc : $_"
    }
}
if ($RestartErrors.Count -gt 0) {
    Write-Log "[FAIL] Service restart errors: $($RestartErrors -join '; ')" "ERROR"
}

# 4. Health check
Write-Log "[4/5] Health check..."
$healthy = Wait-Healthy -Retries 3 -Interval 5
if (-not $healthy) {
    Write-Log "[FAIL] Health check not passing" "ERROR"
    Restore-Git -OldHead $OldHead
    foreach ($svc in $Services) {
        try { cmd /c "$NssmExe restart $svc 2>&1" | Out-Null } catch {}
    }
    Remove-Item -Force $LockFile -ErrorAction SilentlyContinue
    exit 1
}

# 5. Chat API smoke test
Write-Log "[5/5] Chat API smoke test..."
$smokeOk = Test-ChatApi -Timeout 30

# ============================================================
# Complete
# ============================================================

# Save successful HEAD
$rawFinal = cmd /c "git rev-parse HEAD 2>&1"
$FinalHead = ($rawFinal | Out-String).Trim()
$FinalHead | Out-File -FilePath $LastHeadFile -Encoding utf8 -NoNewline

# Release lock
Remove-Item -Force $LockFile -ErrorAction SilentlyContinue

Write-Log "========== DEPLOY COMPLETE =========="
Write-Log "HEAD: $($FinalHead.Substring(0, [Math]::Min(8, $FinalHead.Length)))"
Write-Log "Health: [OK]  |  Smoke: $(if ($smokeOk) {'[OK]'} else {'[WARN]'})"

exit 0
