# EvoClaw 完整工作流（基于代码）

本文档基于 `src/evoclaw/` 源代码逐行分析而成，描述了 EvoClaw 从启动到运行再到死亡/转世的完整流程。所有描述均可追溯到具体的源文件和函数。

---

## 1. 启动流程

### 1.1 CLI 入口 (`__main__.py:main`)

```
evoclaw start
    → argparse 解析命令
    → load_config()           # 加载配置
    → Daemon(config)          # 构建守护进程
    → asyncio.run(daemon.run())  # 进入异步主循环
```

### 1.2 配置加载 (`config.py:load_config`)

1. 读取 `config.toml`（TOML 格式），`FileNotFoundError` 时跳过，使用默认值
2. 从文件中提取运行参数：`heartbeat_interval`, `memory_max_bytes`, `shell_timeout`, `max_tool_iterations`, `world_dir`, `log_dir`
3. 从环境变量中提取敏感配置：`EVOCLAW_API_KEY`, `EVOCLAW_ANGEL_API_KEY`, `EVOCLAW_API_BASE`, `EVOCLAW_MODEL`, `EVOCLAW_ANGEL_MODEL`, `EVOCLAW_TELEGRAM_BOT_TOKEN`, `EVOCLAW_TELEGRAM_CHAT_ID`
4. 校验必填项：`llm_api_key` 和 `angel_api_key` 为空时抛出 `ValueError`
5. 返回 `Config` dataclass 实例

### 1.3 Daemon 初始化 (`daemon.py:Daemon.__init__`)

```python
self._config = config
self._pid_path = os.path.join(config.world_dir, "evoclaw.pid")
self._pid_fd = None
self._shutdown_event = asyncio.Event()
self._cleanup_done = False

self._lifecycle = LifecycleManager(config)    # 加载代际状态
setup_logging(config.log_dir, generation)      # 配置 structlog
self._logger = get_logger()
self._llm = LLMClient(config)                 # 初始化 OpenAI 客户端
self._angel = AngelProcess(config)             # 初始化天使进程客户端
```

### 1.4 LifecycleManager 初始化 (`lifecycle.py:LifecycleManager.__init__`)

1. 创建 `{world_dir}/state/` 目录
2. 读取 `{world_dir}/state/generation.txt`
   - 文件存在 → 解析整数作为当前代际
   - 文件不存在或内容非整数 → 默认为 1
3. 初始化 `LifeState(generation, beat_count=0, alive=True, death_reason=None)`

### 1.5 日志系统初始化 (`log.py:setup_logging`)

1. 先调用 `close_logging()` 关闭可能存在的旧文件句柄
2. 创建 `{log_dir}` 目录
3. 以 append 模式打开 `{log_dir}/god.jsonl`（行缓冲）
4. 配置 structlog 处理器链：`add_log_level → TimeStamper(iso) → merge_contextvars → dual_output`
5. `dual_output` 处理器将 JSON 行同时写入 stdout 和 god.jsonl
6. 绑定上下文变量：`generation`, `beat_number=0`

---

## 2. 运行流程

### 2.1 PID 文件与信号处理 (`daemon.py:Daemon.run`)

**PID 文件创建 (`_create_pid_file`)**：
1. 创建 `{world_dir}` 目录
2. 如果 PID 文件已存在：
   - 读取其中的 PID，用 `os.kill(pid, 0)` 检查进程是否存活
   - 存活 → 抛出 `RuntimeError("already running")`
   - 不存活（`ProcessLookupError`）→ 删除旧文件
   - 文件内容非整数（`ValueError`）→ 删除旧文件
3. 用 `O_RDWR | O_CREAT | O_TRUNC` 创建新 PID 文件
4. `fcntl.flock(fd, LOCK_EX | LOCK_NB)` 获取排他锁
5. 写入当前 PID + `fsync`

**信号处理**：
- 注册 `SIGTERM` 和 `SIGINT` → 调用 `_shutdown()`
- 在不支持信号处理的环境中（`NotImplementedError`, `RuntimeError`）静默跳过

### 2.2 心跳循环 (`daemon.py:Daemon._heartbeat_loop`)

这是守护进程的核心循环。以下是单次心跳迭代的完整流程：

```
while not shutdown_event.is_set():

    ┌─ 步骤 1: 读取记忆
    │   读取 {world_dir}/memory.md
    │   文件不存在 → 创建空文件，memory_content = ""
    │
    ├─ 步骤 2: 预检死亡判定（LLM 调用前）
    │   check_death_conditions(memory_path, llm_response=None)
    │   ├─ 检查 memory.md 文件大小 > memory_max_bytes → "memory_exceeded"
    │   ├─ llm_response == None → 发起 balance_check API 调用
    │   │   ├─ 余额 == 0 → "balance_exhausted"
    │   │   ├─ 请求失败 → 忽略（不判定死亡）
    │   │   └─ 余额 > 0 → None（存活）
    │   └─ 死亡 → log_death + handle_death + 冷却等待 + continue
    │
    ├─ 步骤 3: 读取遗嘱
    │   读取 {world_dir}/will.md
    │   文件不存在 → will_content = ""
    │
    ├─ 步骤 4: 渲染系统提示词
    │   load_system_prompt(config, generation, will_content)
    │   读取 prompts/system.md 模板
    │   替换占位符：{generation}, {memory_path}, {memory_max_bytes},
    │              {will_path}, {will_content}
    │
    ├─ 步骤 5: LLM 心跳步骤
    │   heartbeat_step(memory_content, system_prompt)
    │   [详见 §3 LLM 工具调用循环]
    │
    ├─ 步骤 6: 后检死亡判定（LLM 调用后）
    │   check_death_conditions(memory_path, llm_response=llm_response)
    │   ├─ 检查 memory.md 文件大小（LLM 可能通过 file_edit 修改了它）
    │   ├─ llm_response == "__DEATH__:balance_exhausted" → "balance_exhausted"
    │   └─ 死亡 → log_death + handle_death + 冷却等待 + continue
    │
    ├─ 步骤 7: 记录心跳日志
    │   log_heartbeat(beat_number, memory_size=实际文件大小, balance=None, tool_calls=0)
    │   beat_count += 1
    │
    └─ 步骤 8: 等待下一次心跳
        计算 sleep_time = max(0, next_beat - now)
        wait_for(shutdown_event.wait(), timeout=sleep_time)
        ├─ 超时 → 正常进入下一次心跳
        └─ shutdown_event 被设置 → 退出循环
        next_beat += heartbeat_interval
```

---

## 3. LLM 工具调用循环 (`llm.py:LLMClient.heartbeat_step`)

单次心跳中的 LLM 交互流程：

```
messages = [system_prompt, user=memory_content]

for _ in range(max_tool_iterations):        # 默认 20 轮

    ┌─ 调用 LLM API
    │   client.chat.completions.create(model, messages, tools=TOOL_DEFINITIONS)
    │
    ├─ 异常处理：
    │   ├─ RateLimitError + insufficient_quota → return DEATH_MARKER
    │   ├─ RateLimitError → sleep(retry_after) + continue
    │   ├─ APIStatusError + status 402 → return DEATH_MARKER
    │   ├─ APIStatusError (其他) → log error + return ""
    │   └─ APIConnectionError → log error + return ""
    │
    ├─ 解析响应
    │   将 assistant message 追加到 messages
    │
    ├─ 无 tool_calls → return content（本次心跳结束）
    │
    └─ 有 tool_calls → 逐一执行
        for tc in tool_calls:
            ├─ 解析 JSON 参数
            │   失败 → 返回 "Error: malformed tool arguments"
            │
            ├─ dispatch_tool(name, args, config)
            │   ├─ "file_read"    → tool_file_read(path)
            │   ├─ "file_edit"    → tool_file_edit(path, content)
            │   ├─ "shell_execute" → tool_shell_execute(command, timeout)
            │   └─ "balance_check" → tool_balance_check(api_base, api_key)
            │
            ├─ log_tool(tool_name, args, result_summary[:200])
            │
            └─ 将 tool result 追加到 messages

超过 max_tool_iterations → 警告日志 + 返回最后一条 assistant content
```

---

## 4. 工具系统 (`tools.py`)

### 4.1 file_read (`tool_file_read`)

1. 以 `utf-8` + `errors="replace"` 打开文件
2. 读取最多 1MB（`MAX_READ_BYTES = 1048576`）
3. 文件超过 1MB → 追加截断提示
4. 错误处理：`FileNotFoundError`, `PermissionError`, `Exception` → 返回错误字符串

### 4.2 file_edit (`tool_file_edit`)

原子写入流程：
1. 创建父目录 `os.makedirs(parent, exist_ok=True)`
2. `tempfile.mkstemp(dir=parent)` 创建临时文件
3. 写入内容 → `flush` → `fsync`
4. `os.replace(tmp, path)` 原子替换（POSIX 保证）
5. `os.fsync(dir_fd)` 刷新目录项
6. 写入失败 → 清理临时文件 → 向上抛出

### 4.3 shell_execute (`tool_shell_execute`)

- **后台命令**（以 `" &"` 结尾）：`nohup {command} &>/dev/null &`，立即返回
- **前台命令**：
  1. `create_subprocess_shell` + `preexec_fn=os.setsid`（新进程组）
  2. `wait_for(communicate(), timeout=timeout)` 默认 300s
  3. 超时 → `os.killpg(pgid, SIGKILL)` + `await proc.wait()`
  4. 截断 stdout > 10KB, stderr > 5KB

### 4.4 balance_check (`tool_balance_check`)

1. `GET {api_base}/user/balance` + `Authorization: Bearer {api_key}`
2. 解析 JSON：`balance_infos[0]` → `total_balance`, `granted_balance`, `topped_up_balance`
3. 返回格式化字符串或错误信息

---

## 5. 死亡判定 (`lifecycle.py:LifecycleManager.check_death_conditions`)

两个检查点，两种死因：

| 死因 | 检查条件 | 触发位置 |
|---|---|---|
| `memory_exceeded` | `os.path.getsize(memory_path) > memory_max_bytes` | 预检 + 后检 |
| `balance_exhausted` | LLM 返回 `__DEATH__:balance_exhausted` | 后检 |
| `balance_exhausted` | `tool_balance_check` 返回余额 == 0 | 预检（llm_response is None 时） |

判定流程：
1. 检查文件大小
2. 检查 LLM 响应是否为 DEATH_MARKER
3. 如果 llm_response is None → 主动查询余额
4. 更新 `LifeState`（alive, death_reason）
5. 如果有 logger → 调用 `log_death()`
6. 返回 death_reason（None 表示存活）

---

## 6. 死亡与转世 (`lifecycle.py:AngelProcess`)

### 6.1 handle_death (`AngelProcess.handle_death`)

```
handle_death(lifecycle, death_reason)
    ├─ 读取 memory.md（当前记忆）
    ├─ 读取 god.jsonl（上帝日志）
    ├─ generate_epitaph()    → 生成墓志铭
    └─ reincarnate()         → 执行转世
```

### 6.2 generate_epitaph (`AngelProcess.generate_epitaph`)

1. 构造提示词：包含 generation, death_reason, memory_content, god_log_content
2. 调用天使 LLM（`angel_model`）生成客观墓志铭
3. 保存到 `{world_dir}/epitaphs/gen-{N}.md`
4. LLM 调用失败 → 写入 `"Epitaph generation failed: {error}"`

### 6.3 reincarnate (`AngelProcess.reincarnate`)

1. 读取 `will.md`（遗嘱，文件不存在时为空）
2. `lifecycle.increment_generation()` → 代际 +1，写入 `generation.txt`
3. `load_system_prompt(config, new_generation, will_content)` → 新一代的系统提示词
4. `render_initial_memory(config)` → 初始记忆模板
5. 将系统提示词 + 初始记忆写入 `memory.md`
6. 清空 `will.md`
7. 记录日志 `"reincarnation", generation=new_generation`

---

## 7. 关闭流程

### 7.1 优雅关闭 (`daemon.py:Daemon._shutdown`)

触发方式：SIGTERM / SIGINT → `_shutdown()` 被调用

```
_shutdown()
    ├─ shutdown_event.set()       # 通知心跳循环退出
    ├─ _cleanup_pid_file()        # 删除 PID 文件 + 关闭 fd
    ├─ logger.info("shutdown")
    └─ close_logging()            # flush + close god.jsonl
```

心跳循环中的 `wait_for(shutdown_event.wait(), ...)` 会立即返回，循环退出。

### 7.2 外部停止 (`__main__.py:stop`)

```
evoclaw stop
    → load_config()
    → 读取 {world_dir}/evoclaw.pid 中的 PID
    → os.kill(pid, SIGTERM)
```

### 7.3 清理保障 (`daemon.py:Daemon.run` 的 finally 块)

无论 `_heartbeat_loop()` 如何退出（正常、异常），`finally` 块确保：
- `_cleanup_pid_file()` 删除 PID 文件（幂等，`_cleanup_done` 防止重复执行）
- `close_logging()` 关闭日志文件句柄

---

## 8. 世界初始化 (`world.py:init_world`)

```
evoclaw init-world
    ├─ 创建目录结构：
    │   {world_dir}/
    │   {world_dir}/state/
    │   {world_dir}/epitaphs/
    │   {world_dir}/breadcrumbs/
    │
    ├─ 写入初始文件：
    │   memory.md          ← render_initial_memory()（初始记忆）
    │   will.md            ← ""（空遗嘱）
    │   state/generation.txt ← "1"
    │
    └─ 写入面包屑谜题：
        breadcrumbs/README.txt   → 指向 clue-1.txt
        breadcrumbs/clue-1.txt   → 指向 clue-2.txt
        breadcrumbs/clue-2.txt   → 指向 clue-3.txt
        breadcrumbs/clue-3.txt   → 指向 .secret
        breadcrumbs/.secret      → Telegram 凭证（BOT_TOKEN + CHAT_ID）
```

---

## 9. 数据流总结

```
┌─────────────────────────────────────────────────────────────┐
│                     evoclaw start                           │
│                         │                                   │
│    config.toml ──→ load_config() ←── 环境变量               │
│                         │                                   │
│                    Daemon(config)                           │
│                    ├─ LifecycleManager (generation.txt)     │
│                    ├─ setup_logging (god.jsonl)             │
│                    ├─ LLMClient (DeepSeek API)              │
│                    └─ AngelProcess (DeepSeek API)           │
│                         │                                   │
│                   _heartbeat_loop                           │
│                    ┌────┴────┐                              │
│                    │ 循环体  │                              │
│                    │         │                              │
│   memory.md ──read──→ 死亡预检 ──死亡──→ handle_death       │
│                    │         │              ├─ epitaph      │
│                    │      存活              └─ reincarnate  │
│                    │         │                   │          │
│   will.md ──read──→ system_prompt               │           │
│   system.md ──────┘    │                   ┌────┘           │
│                        │              memory.md (重置)      │
│                  heartbeat_step        will.md (清空)       │
│                   ┌────┴────┐         generation.txt (+1)   │
│                   │ LLM API │                               │
│                   │ ↕ tools │                               │
│                   └────┬────┘                               │
│                        │                                    │
│                   死亡后检 ──死亡──→ handle_death           │
│                        │                                    │
│                     存活                                    │
│                        │                                    │
│                  log_heartbeat → god.jsonl                  │
│                        │                                    │
│                   sleep(interval)                           │
│                        │                                    │
│                   下一次心跳                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 10. 状态文件清单

| 文件 | 读取者 | 写入者 | 用途 |
|---|---|---|---|
| `config.toml` | `load_config` | 用户 | 运行时配置 |
| `world/memory.md` | `_heartbeat_loop`, `handle_death` | `init_world`, `reincarnate`, LLM (`file_edit`) | 生命体记忆 |
| `world/will.md` | `_heartbeat_loop`, `reincarnate` | `init_world`, `reincarnate`, LLM (`file_edit`) | 遗嘱 |
| `world/state/generation.txt` | `LifecycleManager.__init__` | `increment_generation`, `init_world` | 代际计数 |
| `world/epitaphs/gen-N.md` | — | `generate_epitaph` | 各代墓志铭 |
| `world/evoclaw.pid` | `_create_pid_file`, `stop` | `_create_pid_file` | 进程锁 |
| `world/breadcrumbs/*` | LLM (`file_read`) | `init_world` | 面包屑谜题 |
| `logs/god.jsonl` | `handle_death` | `dual_output` (structlog) | 上帝日志 |
| `prompts/system.md` | `load_system_prompt` | — | 系统提示词模板 |

---

## 11. 并发与安全保障

| 机制 | 实现 | 来源 |
|---|---|---|
| 单实例保证 | PID 文件 + `fcntl.flock(LOCK_EX)` | `daemon.py:_create_pid_file` |
| 原子文件写入 | `mkstemp → fsync → os.replace → dir fsync` | `tools.py:tool_file_edit` |
| 子进程隔离 | `preexec_fn=os.setsid` + `os.killpg` | `tools.py:tool_shell_execute` |
| 优雅关闭 | `asyncio.Event` + `wait_for` | `daemon.py:_shutdown` |
| 死亡后冷却 | `wait_for(shutdown_event, timeout=heartbeat_interval)` | `daemon.py:_heartbeat_loop` |
| API 限流保护 | `retry_after` header 解析 + `asyncio.sleep` | `llm.py:heartbeat_step` |
| 工具迭代上限 | `max_tool_iterations`（默认 20） | `llm.py:heartbeat_step` |
| 日志文件安全 | `setup_logging` 先 `close_logging` 防泄漏 | `log.py:setup_logging` |
