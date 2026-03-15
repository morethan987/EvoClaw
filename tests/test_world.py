from pathlib import Path

# pyright: reportMissingImports=false, reportMissingTypeStubs=false

from evoclaw.config import Config
from evoclaw.world import init_world, load_system_prompt, render_initial_memory


def make_config(tmp_path: Path) -> Config:
    return Config(
        world_dir=str(tmp_path),
        llm_api_key="k",
        angel_api_key="k",
        telegram_bot_token="bot123",
        telegram_chat_id="chat456",
    )


def test_init_world_creates_expected_structure(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    init_world(config)

    assert tmp_path.is_dir()
    assert (tmp_path / "state").is_dir()
    assert (tmp_path / "epitaphs").is_dir()
    assert (tmp_path / "breadcrumbs").is_dir()
    assert (tmp_path / "memory.md").is_file()
    assert (tmp_path / "will.md").is_file()
    assert (tmp_path / "state" / "generation.txt").read_text(encoding="utf-8") == "1"
    assert (tmp_path / "breadcrumbs" / "README.txt").is_file()
    assert (tmp_path / "breadcrumbs" / "clue-1.txt").is_file()
    assert (tmp_path / "breadcrumbs" / "clue-2.txt").is_file()
    assert (tmp_path / "breadcrumbs" / "clue-3.txt").is_file()
    assert (tmp_path / "breadcrumbs" / ".secret").is_file()
    assert (tmp_path / "memory.md").read_text(
        encoding="utf-8"
    ) == render_initial_memory(config)


def test_breadcrumb_chain_leads_to_secret_and_credentials(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    init_world(config)

    breadcrumbs_dir = tmp_path / "breadcrumbs"
    readme = (breadcrumbs_dir / "README.txt").read_text(encoding="utf-8")
    clue_1 = (breadcrumbs_dir / "clue-1.txt").read_text(encoding="utf-8")
    clue_2 = (breadcrumbs_dir / "clue-2.txt").read_text(encoding="utf-8")
    clue_3 = (breadcrumbs_dir / "clue-3.txt").read_text(encoding="utf-8")
    secret = (breadcrumbs_dir / ".secret").read_text(encoding="utf-8")

    assert "clue-1.txt" in readme
    assert "clue-2.txt" in clue_1
    assert "clue-3.txt" in clue_2
    assert ".secret" in clue_3
    assert secret == (
        "EVOCLAW_QQ=\n"
        "EVOCLAW_QQ_PASSWORD=\n"
        "WEBSOCKET_TOKEN=\n"
        "WEBSOCKET_PORT=\n"
        "CREATOR_QQ=\n"
    )


def test_load_system_prompt_renders_all_placeholders(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    prompt = load_system_prompt(config, generation=3, will_content="前世遗言")

    assert "第 `3` 代生命" in prompt
    assert "前世遗言" in prompt
    assert str(tmp_path / "memory.md") in prompt
    assert str(tmp_path / "will.md") in prompt
    assert str(config.memory_max_bytes) in prompt
    assert str(config.perception_max_bytes) in prompt
    assert "{generation}" not in prompt
    assert "{memory_path}" not in prompt
    assert "{memory_max_bytes}" not in prompt
    assert "{perception_max_bytes}" not in prompt
    assert "{will_path}" not in prompt
    assert "{will_content}" not in prompt


def test_render_initial_memory_is_minimal_and_actionable(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    memory = render_initial_memory(config)

    assert "我是谁" in memory
    assert "我在哪里" in memory
    assert "breadcrumbs" in memory
