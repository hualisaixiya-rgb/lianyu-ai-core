# 绘梨衣 AI Core · 服务器运维手册

> 服务器：Windows 10 Pro | 项目：`E:\AI\lianyu-ai-core`  
> 最后更新：2026-07-28

---

## 一、服务器架构

```
Windows 开机
├── LianyuAI (NSSM / SYSTEM)
│   └── FastAPI → 0.0.0.0:8000
│
├── LianyuTelegram (NSSM / huali)
│   └── python-telegram-bot → 代理就绪后连接
│
└── 用户 huali 登录
    └── FlClash (Task Scheduler)
        └── HTTP 代理 → 127.0.0.1:7890
```

| 服务 | 管理 | 账户 | 启动 | 端口 |
|------|------|------|:--:|------|
| LianyuAI | NSSM | SYSTEM | 开机自动 | 8000 |
| LianyuTelegram | NSSM | huali | 开机自动 | — |
| FlClash | Task Scheduler | huali | 用户登录 | 7890 |

---

## 二、数据位置

### 运行数据（不进入 Git）

| 数据 | 路径 | 说明 |
|------|------|------|
| SQLite 数据库 | `E:\AI\lianyu-ai-core\data\lianyu.db` | 用户、消息、记忆、关系数据 |
| 对话归档 | `E:\AI\lianyu-ai-core\archives\conversations\` | 按 YYYY/MM/YYYY-MM-DD.md 组织 |
| 记忆事件 | `E:\AI\lianyu-ai-core\archives\memory_events\` | JSON 行格式 |
| 错误归档 | `E:\AI\lianyu-ai-core\archives\errors\` | 按日期 .log |
| 服务日志 | `E:\AI\logs\` | NSSM stdout/stderr |

> 以上数据**仅存在于服务器**，不在 Git 仓库中，不同步到开发机。

### 代码（Git 管理）

| 路径 | 说明 |
|------|------|
| `E:\AI\lianyu-ai-core\` | 项目根目录，`git pull` 同步 |

---

## 三、日常运维

### 更新代码

```powershell
cd E:\AI\lianyu-ai-core
git pull
```

### 更新依赖（pyproject.toml 变化时）

```powershell
cd E:\AI\lianyu-ai-core
uv sync --no-dev
```

### 重启服务

```powershell
# 需要管理员权限
nssm restart LianyuAI
nssm restart LianyuTelegram
```

### 状态检查

```powershell
nssm status LianyuAI
nssm status LianyuTelegram
curl http://localhost:8000/api/v1/health
```

### 一键更新

```powershell
cd E:\AI\lianyu-ai-core
git pull
uv sync --no-dev
nssm restart LianyuAI
nssm restart LianyuTelegram
nssm status LianyuAI
nssm status LianyuTelegram
curl http://localhost:8000/api/v1/health
```

---

## 四、故障排查

### 1. 服务状态

```powershell
nssm status LianyuAI
nssm status LianyuTelegram
```

### 2. 查看日志

```powershell
# AI Core 日志
Get-Content "E:\AI\logs\service_stderr.log" -Tail 30

# Telegram Bot 日志
Get-Content "E:\AI\logs\telegram_stderr.log" -Tail 30
```

### 3. Telegram 连接检查

```powershell
# 检查代理
netstat -ano | findstr ":7890.*LISTEN"

# 测试 Telegram API
curl -x http://127.0.0.1:7890 https://api.telegram.org/bot<TOKEN>/getMe

# 检查待处理消息
curl -x http://127.0.0.1:7890 https://api.telegram.org/bot<TOKEN>/getWebhookInfo
```

### 4. 常见问题

| 症状 | 可能原因 | 操作 |
|------|----------|------|
| Bot 不回复 | 代理未启动（FlClash 未登录） | 确认 FlClash 已打开 |
| AI 返回 "……" | LLM API 调用失败 | 查看 `service_stderr.log`，检查 API Key |
| Health 不通 | LianyuAI 未运行 | `nssm restart LianyuAI` |
| 端口占用 | 残留进程 | 检查 Python 进程数量 |

---

## 五、主机 / 服务器职责划分

| 职责 | 主机 | 服务器 |
|------|:--:|:--:|
| 编写代码 | ✅ | ❌ |
| 修改架构 | ✅ | ❌ |
| 新增功能 | ✅ | ❌ |
| 运行测试 | ✅ | ⚠️ 基础验证 |
| Git 管理 | ✅ | ❌ 仅 `pull` |
| | | |
| 运行 AI 服务 | ❌ | ✅ |
| 保存聊天数据 | ❌ | ✅ |
| 部署更新 | ❌ | ✅ |
| 查看日志 | ❌ | ✅ |
| 故障排查 | ❌ | ✅ |

### 代码问题处理流程

```
服务器发现问题
  → 查看日志，定位原因
  → 报告给主机
  → 主机修改代码、测试、git push
  → 服务器 git pull 更新
```

> **服务器永远不直接修改业务代码。**

---

## 六、注意事项

- `.env` 包含 API Key，在 `.gitignore` 中，不上传 Git
- `data/lianyu.db` 不可删除，是唯一运行数据库
- 任何配置修改前先备份
- 服务重启需管理员权限
- NSSM 配置已冻结，不随意修改
