# ============================================================
# LianyuDeploy 一键安装脚本
# 在服务器上以管理员身份运行此脚本。
#
# 使用方式（管理员 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File install_deploy.ps1
#
# 前置条件：
#   1. 项目已克隆到本地
#   2. Python 虚拟环境已创建（.venv）
#   3. .env.deploy 已配置 WEBHOOK_SECRET
# ============================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

# ---- 动态检测路径 ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\.."

$PythonExe = "$ProjectRoot\.venv\Scripts\python.exe"
$WebhookScript = "$ScriptDir\webhook_server.py"
$EnvDeploy = "$ProjectRoot\.env.deploy"

Write-Host "========================================"
Write-Host "  LianyuDeploy 自动部署安装"
Write-Host "========================================"
Write-Host "项目路径: $ProjectRoot"
Write-Host "Python:   $PythonExe"
Write-Host ""

# ---- 检查前置条件 ----
$errors = @()

if (-not (Test-Path $PythonExe)) {
    $errors += "❌ 虚拟环境不存在: $PythonExe`n   请先运行: uv sync --no-dev"
}

if (-not (Test-Path $WebhookScript)) {
    $errors += "❌ webhook_server.py 不存在，请先 git pull"
}

if (-not (Test-Path $EnvDeploy)) {
    $errors += "❌ .env.deploy 不存在`n   请在项目根目录创建 .env.deploy 并配置 WEBHOOK_SECRET"
} else {
    $secret = Get-Content $EnvDeploy -Encoding UTF8 | Select-String "WEBHOOK_SECRET" | ForEach-Object { $_.Line }
    if (-not $secret -or $secret -match "填入|placeholder|changeme") {
        $errors += "❌ .env.deploy 中 WEBHOOK_SECRET 未正确配置"
    }
}

if (-not (Get-Command "nssm" -ErrorAction SilentlyContinue)) {
    $errors += "❌ NSSM 未安装`n   安装: winget install nssm"
}

if ($errors.Count -gt 0) {
    Write-Host ("`n" + ($errors -join "`n`n") + "`n") -ForegroundColor Red
    Write-Host "请修复以上问题后重新运行。" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ 前置条件检查通过" -ForegroundColor Green
Write-Host ""

# ---- 检查是否已安装 ----
$existing = nssm status LianyuDeploy 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "检测到已存在 LianyuDeploy 服务（状态: $existing）" -ForegroundColor Yellow
    Write-Host "将先移除旧服务..." -ForegroundColor Yellow
    nssm stop LianyuDeploy 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    nssm remove LianyuDeploy confirm 2>&1 | Out-Null
    Write-Host "旧服务已移除" -ForegroundColor Green
}

# ---- 安装 NSSM 服务 ----
Write-Host "安装 NSSM 服务 LianyuDeploy..." -ForegroundColor Cyan

$logDir = "$ProjectRoot\logs\deploy"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# NSSM install
nssm install LianyuDeploy $PythonExe
nssm set LianyuDeploy AppParameters "-u $WebhookScript"
nssm set LianyuDeploy AppDirectory $ProjectRoot
nssm set LianyuDeploy Start SERVICE_AUTO_START
nssm set LianyuDeploy AppExit Default Restart
nssm set LianyuDeploy AppRestartDelay 5000

# NSSM 日志统一输出到项目 logs/
$nssmLogDir = "$ProjectRoot\logs"
nssm set LianyuDeploy AppStdout "$nssmLogDir\webhook_stdout.log"
nssm set LianyuDeploy AppStderr "$nssmLogDir\webhook_stderr.log"

Write-Host "✅ NSSM 服务配置完成" -ForegroundColor Green

# ---- 启动服务 ----
Write-Host "启动 LianyuDeploy..." -ForegroundColor Cyan
nssm start LianyuDeploy
Start-Sleep -Seconds 3

$status = nssm status LianyuDeploy 2>&1
Write-Host "服务状态: $status" -ForegroundColor $(if ($status -match "RUNNING") { "Green" } else { "Red" })

# ---- 验证 ----
Write-Host ""
Write-Host "========================================"
Write-Host "  安装完成"
Write-Host "========================================"
Write-Host ""
Write-Host "项目路径:   $ProjectRoot"
Write-Host "Webhook端口: 9000"
Write-Host ""
Write-Host "验证命令:"
Write-Host "  nssm status LianyuDeploy"
Write-Host "  curl http://localhost:9000/health"
Write-Host ""
Write-Host "日志路径:"
Write-Host "  Webhook:  $logDir\webhook.log"
Write-Host "  部署:    $logDir\deploy.log"
Write-Host "  NSSM:    $nssmLogDir\webhook_stdout.log"
Write-Host ""
Write-Host "接下来:"
Write-Host "  1. 配置 Cloudflare Tunnel（见 docs/WEBHOOK_DEPLOY.md）"
Write-Host "  2. 在 GitHub 添加 Webhook"
Write-Host ""

nssm status LianyuDeploy
