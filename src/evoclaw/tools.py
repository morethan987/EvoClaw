import asyncio
import os
import signal
import tempfile
from typing import cast

import httpx

from evoclaw.config import Config

# OpenAI function calling tool schemas — strict: true required
TOOL_DEFINITIONS: list[dict[str, object]] = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the full content of a file. Returns the content as a string.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file to read.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_edit",
            "description": "Write (overwrite) the entire content of a file atomically. Parent directories are created automatically.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "New content to write to the file (replaces existing content entirely).",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_execute",
            "description": "Execute a shell command asynchronously. Returns exit_code, stdout (up to 10KB), and stderr (up to 5KB). For long-running background tasks, end command with ' &'.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute. End with ' &' to run in background.",
                    },
                    "timeout": {
                        "type": ["integer", "null"],
                        "description": "Timeout in seconds. Null uses default (300s).",
                    },
                },
                "required": ["command", "timeout"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "balance_check",
            "description": "Check the remaining API balance. Returns current balance information.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]

MAX_READ_BYTES = 1024 * 1024  # 1MB max read
STDOUT_MAX = 10 * 1024  # 10KB
STDERR_MAX = 5 * 1024  # 5KB
DEFAULT_SHELL_TIMEOUT = 300  # seconds


async def tool_file_read(path: str) -> str:
    """Read file content, up to 1MB. Returns error string (never raises)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_READ_BYTES)
        size = os.path.getsize(path)
        if size > MAX_READ_BYTES:
            content += f"\n[... truncated: file is {size} bytes, only first {MAX_READ_BYTES} bytes shown]"
        return content
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except PermissionError:
        return f"Error: permission denied: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


async def tool_file_edit(path: str, content: str) -> str:
    """Atomically write content to path. Creates parent dirs. Returns status string (never raises)."""
    try:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)

        # Atomic write: tempfile -> fsync -> os.replace -> dir fsync
        fd, tmp_path = tempfile.mkstemp(dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            # fsync the directory entry
            dir_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            # Clean up temp file if something went wrong before replace
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        size = os.path.getsize(path)
        return f"OK: written {size} bytes to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


async def tool_shell_execute(command: str, timeout: int | None = None) -> str:
    """Execute a shell command asynchronously. Returns exit_code, stdout, stderr."""
    _timeout = timeout if timeout is not None else DEFAULT_SHELL_TIMEOUT

    if command.rstrip().endswith(" &"):
        bg_command = command.rstrip().rstrip("&").rstrip()
        proc = await asyncio.create_subprocess_shell(
            f"nohup {bg_command} &>/dev/null &",
            preexec_fn=os.setsid,
        )
        await proc.wait()
        return f"Background process started for: {bg_command}"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_timeout
            )
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            return (
                f"exit_code: -1\nstdout: \nstderr: Command timed out after {_timeout}s"
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if len(stdout) > STDOUT_MAX:
            stdout = (
                stdout[:STDOUT_MAX] + f"\n[truncated: {len(stdout_bytes)} bytes total]"
            )
        if len(stderr) > STDERR_MAX:
            stderr = (
                stderr[:STDERR_MAX] + f"\n[truncated: {len(stderr_bytes)} bytes total]"
            )

        return f"exit_code: {proc.returncode}\nstdout: {stdout}\nstderr: {stderr}"

    except Exception as e:
        return f"exit_code: -1\nstdout: \nstderr: Shell execution failed: {e}"


async def tool_balance_check(api_base: str, api_key: str) -> str:
    """Check API balance via DeepSeek balance endpoint. Returns formatted balance string (never raises)."""
    try:
        url = f"{api_base}/user/balance"
        headers = {"Authorization": f"Bearer {api_key}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()

        # Parse response format: {"is_available": true, "balance_infos": [...]}
        if not data.get("balance_infos") or len(data["balance_infos"]) == 0:
            return "Balance check failed: no balance information available"

        balance_info = data["balance_infos"][0]
        total_balance = balance_info.get("total_balance", "0")
        granted_balance = balance_info.get("granted_balance", "0")
        topped_up_balance = balance_info.get("topped_up_balance", "0")

        return f"总余额: {total_balance} CNY, 赠送: {granted_balance}, 充值: {topped_up_balance}"

    except Exception as e:
        return f"Balance check failed: {e}"


async def dispatch_tool(
    name: str, args: dict[str, object], config: Config | None = None
) -> str:
    """Route a tool call to its implementation. Returns result string."""
    if name == "file_read":
        return await tool_file_read(cast(str, args["path"]))
    elif name == "file_edit":
        return await tool_file_edit(cast(str, args["path"]), cast(str, args["content"]))
    elif name == "shell_execute":
        return await tool_shell_execute(
            cast(str, args["command"]), cast(int | None, args.get("timeout"))
        )
    elif name == "balance_check":
        if config is None:
            return "Balance check failed: no config provided"
        return await tool_balance_check(config.llm_api_base, config.llm_api_key)
    else:
        return f"Error: unknown tool '{name}'"
