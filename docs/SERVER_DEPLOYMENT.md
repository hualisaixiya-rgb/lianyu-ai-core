# 绘梨衣 AI Core · 服务器部署文档

> 最后更新：2026-07-28  
> 服务器：Windows 10 Pro (Build 19045)  
> 项目路径：`E:\AI\lianyu-ai-core`

---

## 服务列表

| 服务 | 管理方式 | 运行账户 | 启动 | 崩溃恢复 |
|------|----------|----------|:--:|:--:|
| **LianyuAI** | NSSM | SYSTEM | 开机自动 | ✅ 自动重启 |
| **LianyuTelegram** | NSSM | huali | 开机自动 | ✅ 30s 延迟重启 |
| **FlClash** | Task Scheduler | huali | 用户登录 | ❌ 无 |

---

## NSSM 服务配置

### LianyuAI

```
nssm install LianyuAI "E:\AI\lianyu-ai-core\.venv\Scripts\python.exe"
nssm set LianyuAI AppParameters "-m app.main"
nssm set LianyuAI AppDirectory "E:\AI\lianyu-ai-core"
nssm set LianyuAI Start SERVICE_AUTO_START
nssm set LianyuAI AppExit Default Restart
nssm set LianyuAI ObjectName LocalSystem
nssm set LianyuAI AppStdout "E:\AI\logs\service_stdout.log"
nssm set LianyuAI AppStderr "E:\AI\logs\service_stderr.log"
```

### LianyuTelegram

```
nssm install LianyuTelegram "E:\AI\lianyu-ai-core\.venv\Scripts\python.exe"
nssm set LianyuTelegram AppParameters "-u scripts/run_telegram.py"
nssm set LianyuTelegram AppDirectory "E:\AI\lianyu-ai-core"
nssm set LianyuTelegram Start SERVICE_AUTO_START
nssm set LianyuTelegram AppExit Default Restart
nssm set LianyuTelegram AppRestartDelay 30000
nssm set LianyuTelegram ObjectName ".\huali"
nssm set LianyuTelegram AppStdout "E:\AI\logs\telegram_stdout.log"
nssm set LianyuTelegram AppStderr "E:\AI\logs\telegram_stderr.log"
```

---

## 项目路径

```
E:\AI\
├── lianyu-ai-core\          # 项目代码（Git 管理）
│   ├── .venv\               # Python 虚拟环境
│   ├── .env                 # 环境变量（gitignored）
│   ├── data\lianyu.db       # SQLite 数据库
│   ├── archives\            # 对话归档 / 错误日志
│   └── logs\                # 项目内日志（如有）
├── logs\                    # NSSM 服务日志
│   ├── service_stdout.log   # LianyuAI stdout
│   ├── service_stderr.log   # LianyuAI stderr
│   ├── telegram_stdout.log  # LianyuTelegram stdout
│   └── telegram_stderr.log  # LianyuTelegram stderr
├── backups\                 # 备份存档
├── deploy\                  # 部署脚本
├── config\                  # 服务器配置
├── models\                  # 本地模型
└── docs\                    # 运维文档
```

---

## 日志路径

| 服务 | 日志文件 |
|------|----------|
| LianyuAI | `E:\AI\logs\service_stdout.log` · `E:\AI\logs\service_stderr.log` |
| LianyuTelegram | `E:\AI\logs\telegram_stdout.log` · `E:\AI\logs\telegram_stderr.log` |
| 应用日志 | loguru 输出到各服务的 stderr 文件 |

---

## 环境变量 (`.env`)

| 变量 | 说明 | 状态 |
|------|------|:--:|
| `AI_LLM_BASE_URL` | DeepSeek API 地址 | ✅ |
| `AI_LLM_API_KEY` | API Key | ✅ |
| `AI_LLM_MODEL` | 模型名（deepseek-v4-flash） | ✅ |
| `APP_DEBUG` | 调试模式（false） | ✅ |
| `APP_LOG_LEVEL` | 日志级别（INFO） | ✅ |
| `CHARACTER_NAME` | 角色名（eryi） | ✅ |
| `DATABASE_URL` | SQLite 路径 | ✅ |
| `TELEGRAM_BOT_TOKEN` | Bot Token | ✅ |
| `TELEGRAM_PROXY` | HTTP 代理地址 | ✅ |

---

## Python 环境

| 组件 | 版本 | 路径 |
|------|------|------|
| Python | 3.12.10 | `C:\Users\huali\AppData\Local\Programs\Python\Python312\` |
| uv | 0.11.26 | `C:\Users\huali\.local\bin\` |
| NSSM | 2.24 | winget 安装 |

---

## 启停命令

```powershell
# 查看状态
nssm status LianyuAI
nssm status LianyuTelegram

# 重启服务 (管理员)
nssm restart LianyuAI
nssm restart LianyuTelegram

# 停止服务 (管理员)
nssm stop LianyuAI
nssm stop LianyuTelegram

# 启动服务 (管理员)
nssm start LianyuAI
nssm start LianyuTelegram

# 查看日志
Get-Content "E:\AI\logs\telegram_stderr.log" -Tail 20

# 更新代码
cd E:\AI\lianyu-ai-core
git pull
uv sync --no-dev
nssm restart LianyuAI
nssm restart LianyuTelegram

# 健康检查
curl http://localhost:8000/api/v1/health

# Chat 测试
curl -X POST http://localhost:8000/api/v1/chat -H "Content-Type: application/json" -d '{"user_id":"test","message":"你好"}'
```

---

## 故障排查

### Bot 不回复

```powershell
# 1. 检查服务状态
nssm status LianyuTelegram

# 2. 查看日志末尾
Get-Content "E:\AI\logs\telegram_stderr.log" -Tail 20

# 3. 检查代理
netstat -ano | findstr 7890

# 4. 测试 Telegram API
curl -x http://127.0.0.1:7890 https://api.telegram.org/bot<TOKEN>/getMe

# 5. 检查 pending
curl -x http://127.0.0.1:7890 https://api.telegram.org/bot<TOKEN>/getWebhookInfo

# 6. 重启 Bot
nssm restart LianyuTelegram
```

### AI 不回复

```powershell
# 1. 检查服务
nssm status LianyuAI

# 2. 查看日志
Get-Content "E:\AI\logs\service_stderr.log" -Tail 20

# 3. 测试 API
curl http://localhost:8000/api/v1/health
```

---

## 注意事项

1. `.env` 在 `.gitignore` 中，Git 不会跟踪
2. `data/lianyu.db` 不可删除
3. 修改配置前先备份
4. 不要在服务器直接修改业务代码
5. 更新来自 `git pull`，开发在另一台主机
