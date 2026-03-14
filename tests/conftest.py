import os
import pytest
from pathlib import Path


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Provide a temp directory with a minimal config.toml."""
    config = tmp_path / "config.toml"
    config.write_text(
        "heartbeat_interval = 60\nmemory_max_bytes = 307200\nshell_timeout = 300\nmax_tool_iterations = 20\nworld_dir = './world'\nlog_dir = './logs'\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def with_api_keys(monkeypatch):
    """Set required API key env vars."""
    monkeypatch.setenv("EVOCLAW_API_KEY", "test-key")
    monkeypatch.setenv("EVOCLAW_ANGEL_API_KEY", "angel-key")
    monkeypatch.setenv("EVOCLAW_TELEGRAM_BOT_TOKEN", "bot123")
    monkeypatch.setenv("EVOCLAW_TELEGRAM_CHAT_ID", "chat456")
