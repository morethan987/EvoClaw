# EvoClaw 代码审计报告

**审计日期**: 2026-03-14  
**审计范围**: `src/evoclaw/` 全部 8 个模块 + `tests/` 全部 8 个测试文件  
**Python 版本**: 3.14.3  
**测试状态**: 68/68 全部通过 (5.34s)

---

## 审计流程

### 第一步：运行完整测试套件

```bash
uv run pytest -v
```

结果：68 个测试全部通过，无 failure 或 error。确认现有功能的基线状态正常。

### 第二步：LSP 静态分析

对 `src/evoclaw/` 下全部 8 个源文件执行 basedpyright 诊断（severity=all）：

| 文件 | Error | Warning | 说明 |
|---|---|---|---|
| config.py | 1 | 11 | `dict` 缺少泛型参数；`data.get()` 返回类型未知 |
| daemon.py | 0 | 5 | 全部是 `reportMissingTypeStubs`（本包模块间引用） |
| lifecycle.py | 0 | 4 | 同上 |
| llm.py | 0 | 1 | 同上 |
| log.py | 0 | 0 | 无诊断 |
| tools.py | 2 | 20+ | `dict` 缺少泛型参数；`dispatch_tool` 参数缺少类型注解；`httpx` 返回的 `Any` 类型传播 |
| world.py | 0 | 0 | 无诊断 |
| \_\_main\_\_.py | 0 | 3 | `reportMissingTypeStubs` |

**LSP Error 总结**：仅有 `config.py` 和 `tools.py` 各有一个 `reportMissingTypeArgument` error（`dict` 未指定泛型参数），属于类型注解不完整，非运行时错误。

### 第三步：逐文件人工代码审查

针对以下维度逐一审查：
- 语法正确性
- 逻辑错误
- 边界条件与 edge case
- 并发 / 异步安全
- 资源泄漏
- 异常处理遗漏
- 安全隐患

---

## 发现的问题

### BUG-1: except 子句使用逗号语法（非标准，可能造成混淆） ✅ 已修复

**严重程度**: 🟡 低（功能正确但语法非标准）  
**状态**: ✅ 已修复  
**文件**: `daemon.py`, `lifecycle.py`

**问题**: `except A, B:` 逗号语法容易与 Python 2 的 `except ExceptionType, variable:` 混淆。

**修复**: 改为标准元组写法 `except (NotImplementedError, RuntimeError):` 和 `except (FileNotFoundError, ValueError):`。

---

### BUG-2: 死亡后无延迟立即重试 — 潜在紧密循环 ✅ 已修复

**严重程度**: 🟠 中  
**状态**: ✅ 已修复  
**文件**: `daemon.py`

**问题**: 死亡 → 天使处理（转世） → `continue` 后循环立即重新开始，跳过 heartbeat sleep，在持续性死亡条件下形成无延迟的紧密循环。

**修复**: 在每次 `handle_death` 后、`continue` 前，加入 `asyncio.wait_for(shutdown_event.wait(), timeout=heartbeat_interval)` 冷却等待，确保即使持续死亡也不会形成紧密循环。

---

### BUG-3: `log_heartbeat` 记录的 memory_size 是过期值 ✅ 已修复

**严重程度**: 🟢 低（日志准确性问题）  
**状态**: ✅ 已修复  
**文件**: `daemon.py`

**问题**: `memory_content` 在心跳开始时读取，LLM 工具调用可能在心跳期间修改了 `memory.md`，导致日志中的 `memory_size` 不准确。

**修复**: 改为使用 `os.path.getsize(memory_path)` 在日志记录时获取实时文件大小。

---

### BUG-4: `tools.py` 中 `dispatch_tool` 缺少类型注解 ✅ 已修复

**严重程度**: 🟢 低（类型安全）  
**状态**: ✅ 已修复  
**文件**: `tools.py`

**问题**: `args` 为裸 `dict`，`config` 缺少类型注解，与项目类型注解规范不一致。

**修复**: 改为 `dispatch_tool(name: str, args: dict[str, object], config: Config | None = None) -> str`，增加 `from typing import cast` 和 `from evoclaw.config import Config` 导入，函数体内使用 `cast()` 处理类型。

---

### BUG-5: `config.py` 中 `data` 的类型注解不完整 ✅ 已修复

**严重程度**: 🟢 低（类型安全）  
**状态**: ✅ 已修复  
**文件**: `config.py`

**问题**: `data: dict = {}` 缺少泛型参数。

**修复**: 改为 `data: dict[str, Any] = {}`，增加 `from typing import Any` 导入。

---

### BUG-6: `TOOL_DEFINITIONS` 类型注解不完整 ✅ 已修复

**严重程度**: 🟢 低（类型安全）  
**状态**: ✅ 已修复  
**文件**: `tools.py`

**问题**: `TOOL_DEFINITIONS: list[dict] = [...]` 缺少泛型参数。

**修复**: 改为 `TOOL_DEFINITIONS: list[dict[str, object]] = [...]`。

---

### BUG-7: 测试中 `open()` 缺少 `encoding` 参数和上下文管理器 ✅ 已修复

**严重程度**: 🟢 低（测试代码质量）  
**状态**: ✅ 已修复  
**文件**: `test_tools.py`, `test_lifecycle.py`, `test_log.py`, `conftest.py`

**问题**: 部分测试文件中 `open()`、`write_text()`、`read_text()` 未指定 `encoding="utf-8"`，与项目规范不一致。

**修复**: 为所有涉及的测试文件补充 `encoding="utf-8"` 参数，`test_tools.py` 中额外添加了 pyright 抑制注释以保持与其他测试文件一致。

---

## 未发现问题的区域（已确认安全）

| 区域 | 检查内容 | 结论 |
|---|---|---|
| 原子写入 (tools.py) | tempfile → fsync → replace → dir fsync | ✅ 正确，包含失败时的 temp 文件清理 |
| PID 文件锁 (daemon.py) | flock + 进程存活检测 | ✅ 正确，覆盖了 stale PID 清理 |
| 子进程隔离 (tools.py) | setsid + killpg + timeout | ✅ 正确，测试确认无僵尸进程 |
| LLM 工具循环 (llm.py) | max_iterations 限制 + 错误恢复 | ✅ 正确，malformed args 不导致崩溃 |
| API 错误处理 (llm.py) | RateLimit / 402 / ConnectionError | ✅ 正确，quota 耗尽返回 DEATH_MARKER |
| 天使进程 (lifecycle.py) | epitaph 生成 + 转世 + 代际递增 | ✅ 正确，包含 will.md 不存在的处理 |
| 配置加载 (config.py) | TOML + 环境变量 + 必填校验 | ✅ 正确，文件不存在时优雅降级 |
| 日志系统 (log.py) | 双输出 + close 清理 | ✅ 正确，setup 前先 close 防泄漏 |
| 面包屑系统 (world.py) | 线索链完整性 | ✅ 正确，测试覆盖了完整链路 |
| 系统提示词 (world.py) | 模板占位符渲染 | ✅ 正确，测试确认无残留占位符 |

---

## 总结

| 严重程度 | 数量 | 状态 | 详情 |
|---|---|---|---|
| 🔴 高（运行时崩溃） | 0 | — | — |
| 🟠 中（逻辑/性能问题） | 1 | ✅ 全部已修复 | 死亡后紧密循环 (BUG-2) |
| 🟡 低-中（非标准语法） | 1 | ✅ 全部已修复 | except 逗号语法 (BUG-1) |
| 🟢 低（类型/风格） | 5 | ✅ 全部已修复 | 类型注解不完整 (BUG-3~7) |

**整体评估**: 代码库质量良好，无运行时崩溃风险。审计发现的全部 7 个问题已于 2026-03-14 修复并通过完整测试套件验证（68/68 通过）。所有源文件 LSP 诊断无 error。
