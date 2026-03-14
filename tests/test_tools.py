# pyright: reportAttributeAccessIssue=false, reportIndexIssue=false

import os
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from evoclaw.tools import (
    tool_file_read,
    tool_file_edit,
    tool_shell_execute,
    tool_balance_check,
    dispatch_tool,
    TOOL_DEFINITIONS,
)
from evoclaw.config import Config


# ---- TOOL_DEFINITIONS schema tests ----


def test_tool_definitions_have_strict():
    for tool in TOOL_DEFINITIONS:
        fn = tool["function"]
        assert fn.get("strict") is True, f"Tool {fn['name']} missing strict: true"


def test_tool_definitions_names():
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert "file_read" in names
    assert "file_edit" in names
    assert "shell_execute" in names
    assert "balance_check" in names


# ---- file_read tests ----


async def test_file_read_returns_content(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world", encoding="utf-8")
    result = await tool_file_read(str(f))
    assert result == "hello world"


async def test_file_read_nonexistent_returns_error():
    result = await tool_file_read("/tmp/nonexistent_evoclaw_test_file_xyz.txt")
    assert "Error" in result
    assert "not found" in result.lower() or "nonexistent" in result.lower()


async def test_file_read_returns_string_not_exception(tmp_path):
    result = await tool_file_read(str(tmp_path / "missing.txt"))
    assert isinstance(result, str)
    assert "Error" in result


# ---- file_edit (atomic write) tests ----


async def test_file_edit_writes_content(tmp_path):
    target = str(tmp_path / "output.txt")
    result = await tool_file_edit(target, "new content")
    assert "OK" in result
    with open(target, encoding="utf-8") as f:
        assert f.read() == "new content"


async def test_file_edit_creates_parent_dirs(tmp_path):
    target = str(tmp_path / "deep" / "nested" / "file.txt")
    result = await tool_file_edit(target, "nested content")
    assert "OK" in result
    with open(target, encoding="utf-8") as f:
        assert f.read() == "nested content"


async def test_file_edit_no_temp_file_residue(tmp_path):
    target = str(tmp_path / "clean.txt")
    await tool_file_edit(target, "content")
    files = list(tmp_path.iterdir())
    # Only the target file should exist — no .tmp or tmp* residue
    assert len(files) == 1
    assert files[0].name == "clean.txt"


async def test_file_edit_overwrites_existing(tmp_path):
    target = str(tmp_path / "existing.txt")
    await tool_file_edit(target, "original")
    await tool_file_edit(target, "updated")
    with open(target, encoding="utf-8") as f:
        assert f.read() == "updated"


# ---- dispatch_tool tests ----


async def test_dispatch_file_read(tmp_path):
    f = tmp_path / "disp.txt"
    f.write_text("dispatch test", encoding="utf-8")
    result = await dispatch_tool("file_read", {"path": str(f)})
    assert result == "dispatch test"


async def test_dispatch_file_edit(tmp_path):
    target = str(tmp_path / "disp_out.txt")
    result = await dispatch_tool("file_edit", {"path": target, "content": "dispatched"})
    assert "OK" in result


async def test_dispatch_unknown_tool():
    result = await dispatch_tool("unknown_tool", {})
    assert "Error" in result
    assert "unknown" in result.lower()


# ---- shell_execute tests ----


async def test_shell_execute_basic():
    result = await tool_shell_execute("echo hello_world")
    assert "hello_world" in result
    assert "exit_code: 0" in result


async def test_shell_execute_exit_code_nonzero():
    result = await tool_shell_execute("exit 42", timeout=5)
    assert "exit_code: 42" in result


async def test_shell_execute_stderr():
    result = await tool_shell_execute("echo error_msg >&2; exit 1", timeout=5)
    assert "error_msg" in result
    assert "exit_code: 1" in result


async def test_shell_execute_timeout():
    result = await tool_shell_execute("sleep 60", timeout=2)
    assert "timeout" in result.lower() or "exit_code: -1" in result


async def test_shell_execute_no_zombie(tmp_path):
    """After timeout, no zombie processes remain."""
    result = await tool_shell_execute("sleep 60", timeout=2)
    assert "exit_code: -1" in result or "timeout" in result.lower()
    import subprocess

    zombie_check = subprocess.run(
        ["sh", "-c", "ps aux | grep 'sleep 60' | grep -v grep | wc -l"],
        capture_output=True,
        text=True,
    )
    count = int(zombie_check.stdout.strip())
    assert count == 0, f"Found {count} zombie sleep processes"


async def test_dispatch_shell_execute():
    result = await dispatch_tool(
        "shell_execute", {"command": "echo dispatch_test", "timeout": None}
    )
    assert "dispatch_test" in result


# ---- balance_check tests ----


async def test_balance_check_parse():
    """Test balance_check parses DeepSeek response correctly."""
    mock_response = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "12.50",
                "granted_balance": "2.50",
                "topped_up_balance": "10.00",
            }
        ],
    }

    with patch("evoclaw.tools.httpx.AsyncClient") as MockAsyncClient:
        # Create response mock (regular object, not async)
        mock_response_obj = MagicMock()
        mock_response_obj.json.return_value = mock_response
        mock_response_obj.raise_for_status.return_value = None

        # Create client mock that's async for get() but regular for context manager
        mock_client_instance = MagicMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response_obj)

        # Setup AsyncClient to work as async context manager
        MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance
        MockAsyncClient.return_value.__aexit__.return_value = None

        result = await tool_balance_check("https://api.deepseek.com", "test_key")

        assert "总余额: 12.50 CNY" in result
        assert "赠送: 2.50" in result
        assert "充值: 10.00" in result


async def test_balance_check_network_error():
    """Test balance_check handles network errors gracefully."""
    with patch("evoclaw.tools.httpx.AsyncClient") as MockAsyncClient:
        # Create client mock that raises error
        mock_client_instance = MagicMock()
        mock_client_instance.get = AsyncMock(side_effect=Exception("Network error"))

        # Setup AsyncClient to work as async context manager
        MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance
        MockAsyncClient.return_value.__aexit__.return_value = None

        result = await tool_balance_check("https://api.deepseek.com", "test_key")

        assert "Balance check failed" in result
        assert "Network error" in result


async def test_balance_check_empty_balance_infos():
    """Test balance_check handles empty balance_infos gracefully."""
    mock_response = {"is_available": True, "balance_infos": []}

    with patch("evoclaw.tools.httpx.AsyncClient") as MockAsyncClient:
        # Create response mock
        mock_response_obj = MagicMock()
        mock_response_obj.json.return_value = mock_response
        mock_response_obj.raise_for_status.return_value = None

        # Create client mock
        mock_client_instance = MagicMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response_obj)

        # Setup AsyncClient to work as async context manager
        MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance
        MockAsyncClient.return_value.__aexit__.return_value = None

        result = await tool_balance_check("https://api.deepseek.com", "test_key")

        assert "Balance check failed" in result


async def test_dispatch_balance_check_with_config():
    """Test dispatch_tool routes balance_check correctly with config."""
    config = Config(
        llm_api_base="https://api.deepseek.com",
        llm_api_key="test_key",
        angel_api_key="angel_key",
    )

    mock_response = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "50.00",
                "granted_balance": "10.00",
                "topped_up_balance": "40.00",
            }
        ],
    }

    with patch("evoclaw.tools.httpx.AsyncClient") as MockAsyncClient:
        # Create response mock
        mock_response_obj = MagicMock()
        mock_response_obj.json.return_value = mock_response
        mock_response_obj.raise_for_status.return_value = None

        # Create client mock
        mock_client_instance = MagicMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response_obj)

        # Setup AsyncClient to work as async context manager
        MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance
        MockAsyncClient.return_value.__aexit__.return_value = None

        result = await dispatch_tool("balance_check", {}, config=config)

        assert "总余额: 50.00 CNY" in result


async def test_dispatch_balance_check_without_config():
    """Test dispatch_tool balance_check returns error when config is None."""
    result = await dispatch_tool("balance_check", {}, config=None)

    assert "Balance check failed: no config provided" in result
