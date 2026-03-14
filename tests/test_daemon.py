# pyright: reportMissingTypeStubs=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportMissingParameterType=false, reportPrivateUsage=false

import os
import sys
from collections.abc import Coroutine, Generator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from evoclaw.config import Config
from evoclaw.daemon import Daemon


type DaemonFixture = tuple[Daemon, Config, MagicMock, MagicMock]


def make_config(tmp_path: Path, **overrides: object) -> Config:
    config = Config(
        llm_api_key="test-key",
        angel_api_key="angel-key",
        world_dir=str(tmp_path / "world"),
        log_dir=str(tmp_path / "logs"),
        heartbeat_interval=1,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def prepare_world(config: Config) -> None:
    world_dir = Path(config.world_dir)
    world_dir.mkdir(parents=True, exist_ok=True)
    _ = (world_dir / "memory.md").write_text("memory", encoding="utf-8")
    _ = (world_dir / "will.md").write_text("", encoding="utf-8")


@pytest.fixture
def daemon_with_mocks(tmp_path: Path) -> Generator[DaemonFixture, None, None]:
    config = make_config(tmp_path)
    prepare_world(config)
    with (
        patch("evoclaw.daemon.LLMClient") as mock_llm_cls,
        patch("evoclaw.daemon.AngelProcess") as mock_angel_cls,
    ):
        mock_llm = MagicMock()
        mock_llm.heartbeat_step = AsyncMock(return_value="ok")
        mock_llm_cls.return_value = mock_llm

        mock_angel = MagicMock()
        mock_angel.handle_death = AsyncMock()
        mock_angel_cls.return_value = mock_angel

        daemon = Daemon(config)
        yield daemon, config, mock_llm, mock_angel


async def test_pid_file_created(daemon_with_mocks: DaemonFixture):
    daemon, config, _, _ = daemon_with_mocks
    pid_path = Path(config.world_dir) / "evoclaw.pid"
    observed = {"created": False}

    async def fake_heartbeat_loop() -> None:
        observed["created"] = pid_path.exists()
        await daemon._shutdown()

    daemon._heartbeat_loop = fake_heartbeat_loop  # type: ignore[method-assign]
    await daemon.run()

    assert observed["created"] is True


async def test_pid_file_deleted_on_shutdown(daemon_with_mocks: DaemonFixture):
    daemon, config, _, _ = daemon_with_mocks
    pid_path = Path(config.world_dir) / "evoclaw.pid"

    async def fake_heartbeat_loop() -> None:
        await daemon._shutdown()

    daemon._heartbeat_loop = fake_heartbeat_loop  # type: ignore[method-assign]
    await daemon.run()

    assert not pid_path.exists()


async def test_duplicate_instance_prevented(tmp_path: Path):
    config = make_config(tmp_path)
    prepare_world(config)
    pid_path = Path(config.world_dir) / "evoclaw.pid"
    _ = pid_path.write_text(str(os.getpid()), encoding="utf-8")

    with (
        patch("evoclaw.daemon.LLMClient"),
        patch("evoclaw.daemon.AngelProcess"),
    ):
        daemon = Daemon(config)
        with pytest.raises(RuntimeError, match="already running"):
            await daemon.run()


async def test_heartbeat_executes_once(daemon_with_mocks: DaemonFixture):
    daemon, _, mock_llm, _ = daemon_with_mocks

    async def heartbeat_once(memory_content: str, system_prompt: str) -> str:
        _ = memory_content, system_prompt
        daemon._shutdown_event.set()
        return "hello"

    mock_llm.heartbeat_step = AsyncMock(side_effect=heartbeat_once)

    with patch("evoclaw.daemon.load_system_prompt", return_value="system"):
        await daemon._heartbeat_loop()

    heartbeat_mock = cast(AsyncMock, mock_llm.heartbeat_step)
    assert heartbeat_mock.await_count == 1


async def test_shutdown_event_stops_loop(daemon_with_mocks: DaemonFixture):
    daemon, _, mock_llm, _ = daemon_with_mocks
    daemon._shutdown_event.set()

    await daemon._heartbeat_loop()

    heartbeat_mock = cast(AsyncMock, mock_llm.heartbeat_step)
    heartbeat_mock.assert_not_awaited()


def test_cli_argparse_start(monkeypatch: pytest.MonkeyPatch):
    import evoclaw.__main__ as main_module

    daemon_instance = SimpleNamespace(run=AsyncMock(return_value=None))

    monkeypatch.setattr(sys, "argv", ["evoclaw", "start"])
    with (
        patch("evoclaw.__main__.load_config", return_value=make_config(Path("."))),
        patch(
            "evoclaw.__main__.Daemon", return_value=daemon_instance
        ) as mock_daemon_cls,
        patch("evoclaw.__main__.asyncio.run") as mock_asyncio_run,
    ):
        main_module.main()

    mock_daemon_cls.assert_called_once()
    mock_asyncio_run.assert_called_once()
    run_arg = cast(
        Coroutine[object, object, object], mock_asyncio_run.call_args.args[0]
    )
    run_arg.close()


def test_cli_argparse_init_world(monkeypatch: pytest.MonkeyPatch):
    import evoclaw.__main__ as main_module

    monkeypatch.setattr(sys, "argv", ["evoclaw", "init-world"])
    with (
        patch("evoclaw.__main__.load_config", return_value=make_config(Path("."))),
        patch("evoclaw.__main__.init_world") as mock_init_world,
    ):
        main_module.main()

    mock_init_world.assert_called_once()
