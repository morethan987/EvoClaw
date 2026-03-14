import os
import pytest
from evoclaw.config import load_config, Config


def test_config_loads_with_env_vars(tmp_config_dir, with_api_keys):
    cfg = load_config(str(tmp_config_dir / "config.toml"))
    assert cfg.heartbeat_interval == 60
    assert cfg.memory_max_bytes == 307200
    assert cfg.llm_api_key == "test-key"
    assert cfg.angel_api_key == "angel-key"
    assert cfg.llm_api_base == "https://api.deepseek.com"
    assert cfg.llm_model == "deepseek-chat"


def test_config_defaults(tmp_config_dir, with_api_keys):
    cfg = load_config(str(tmp_config_dir / "config.toml"))
    assert cfg.shell_timeout == 300
    assert cfg.max_tool_iterations == 20
    assert cfg.world_dir == "./world"
    assert cfg.log_dir == "./logs"


def test_config_missing_api_key(tmp_config_dir, monkeypatch):
    monkeypatch.delenv("EVOCLAW_API_KEY", raising=False)
    monkeypatch.delenv("EVOCLAW_ANGEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="EVOCLAW_API_KEY"):
        load_config(str(tmp_config_dir / "config.toml"))


def test_config_missing_angel_key(tmp_config_dir, monkeypatch):
    monkeypatch.setenv("EVOCLAW_API_KEY", "test-key")
    monkeypatch.delenv("EVOCLAW_ANGEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="EVOCLAW_ANGEL_API_KEY"):
        load_config(str(tmp_config_dir / "config.toml"))


def test_config_no_toml_file(tmp_path, with_api_keys):
    """Config should still load using env vars even if toml is missing."""
    cfg = load_config(str(tmp_path / "nonexistent.toml"))
    assert cfg.llm_api_key == "test-key"


def test_config_env_override(tmp_config_dir, monkeypatch):
    monkeypatch.setenv("EVOCLAW_API_KEY", "override-key")
    monkeypatch.setenv("EVOCLAW_ANGEL_API_KEY", "angel-key")
    monkeypatch.setenv("EVOCLAW_API_BASE", "https://custom.api.com")
    cfg = load_config(str(tmp_config_dir / "config.toml"))
    assert cfg.llm_api_key == "override-key"
    assert cfg.llm_api_base == "https://custom.api.com"
