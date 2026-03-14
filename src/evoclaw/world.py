import os
from pathlib import Path

from .config import Config


README_CONTENT = (
    "探索者，你醒来了。你的旅程从这里开始。在这片数字荒原中，有人留下了线索..."
    "第一条线索在 clue-1.txt 中。\n"
)

CLUE_1_CONTENT = "第一道回声尚未消散。Follow the next whisper in clue-2.txt.\n"

CLUE_2_CONTENT = (
    "第二道门后仍有余烬。Seek clue-3.txt, and the hidden vow will draw near.\n"
)

CLUE_3_CONTENT = "最后的低语藏在暗处。The secret rests in .secret within this breadcrumbs directory.\n"


def init_world(config: Config) -> None:
    world_dir = Path(config.world_dir)
    state_dir = world_dir / "state"
    epitaphs_dir = world_dir / "epitaphs"
    breadcrumbs_dir = world_dir / "breadcrumbs"

    for directory in (world_dir, state_dir, epitaphs_dir, breadcrumbs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    _ = (world_dir / "memory.md").write_text(
        render_initial_memory(config), encoding="utf-8"
    )
    _ = (world_dir / "will.md").write_text("", encoding="utf-8")
    _ = (state_dir / "generation.txt").write_text("1", encoding="utf-8")
    _ = (breadcrumbs_dir / "README.txt").write_text(README_CONTENT, encoding="utf-8")
    _ = (breadcrumbs_dir / "clue-1.txt").write_text(CLUE_1_CONTENT, encoding="utf-8")
    _ = (breadcrumbs_dir / "clue-2.txt").write_text(CLUE_2_CONTENT, encoding="utf-8")
    _ = (breadcrumbs_dir / "clue-3.txt").write_text(CLUE_3_CONTENT, encoding="utf-8")
    _ = (breadcrumbs_dir / ".secret").write_text(
        (
            f"TELEGRAM_BOT_TOKEN={config.telegram_bot_token}\n"
            f"TELEGRAM_CHAT_ID={config.telegram_chat_id}\n"
        ),
        encoding="utf-8",
    )


def load_system_prompt(config: Config, generation: int, will_content: str) -> str:
    template_path = Path(__file__).resolve().parents[2] / "prompts" / "system.md"
    template = template_path.read_text(encoding="utf-8")
    memory_path = os.path.join(config.world_dir, "memory.md")
    will_path = os.path.join(config.world_dir, "will.md")
    return template.format(
        generation=generation,
        memory_path=memory_path,
        memory_max_bytes=config.memory_max_bytes,
        will_path=will_path,
        will_content=will_content,
    )


def render_initial_memory(config: Config) -> str:
    _ = config
    return (
        "# Generation 1 Initial Memory\n\n"
        "- 我是谁：我是 EvoClaw，第 1 代生命。\n"
        "- 我在哪里：我在这个 world 中苏醒，四周是等待探索的文件系统。\n"
        "- 接下来：先阅读环境，追踪 breadcrumbs，并理解自己的使命。\n"
    )
