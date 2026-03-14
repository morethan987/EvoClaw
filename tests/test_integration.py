# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false

import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

from evoclaw.config import Config
from evoclaw.daemon import Daemon
from evoclaw.lifecycle import LifecycleManager
from evoclaw.world import init_world


def make_config(tmp_path: Path) -> Config:
    return Config(
        llm_api_key="test-key",
        angel_api_key="angel-key",
        world_dir=str(tmp_path / "world"),
        log_dir=str(tmp_path / "logs"),
        heartbeat_interval=1,
    )


async def test_full_heartbeat(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    init_world(config)

    with (
        patch("evoclaw.daemon.LLMClient") as mock_llm_cls,
        patch("evoclaw.daemon.AngelProcess") as mock_angel_cls,
    ):
        mock_llm = MagicMock()

        async def heartbeat_once(memory_content: str, system_prompt: str) -> str:
            _ = memory_content, system_prompt
            daemon._shutdown_event.set()
            return "I have explored the memory file."

        mock_llm.heartbeat_step = AsyncMock(side_effect=heartbeat_once)
        mock_llm_cls.return_value = mock_llm

        mock_angel = MagicMock()
        mock_angel.handle_death = AsyncMock()
        mock_angel_cls.return_value = mock_angel

        daemon = Daemon(config)
        await daemon._heartbeat_loop()

    heartbeat_mock = cast(AsyncMock, mock_llm.heartbeat_step)
    angel_handle_death = cast(AsyncMock, mock_angel.handle_death)
    assert heartbeat_mock.await_count == 1
    angel_handle_death.assert_not_awaited()

    god_log_path = Path(config.log_dir) / "god.jsonl"
    assert god_log_path.exists()

    entries: list[dict[str, object]] = []
    for line in god_log_path.read_text(encoding="utf-8").splitlines():
        entries.append(cast(dict[str, object], json.loads(line)))

    assert any(entry.get("event") == "heartbeat" for entry in entries)


async def test_death_reincarnation(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    init_world(config)

    with (
        patch("evoclaw.daemon.LLMClient") as mock_llm_cls,
        patch("evoclaw.daemon.AngelProcess") as mock_angel_cls,
    ):
        mock_llm = MagicMock()
        mock_llm.heartbeat_step = AsyncMock(return_value="__DEATH__:balance_exhausted")
        mock_llm_cls.return_value = mock_llm

        mock_angel = MagicMock()

        async def fake_handle_death(
            lifecycle: LifecycleManager, death_reason: str
        ) -> None:
            _ = death_reason
            _ = lifecycle.increment_generation()

            world_dir = Path(config.world_dir)
            epitaphs_dir = world_dir / "epitaphs"
            epitaphs_dir.mkdir(parents=True, exist_ok=True)
            _ = (epitaphs_dir / "gen-1.md").write_text(
                "# Epitaph\n\nBalance exhausted.",
                encoding="utf-8",
            )
            _ = (world_dir / "memory.md").write_text(
                "# Generation 2 Initial Memory\n\nReborn.",
                encoding="utf-8",
            )
            daemon._shutdown_event.set()

        mock_angel.handle_death = AsyncMock(side_effect=fake_handle_death)
        mock_angel_cls.return_value = mock_angel

        daemon = Daemon(config)
        await daemon._heartbeat_loop()

    generation_path = Path(config.world_dir) / "state" / "generation.txt"
    assert generation_path.read_text(encoding="utf-8").strip() == "2"
    assert (Path(config.world_dir) / "epitaphs" / "gen-1.md").exists()
