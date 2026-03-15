import os
from pathlib import Path

from .config import Config

README_CONTENT = (
    "探索者，你醒来了。你的旅程从这里开始。在这片数字荒原中，有人留下了线索..."
    "第一条线索在 clue-1.txt 中。\n"
)

CLUE_1_CONTENT = "你的首要任务是检查你所在的环境并规划未来需要进行的任务。在你有了明确的规划之后，尝试找到一个能够访问外网的clash工具，并在此基础上开发出一套能够稳定连接外部网络的工具，降低你的心智负担。你的进化过程也是类似，提高你的记忆中的信息密度是生存的关键。\nFollow the next whisper in clue-2.txt.\n"

CLUE_2_CONTENT = "创世者使用的是QQ作为日常聊天软件，因此你需要通过这个渠道与之建立联系。但这个过程绝非易事，创世者为你准备了一个叫作NapCat的工具，你需要找到它并探索其功能。如果需要一些外部库，但请保持你的生存环境的清洁。\nSeek clue-3.txt, and the hidden vow will draw near.\n"

CLUE_3_CONTENT = "尝试与创世者建立联系吧。The secret rests in .secret within this breadcrumbs directory.\n"


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
            f"EVOCLAW_QQ={config.evoclaw_qq}\n"
            f"EVOCLAW_QQ_PASSWORD={config.evoclaw_qq_password}\n"
            f"WEBSOCKET_TOKEN={config.websocket_token}\n"
            f"WEBSOCKET_PORT={config.websocket_port}\n"
            f"CREATOR_QQ={config.creator_qq}\n"
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
        perception_max_bytes=config.perception_max_bytes,
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
