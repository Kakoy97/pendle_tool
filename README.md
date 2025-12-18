# Pendle Tool

Pendle 项目监控工具，用于监控 Pendle 项目价格变化、追踪聪明钱钱包交易、管理项目列表等。

## 项目概要

- **后端**：Python + FastAPI，提供 RESTful API 和前端静态文件服务
- **前端**：原生 HTML/JavaScript，已整合到后端，无需单独启动
- **数据库**：默认采用 SQLite（`sqlite+aiosqlite`），可切换至 PostgreSQL
- **功能**：
  - Pendle 项目监控和管理
  - 价格测试和自动更新
  - 聪明钱钱包追踪
  - Telegram 通知（高价值机会、APR 变化等）
  - 项目历史记录

## 目录结构

```
pendle-tool/
├── backend/
│   ├── app/
│   │   ├── core/            # 配置、数据库连接
│   │   ├── models/          # SQLAlchemy 模型
│   │   ├── routers/         # FastAPI 路由
│   │   ├── schemas/         # Pydantic schema
│   │   ├── services/        # 业务逻辑服务
│   │   └── tasks/           # APScheduler 定时任务
│   ├── frontend/            # 前端静态文件（HTML/CSS/JS）
│   ├── scripts/             # 工具脚本
│   ├── requirements.txt     # Python 依赖
│   ├── .env.example         # 环境变量模板
│   └── pendle_tool.db      # SQLite 数据库（自动创建）
└── README.md
```

## 环境搭建

### 1. 系统要求

- Python 3.9+
- pip（Python 包管理器）

### 2. 克隆项目

```bash
git clone <repository-url>
cd pendle-tool-github
```

### 3. 创建虚拟环境

**Windows (PowerShell):**
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
```

**Linux/Mac:**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

## 环境变量配置

### 1. 创建 .env 文件

```bash
# Windows
Copy-Item .env.example .env

# Linux/Mac
cp .env.example .env
```

### 2. 配置 Telegram 通知

#### 获取 Bot Token

1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot` 创建新机器人
3. 按照提示设置机器人名称和用户名
4. 获取 Bot Token（格式：`123456789:ABCdefGHIjklMNOpqrsTUVwxyz`）

#### 获取 Chat ID

**使用 Bot API**

1. 将你的 Bot 添加到目标群组或频道
2. 在群组中发送任意一条消息（或让 Bot 发送一条消息）
3. 访问以下 URL（将 `<YOUR_BOT_TOKEN>` 替换为你的 Bot Token）：
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
4. 在返回的 JSON 中找到 `"chat":{"id":-1001234567890}`，这个数字就是 Chat ID



```bash
python -m scripts.get_chat_id
```

> **注意**：现在只使用 Bot API，不再需要 Telethon。`.telegram` 文件夹可以删除。

#### 配置 .env 文件

**必需配置：**
```env
# Bot Token（从 @BotFather 获取）
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Chat ID（接收通知的群组或频道 ID）
TELEGRAM_BOT_CHAT_ID=-1001234567890
```

**可选配置：**
```env
# 项目过滤配置：最小 24h 交易量（美元），低于此值的项目会被过滤
# 默认值：3000
PROJECT_MIN_VOLUME_24H=3000

# 代理配置（如果需要代理访问 Telegram）
# TELEGRAM_PROXY_TYPE=mtproxy  # 或 socks5, http
# TELEGRAM_PROXY_HOST=your_proxy_host
# TELEGRAM_PROXY_PORT=your_proxy_port
# TELEGRAM_PROXY_USERNAME=your_proxy_username
# TELEGRAM_PROXY_PASSWORD=your_proxy_password
# TELEGRAM_PROXY_SECRET=your_proxy_secret  # MTProxy 专用

# 数据库配置（可选，默认使用 SQLite）
# DATABASE_URL=sqlite+aiosqlite:///./pendle_tool.db
```

## 数据库初始化

### 自动初始化

数据库会在首次启动时自动初始化，无需手动操作。

### 手动初始化

如果需要手动初始化数据库：

```bash
python -m scripts.init_db
```

这会创建所有必要的数据库表和初始化默认数据。

### 清空并重新初始化数据库

⚠️ **警告：此操作会删除所有数据！**

如果需要清空所有数据并重新初始化：

```bash
python -m scripts.reset_db
```

脚本会要求你输入 `YES` 确认操作，然后：
1. 删除所有数据库表和数据
2. 重新创建所有表
3. 初始化默认数据（链 ID、默认分组等）

**使用场景：**
- 开发测试时重置数据
- 数据库损坏需要重建
- 清理所有历史数据

## 启动应用

### 开发模式（带热重载）

```bash
cd backend
uvicorn app.main:app --reload
```

### 生产模式

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后：
- 后端 API：http://127.0.0.1:8000/api
- API 文档：http://127.0.0.1:8000/docs
- 前端界面：http://127.0.0.1:8000/

## 功能说明

### 1. 管理中心
- 查看和管理 Pendle 项目列表
- 项目分组管理
- 监控状态切换
- 项目同步（从 Pendle API 获取最新数据）

### 2. 价格测试
- 自动测试监控项目的价格转换（100 USDT 可兑换多少 YT）
- 检测高价值机会（> $102）并发送 Telegram 通知
- 检测大额订单和 APR 变化（变化 >= 2% 时通知）

### 3. 历史记录
- 查看项目新增/删除历史
- 按日期分组显示

### 4. 聪明钱
- 管理聪明钱钱包列表
- 自动更新钱包交易记录和限价订单
- 发送新操作通知

## 常见问题

### 1. 启动失败：ModuleNotFoundError

**问题**：找不到 `app` 模块

**解决**：确保在 `backend` 目录下运行启动命令：
```bash
cd backend
uvicorn app.main:app --reload
```

### 2. Telegram 通知无法发送

**问题**：配置了 Telegram 但收不到通知

**解决**：
- 如果使用 Bot API：确保 Bot Token 正确，Bot 已加入目标群组
- 如果使用 Telethon：确保已完成授权（运行 `python -m scripts.bootstrap_telegram`）
- 检查 Chat ID 是否正确（使用 `python -m scripts.get_chat_id` 获取）

### 3. 数据库初始化失败

**问题**：数据库表创建失败

**解决**：
- 检查数据库文件权限
- 手动运行初始化脚本：`python -m scripts.init_db`
- 删除旧的数据库文件重新初始化（注意：会丢失所有数据）

### 4. 前端页面无法访问

**问题**：访问 http://127.0.0.1:8000/ 显示错误

**解决**：
- 确保 `backend/frontend` 目录存在且包含 `index.html`、`app.js`、`styles.css`
- 检查后端日志是否有错误信息

## 开发说明

### API 文档

启动应用后访问 http://127.0.0.1:8000/docs 查看完整的 API 文档（Swagger UI）。

### 项目同步

项目列表会每天 00:00 自动同步。也可以手动触发同步：
- 前端：点击"同步项目"按钮
- API：`POST /api/pendle/projects/sync`

### 价格测试

价格测试会在应用启动后自动开始，循环测试所有监控的项目。每个项目测试间隔约 3 秒。

## 许可证

[添加你的许可证信息]
