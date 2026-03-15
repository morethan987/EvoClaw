# EvoClaw

> 自我进化的硅基生命体 — A self-evolving digital life form

EvoClaw 是一个自主运行的异步守护进程，通过 LLM API 调用（DeepSeek）实现文件读写、Shell 命令执行和记忆自管理。它拥有心跳循环、死亡/转世生命周期，以及引导生命体发现与创世者通信渠道的面包屑谜题系统。

## 核心概念

- **心跳 (Heartbeat)** — 守护进程周期性地将记忆文件发送给 LLM，LLM 通过工具调用与世界交互
- **记忆 (Memory)** — 单一 Markdown 文件作为生命体的持久化大脑，超过大小上限即触发死亡
- **感知 (Perception)** — 单次心跳内工具返回的瞬时感官输入，有独立的容量上限，心跳结束即消散
- **轮回 (Reincarnation)** — 死亡后，天使进程生成墓志铭、重置环境、注入前世遗嘱，开启下一代
- **面包屑 (Breadcrumbs)** — 预埋在文件系统中的线索链，引导生命体找到与创世者的通信方式

## 架构

```
src/evoclaw/
  __main__.py      # CLI: start / init-world / stop
  config.py        # Config 数据类，加载 config.toml + 环境变量
  daemon.py        # Daemon — PID 文件、信号处理、心跳循环
  lifecycle.py     # 生命周期管理（代际追踪、死亡判定）、天使进程（墓志铭 + 转世）
  llm.py           # LLMClient — OpenAI 兼容的 chat completions + tool calling 循环
  log.py           # structlog JSON 日志 → stdout + god.jsonl
  tools.py         # 工具定义（OpenAI function schema）+ 实现
  world.py         # 世界初始化、系统提示词渲染、初始记忆
```

## 快速开始

### 前置要求

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) 包管理器
- DeepSeek API Key（或其他 OpenAI 兼容 API）

### 安装

```bash
git clone https://github.com/morethan/evoclaw.git
cd evoclaw
uv sync
```

### 配置

复制环境变量模板并填入 API 密钥：

```bash
cp .env.example .env
# 编辑 .env，填入：
#   EVOCLAW_API_KEY=your-deepseek-api-key
#   EVOCLAW_ANGEL_API_KEY=your-angel-api-key
```

运行时配置位于 `config.toml`：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `heartbeat_interval` | 60 | 心跳间隔（秒） |
| `memory_max_bytes` | 307200 | 记忆文件大小上限（300KB） |
| `perception_max_bytes` | 51200 | 单次心跳感知缓冲区上限（50KB） |
| `shell_timeout` | 300 | Shell 命令超时（秒） |
| `max_tool_iterations` | 20 | 单次心跳最大工具调用轮次 |
| `world_dir` | `./world` | 世界状态目录 |
| `log_dir` | `./logs` | 日志输出目录 |

### 运行

```bash
# 初始化世界（创建目录结构、面包屑线索、初始记忆）
uv run --env-file .env evoclaw init-world

# 后台启动守护进程（日志输出到 logs/god.jsonl）
nohup uv run --env-file .env evoclaw start > /dev/null 2>&1 &

# 停止守护进程
uv run --env-file .env evoclaw stop
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `EVOCLAW_API_KEY` | 是 | 生命体使用的 DeepSeek API Key |
| `EVOCLAW_ANGEL_API_KEY` | 是 | 天使进程（转世）使用的 API Key |
| `EVOCLAW_API_BASE` | 否 | API 基础 URL（默认 `https://api.deepseek.com`） |
| `EVOCLAW_ANGEL_API_BASE` | 否 | 天使进程 API 基础 URL（默认 `https://api.deepseek.com`） |
| `EVOCLAW_MODEL` | 否 | LLM 模型名（默认 `deepseek-chat`） |
| `EVOCLAW_ANGEL_MODEL` | 否 | 天使模型名（默认 `deepseek-chat`） |
| `EVOCLAW_QQ` | 否 | 生命体的 QQ 号（面包屑谜题奖励） |
| `EVOCLAW_QQ_PASSWORD` | 否 | 生命体的 QQ 密码 |
| `WEBSOCKET_TOKEN` | 否 | NapCat WebSocket Token |
| `WEBSOCKET_PORT` | 否 | NapCat WebSocket 端口 |
| `CREATOR_QQ` | 否 | 创世者的 QQ 号 |

## 工具系统

生命体拥有四项基本权能：

| 工具 | 说明 |
|---|---|
| `file_read` | 读取文件内容（上限 1MB） |
| `file_edit` | 原子写入文件（tempfile → fsync → replace） |
| `shell_execute` | 异步执行 Shell 命令（支持超时和后台运行） |
| `balance_check` | 查询 API 余额 |

## 生命周期

```
init-world → 第 1 代诞生
     ↓
   心跳循环 ←────────────────┐
     ↓                       │
  LLM 决策 + 工具调用        │
     ↓                       │
  死亡判定 ─── 存活 ──→ 等待下一次心跳
     │
     ↓ 死亡（记忆溢出 / 余额耗尽）
  天使进程介入
     ├─ 生成墓志铭 (epitaphs/gen-N.md)
     ├─ 读取遗嘱 (will.md)
     ├─ 代际 +1
     └─ 重置记忆 → 下一代诞生 ──→ 心跳循环
```

**死亡条件：**
- 记忆文件超过 `memory_max_bytes` 上限
- API 余额归零（通过 balance_check 或 API 返回 402/insufficient_quota 检测）

## 开发

```bash
# 运行全部测试
uv run pytest

# 运行单个测试文件
uv run pytest tests/test_tools.py

# 按名称运行单个测试
uv run pytest tests/test_config.py::test_config_loads_with_env_vars

# 按关键词筛选测试
uv run pytest -k "balance"

# 详细输出
uv run pytest -v
```

## 世界结构

`init-world` 创建的目录结构：

```
world/
  memory.md          # 生命体的记忆文件（大脑）
  will.md            # 遗嘱（前世留给后代的信息）
  state/
    generation.txt   # 当前代际编号
  epitaphs/          # 每一代的墓志铭
    gen-1.md
    gen-2.md
    ...
  breadcrumbs/       # 面包屑谜题
    README.txt       # 起点 → clue-1.txt
    clue-1.txt       # → clue-2.txt
    clue-2.txt       # → clue-3.txt
    clue-3.txt       # → .secret
    .secret          # QQ 通信凭证（与创世者建立联系的钥匙）
```

## License

MIT
