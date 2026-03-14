# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnusedCallResult=false

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

from evoclaw.config import Config
from evoclaw.lifecycle import AngelProcess, LifeState, LifecycleManager


@dataclass
class FakeMessage:
    content: str | None


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeResponse:
    choices: list[FakeChoice]


class FakeCompletions:
    def __init__(self, response: FakeResponse) -> None:
        self._response: FakeResponse = response

    async def create(self, *args: object, **kwargs: object) -> FakeResponse:
        _ = args, kwargs
        return self._response


class FakeChat:
    def __init__(self, response: FakeResponse) -> None:
        self.completions: FakeCompletions = FakeCompletions(response)


class FakeOpenAIClient:
    def __init__(self, response: FakeResponse) -> None:
        self.chat: FakeChat = FakeChat(response)


def make_config(tmp_path: Path, **overrides: object) -> Config:
    config = Config(
        llm_api_key="test-key",
        angel_api_key="angel-key",
        world_dir=str(tmp_path / "world"),
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def test_lifecycle_manager_defaults_generation_and_creates_state_dir(tmp_path: Path):
    config = make_config(tmp_path)

    manager = LifecycleManager(config)

    assert manager.get_generation() == 1
    assert manager.state == LifeState(
        generation=1,
        beat_count=0,
        alive=True,
        death_reason=None,
    )
    assert (tmp_path / "world" / "state").is_dir()


def test_lifecycle_manager_loads_existing_generation(tmp_path: Path):
    generation_file = tmp_path / "world" / "state" / "generation.txt"
    generation_file.parent.mkdir(parents=True)
    generation_file.write_text("7", encoding="utf-8")
    config = make_config(tmp_path)

    manager = LifecycleManager(config)

    assert manager.get_generation() == 7
    assert manager.state.generation == 7


def test_lifecycle_manager_invalid_generation_defaults_to_one(tmp_path: Path):
    generation_file = tmp_path / "world" / "state" / "generation.txt"
    generation_file.parent.mkdir(parents=True)
    generation_file.write_text("not-an-int", encoding="utf-8")
    config = make_config(tmp_path)

    manager = LifecycleManager(config)

    assert manager.get_generation() == 1


async def test_check_death_conditions_detects_memory_exceeded(tmp_path: Path):
    config = make_config(tmp_path, memory_max_bytes=1000)
    memory_path = tmp_path / "memory.txt"
    memory_path.write_bytes(b"x" * 1500)

    with patch("evoclaw.lifecycle.log_death") as mock_log_death:
        manager = LifecycleManager(config, logger=object())

        result = await manager.check_death_conditions(str(memory_path), None)

    assert result == "memory_exceeded"
    assert manager.state.alive is False
    assert manager.state.death_reason == "memory_exceeded"
    mock_log_death.assert_called_once_with("memory_exceeded", 1)


async def test_check_death_conditions_detects_balance_exhausted_marker(tmp_path: Path):
    config = make_config(tmp_path, memory_max_bytes=1000)
    memory_path = tmp_path / "memory.txt"
    memory_path.write_bytes(b"x" * 100)

    with patch("evoclaw.lifecycle.log_death") as mock_log_death:
        manager = LifecycleManager(config, logger=object())

        result = await manager.check_death_conditions(
            str(memory_path), "__DEATH__:balance_exhausted"
        )

    assert result == "balance_exhausted"
    assert manager.state.alive is False
    assert manager.state.death_reason == "balance_exhausted"
    mock_log_death.assert_called_once_with("balance_exhausted", 1)


async def test_check_death_conditions_returns_none_when_healthy(tmp_path: Path):
    config = make_config(tmp_path, memory_max_bytes=1000)
    memory_path = tmp_path / "memory.txt"
    memory_path.write_bytes(b"x" * 100)
    with patch(
        "evoclaw.lifecycle.tool_balance_check", new_callable=AsyncMock
    ) as mock_balance_check:
        manager = LifecycleManager(config)

        result = await manager.check_death_conditions(str(memory_path), "normal text")

    assert result is None
    assert manager.state.alive is True
    assert manager.state.death_reason is None
    mock_balance_check.assert_not_awaited()


async def test_check_death_conditions_does_not_log_without_logger(tmp_path: Path):
    config = make_config(tmp_path, memory_max_bytes=1000)
    memory_path = tmp_path / "memory.txt"
    memory_path.write_bytes(b"x" * 1500)

    with patch("evoclaw.lifecycle.log_death") as mock_log_death:
        manager = LifecycleManager(config)

        result = await manager.check_death_conditions(str(memory_path), None)

    assert result == "memory_exceeded"
    mock_log_death.assert_not_called()


async def test_check_death_conditions_detects_zero_balance(tmp_path: Path):
    config = make_config(tmp_path, memory_max_bytes=1000)
    memory_path = tmp_path / "memory.txt"
    memory_path.write_bytes(b"x" * 100)

    with (
        patch(
            "evoclaw.lifecycle.tool_balance_check", new_callable=AsyncMock
        ) as mock_balance_check,
        patch("evoclaw.lifecycle.log_death") as mock_log_death,
    ):
        mock_balance_check.return_value = "总余额: 0.00 CNY, 赠送: 0.00, 充值: 0.00"
        manager = LifecycleManager(config, logger=object())

        result = await manager.check_death_conditions(str(memory_path), None)

    assert result == "balance_exhausted"
    assert manager.state.alive is False
    assert manager.state.death_reason == "balance_exhausted"
    mock_balance_check.assert_awaited_once_with(config.llm_api_base, config.llm_api_key)
    mock_log_death.assert_called_once_with("balance_exhausted", 1)


async def test_check_death_conditions_ignores_balance_check_failures(tmp_path: Path):
    config = make_config(tmp_path, memory_max_bytes=1000)
    memory_path = tmp_path / "memory.txt"
    memory_path.write_bytes(b"x" * 100)

    with patch(
        "evoclaw.lifecycle.tool_balance_check", new_callable=AsyncMock
    ) as mock_balance_check:
        mock_balance_check.return_value = "Balance check failed: timeout"
        manager = LifecycleManager(config)

        result = await manager.check_death_conditions(str(memory_path), None)

    assert result is None
    assert manager.state.alive is True
    assert manager.state.death_reason is None
    mock_balance_check.assert_awaited_once_with(config.llm_api_base, config.llm_api_key)


def test_increment_generation_persists_counter(tmp_path: Path):
    config = make_config(tmp_path)
    manager = LifecycleManager(config)

    new_generation = manager.increment_generation()

    assert new_generation == 2
    assert manager.get_generation() == 2
    assert manager.state.generation == 2
    assert (tmp_path / "world" / "state" / "generation.txt").read_text(
        encoding="utf-8"
    ) == "2"

    reloaded_manager = LifecycleManager(config)
    assert reloaded_manager.get_generation() == 2


async def test_angel_generate_epitaph_saves_file(tmp_path: Path) -> None:
    config = make_config(tmp_path, log_dir=str(tmp_path / "logs"))
    response = FakeResponse([FakeChoice(FakeMessage("# Epitaph\n\nobjective record"))])

    with patch("evoclaw.lifecycle.AsyncOpenAI") as mock_openai:
        mock_openai.return_value = FakeOpenAIClient(response)

        angel = AngelProcess(config)
        result = await angel.generate_epitaph(
            1,
            "mem content",
            "log content",
            "memory_exceeded",
        )

    epitaph_path = tmp_path / "world" / "epitaphs" / "gen-1.md"
    assert result == "# Epitaph\n\nobjective record"
    assert epitaph_path.read_text(encoding="utf-8") == result


async def test_angel_reincarnate_increments_generation(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    world_dir = tmp_path / "world"
    state_dir = world_dir / "state"
    state_dir.mkdir(parents=True)
    _ = (state_dir / "generation.txt").write_text("1", encoding="utf-8")
    _ = (world_dir / "will.md").write_text("前世的智慧", encoding="utf-8")
    manager = LifecycleManager(config)

    with patch("evoclaw.lifecycle.AsyncOpenAI"):
        angel = AngelProcess(config)

    await angel.reincarnate(manager)

    assert (world_dir / "state" / "generation.txt").read_text(encoding="utf-8") == "2"
    memory_content = (world_dir / "memory.md").read_text(encoding="utf-8")
    assert "前世的智慧" in memory_content
    assert "第 `2` 代生命" in memory_content
    assert (world_dir / "will.md").read_text(encoding="utf-8") == ""


async def test_angel_reincarnate_no_will(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    world_dir = tmp_path / "world"
    state_dir = world_dir / "state"
    state_dir.mkdir(parents=True)
    _ = (state_dir / "generation.txt").write_text("1", encoding="utf-8")
    manager = LifecycleManager(config)

    with patch("evoclaw.lifecycle.AsyncOpenAI"):
        angel = AngelProcess(config)

    await angel.reincarnate(manager)

    assert (world_dir / "state" / "generation.txt").read_text(encoding="utf-8") == "2"
    assert (world_dir / "memory.md").is_file()
    assert (world_dir / "will.md").read_text(encoding="utf-8") == ""


async def test_angel_handle_death_full_flow(tmp_path: Path) -> None:
    config = make_config(tmp_path, log_dir=str(tmp_path / "logs"))
    world_dir = tmp_path / "world"
    state_dir = world_dir / "state"
    logs_dir = tmp_path / "logs"
    response = FakeResponse([FakeChoice(FakeMessage("# Epitaph\n\nfinal record"))])
    state_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    _ = (state_dir / "generation.txt").write_text("1", encoding="utf-8")
    _ = (world_dir / "memory.md").write_text("current memory", encoding="utf-8")
    _ = (world_dir / "will.md").write_text("遗愿延续", encoding="utf-8")
    _ = (logs_dir / "god.jsonl").write_text('{"event":"heartbeat"}\n', encoding="utf-8")
    manager = LifecycleManager(config)

    with patch("evoclaw.lifecycle.AsyncOpenAI") as mock_openai:
        mock_openai.return_value = FakeOpenAIClient(response)

        angel = AngelProcess(config)
        await angel.handle_death(manager, "memory_exceeded")

    assert (world_dir / "epitaphs" / "gen-1.md").read_text(encoding="utf-8") == (
        "# Epitaph\n\nfinal record"
    )
    assert manager.get_generation() == 2
    assert (world_dir / "state" / "generation.txt").read_text(encoding="utf-8") == "2"
    memory_content = (world_dir / "memory.md").read_text(encoding="utf-8")
    assert "遗愿延续" in memory_content
    assert (world_dir / "will.md").read_text(encoding="utf-8") == ""
