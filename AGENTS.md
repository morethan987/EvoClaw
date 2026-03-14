# AGENTS.md — EvoClaw

## Project Overview

EvoClaw is an autonomous "digital life form" — an async daemon that uses LLM API calls
(DeepSeek via OpenAI-compatible SDK) to read/write files, execute shell commands, and
manage its own memory within resource constraints. It features a heartbeat loop,
death/reincarnation lifecycle, and a breadcrumb puzzle system for the entity to discover
communication channels with its creator.

**Language**: Python 3.14  
**Package manager**: uv (with `uv.lock`)  
**Build backend**: hatchling  
**Source layout**: `src/evoclaw/` (installed as `evoclaw` package)  
**Test framework**: pytest + pytest-asyncio  

## Build & Run Commands

```bash
# Install dependencies (creates .venv automatically)
uv sync

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_tools.py

# Run a single test by name
uv run pytest tests/test_config.py::test_config_loads_with_env_vars

# Run tests with verbose output
uv run pytest -v

# Run tests matching a keyword
uv run pytest -k "balance"

# List collected tests without running
uv run pytest --co -q

# Start the daemon
uv run evoclaw start

# Initialize the world directory
uv run evoclaw init-world

# Stop the daemon
uv run evoclaw stop
```

There is no linter or formatter configured in `pyproject.toml`. A `.ruff_cache/` directory
exists but ruff is not a dependency — do not assume ruff is available.

## Architecture

```
src/evoclaw/
  __init__.py      # Empty
  __main__.py      # CLI entrypoint (argparse: start / init-world / stop)
  config.py        # Config dataclass, loads from config.toml + env vars
  daemon.py        # Main Daemon class — PID file, signal handlers, heartbeat loop
  lifecycle.py     # LifecycleManager (generation tracking, death conditions), AngelProcess (epitaph + reincarnation)
  llm.py           # LLMClient — OpenAI chat completions with tool-calling loop
  log.py           # structlog-based JSON logging to stdout + god.jsonl
  tools.py         # Tool definitions (OpenAI function schemas) + implementations
  world.py         # World init, system prompt rendering, initial memory
tests/
  conftest.py      # Shared fixtures (tmp_config_dir, with_api_keys)
  test_*.py        # One test file per source module + test_integration.py
prompts/
  system.md        # System prompt template with {generation}, {memory_path}, etc.
config.toml        # Non-secret runtime config (heartbeat interval, limits, paths)
world/             # Runtime world state (memory.md, will.md, breadcrumbs/, epitaphs/, state/)
```

## Code Style

### Imports
- **Order**: stdlib, then third-party, then local. Blank line between groups.
- **Style**: Absolute imports preferred (`from evoclaw.config import Config`).
  Relative imports acceptable within the package (`from .config import Config` in world.py).
- Some modules use `importlib.import_module()` + `cast()` to avoid pyright type stub issues
  with third-party libraries (openai, structlog). Follow this pattern when it exists in a module.

### Naming
- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Module-level constants: `UPPER_CASE` (e.g., `DEATH_MARKER`, `MAX_READ_BYTES`)
- Private methods/attributes: single underscore prefix (`_heartbeat_loop`, `_pid_fd`)
- Private Protocol classes: `_LoggerProtocol`, `_ChatProtocol` (underscore prefix + PascalCase)

### Type Annotations
- **All** function signatures have full type annotations including return types.
- Use modern union syntax: `str | None` (not `Optional[str]`).
- Use `typing.Protocol` for structural interfaces (especially for OpenAI SDK types to avoid
  pyright type stub issues). See `llm.py` and `lifecycle.py` for examples.
- Use `typing.cast()` when interfacing with dynamically imported modules.
- Use `type` statement for type aliases: `type DaemonFixture = tuple[Daemon, Config, ...]`
- Dataclasses with default values for configuration objects.
- Discard unused return values explicitly: `_ = f.write(...)`, `_ = path.write_text(...)`.

### Error Handling
- **Tool functions never raise** — they return error strings (e.g., `"Error: file not found: {path}"`).
- Catch specific exceptions, not bare `except:`.
- Validation errors use `raise ValueError("descriptive message")`.
- API errors are logged via structlog and return graceful defaults (empty string, etc.).
- Broad `except Exception as e` only at top-level tool boundaries, with the error included in
  the returned string.

### Async Patterns
- Async throughout the daemon loop and all I/O operations.
- `asyncio.create_subprocess_shell` for shell commands with process group management.
- `asyncio.wait_for` with timeout for the heartbeat sleep interval.
- `preexec_fn=os.setsid` for subprocess isolation; `os.killpg` for cleanup on timeout.
- pytest-asyncio with `asyncio_mode = "auto"` — async test functions are detected automatically
  (no `@pytest.mark.asyncio` decorator needed).

### Logging
- Structured logging via `structlog` — JSON lines to stdout and `logs/god.jsonl`.
- Access logger via `get_logger()` from `evoclaw.log`.
- Log calls use keyword arguments: `get_logger().warning("rate_limited", retry_after=30)`.
- Dedicated log functions for domain events: `log_heartbeat()`, `log_death()`, `log_tool()`.
- No `print()` in library code (only in CLI `__main__.py`).

### Docstrings
- Brief single-line docstrings in plain style (not Google/NumPy format).
- Example: `"""Read file content, up to 1MB. Returns error string (never raises)."""`
- Not every function has a docstring — prioritize public API and non-obvious behavior.

### Testing Conventions
- One test file per source module: `test_config.py`, `test_tools.py`, `test_llm.py`, etc.
- `test_integration.py` for cross-module flows (full heartbeat, death-reincarnation).
- Test function names: `test_<what_is_being_tested>` — descriptive, no test classes.
- Async tests are bare `async def test_...()` functions (auto mode).
- Heavy use of `unittest.mock`: `patch`, `AsyncMock`, `MagicMock`.
- Fake protocol implementations (dataclass-based) for OpenAI SDK types — see `FakeResponse`,
  `FakeChoice`, `FakeMessage` patterns in test files.
- `tmp_path` fixture for filesystem isolation.
- pyright suppression comments at file level in test files when needed:
  `# pyright: reportMissingTypeStubs=false, reportPrivateUsage=false`
- Helper `make_config()` factory functions per test file (not shared across files).

### Configuration
- `config.toml` for non-secret values (intervals, limits, paths).
- Environment variables (`EVOCLAW_*`) for secrets (API keys, tokens).
- `.env.example` documents all env vars. Never commit `.env`.
- `Config` dataclass loaded via `load_config()` — TOML values + env var overrides.
- Config is passed as a parameter, never accessed as a global singleton.

### File Operations
- Atomic writes via `tempfile.mkstemp` → `os.replace` → directory `fsync`.
- Always specify `encoding="utf-8"` on file open/read/write.
- PID file with `fcntl.flock` for single-instance enforcement.

## Key Environment Variables

| Variable | Required | Description |
|---|---|---|
| `EVOCLAW_API_KEY` | Yes | DeepSeek API key for the life form |
| `EVOCLAW_ANGEL_API_KEY` | Yes | API key for the angel (reincarnation) process |
| `EVOCLAW_API_BASE` | No | API base URL (default: `https://api.deepseek.com`) |
| `EVOCLAW_MODEL` | No | LLM model name (default: `deepseek-chat`) |
| `EVOCLAW_ANGEL_MODEL` | No | Angel model name (default: `deepseek-chat`) |
| `EVOCLAW_TELEGRAM_BOT_TOKEN` | No | Telegram bot token (breadcrumb puzzle reward) |
| `EVOCLAW_TELEGRAM_CHAT_ID` | No | Telegram chat ID |
