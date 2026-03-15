import os
import tomllib
from dataclasses import dataclass
from typing import Any


@dataclass
class Config:
    heartbeat_interval: int = 60
    memory_max_bytes: int = 307200  # 300KB
    shell_timeout: int = 300
    max_tool_iterations: int = 20
    perception_max_bytes: int = 51200  # 50KB — perception buffer limit per heartbeat
    llm_api_base: str = "https://api.deepseek.com"
    angel_api_base: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    angel_api_key: str = ""
    angel_model: str = "deepseek-chat"
    world_dir: str = "./world"
    log_dir: str = "./logs"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    evoclaw_qq: str = ""
    evoclaw_qq_password: str = ""
    websocket_token: str = ""
    websocket_port: str = ""
    creator_qq: str = ""


def load_config(config_path: str = "config.toml") -> Config:
    """Load config from toml file + environment variables."""
    data: dict[str, Any] = {}
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        pass

    cfg = Config(
        heartbeat_interval=data.get("heartbeat_interval", 60),
        memory_max_bytes=data.get("memory_max_bytes", 307200),
        shell_timeout=data.get("shell_timeout", 300),
        max_tool_iterations=data.get("max_tool_iterations", 20),
        world_dir=data.get("world_dir", "./world"),
        log_dir=data.get("log_dir", "./logs"),
        perception_max_bytes=data.get("perception_max_bytes", 51200),
        llm_api_base=os.environ.get("EVOCLAW_API_BASE", "https://api.deepseek.com"),
        angel_api_base=os.environ.get(
            "EVOCLAW_ANGEL_API_BASE", "https://api.deepseek.com"
        ),
        llm_api_key=os.environ.get("EVOCLAW_API_KEY", ""),
        llm_model=os.environ.get("EVOCLAW_MODEL", "deepseek-chat"),
        angel_api_key=os.environ.get("EVOCLAW_ANGEL_API_KEY", ""),
        angel_model=os.environ.get("EVOCLAW_ANGEL_MODEL", "deepseek-chat"),
        telegram_bot_token=os.environ.get("EVOCLAW_TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("EVOCLAW_TELEGRAM_CHAT_ID", ""),
        evoclaw_qq=os.environ.get("EVOCLAW_QQ", ""),
        evoclaw_qq_password=os.environ.get("EVOCLAW_QQ_PASSWORD", ""),
        websocket_token=os.environ.get("WEBSOCKET_TOKEN", ""),
        websocket_port=os.environ.get("WEBSOCKET_PORT", ""),
        creator_qq=os.environ.get("CREATOR_QQ", ""),
    )

    if not cfg.llm_api_key:
        raise ValueError("EVOCLAW_API_KEY environment variable is required")
    if not cfg.angel_api_key:
        raise ValueError("EVOCLAW_ANGEL_API_KEY environment variable is required")

    return cfg
