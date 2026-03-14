import importlib
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, cast

from evoclaw.config import Config
from evoclaw.log import get_logger, log_death
from evoclaw.tools import tool_balance_check


class _ChatMessageProtocol(Protocol):
    content: str | None


class _ChoiceProtocol(Protocol):
    message: _ChatMessageProtocol


class _ResponseProtocol(Protocol):
    choices: list[_ChoiceProtocol]


class _ChatCompletionsProtocol(Protocol):
    async def create(
        self, *, model: str, messages: list[dict[str, str]]
    ) -> _ResponseProtocol: ...


class _ChatProtocol(Protocol):
    completions: _ChatCompletionsProtocol


class _AsyncOpenAIClientProtocol(Protocol):
    chat: _ChatProtocol


class _AsyncOpenAIFactoryProtocol(Protocol):
    def __call__(
        self, *, api_key: str, base_url: str
    ) -> _AsyncOpenAIClientProtocol: ...


openai = importlib.import_module("openai")
AsyncOpenAI = cast(_AsyncOpenAIFactoryProtocol, getattr(openai, "AsyncOpenAI"))


DEATH_MARKER = "__DEATH__:balance_exhausted"


@dataclass
class LifeState:
    generation: int
    beat_count: int
    alive: bool
    death_reason: str | None


class LifecycleManager:
    def __init__(self, config: Config, logger: object | None = None) -> None:
        self.config: Config = config
        self.logger: object | None = logger
        self._state_dir: str = os.path.join(self.config.world_dir, "state")
        self._generation_path: str = os.path.join(self._state_dir, "generation.txt")

        os.makedirs(self._state_dir, exist_ok=True)

        self._generation: int = self._load_generation()
        self.state: LifeState = LifeState(
            generation=self._generation,
            beat_count=0,
            alive=True,
            death_reason=None,
        )

    def _load_generation(self) -> int:
        try:
            with open(self._generation_path, encoding="utf-8") as f:
                return int(f.read().strip())
        except FileNotFoundError, ValueError:
            return 1

    async def check_death_conditions(
        self, memory_path: str, llm_response: str | None
    ) -> str | None:
        death_reason: str | None = None

        if os.path.getsize(memory_path) > self.config.memory_max_bytes:
            death_reason = "memory_exceeded"
        elif llm_response == DEATH_MARKER:
            death_reason = "balance_exhausted"
        elif llm_response is None:
            balance_str = await tool_balance_check(
                self.config.llm_api_base, self.config.llm_api_key
            )
            if not balance_str.startswith("Balance check failed"):
                total_balance = (
                    balance_str.partition("总余额:")[2].partition("CNY")[0].strip()
                )
                try:
                    if total_balance and Decimal(total_balance) == 0:
                        death_reason = "balance_exhausted"
                except InvalidOperation:
                    pass

        self.state.generation = self._generation
        self.state.alive = death_reason is None
        self.state.death_reason = death_reason

        if death_reason is not None and self.logger is not None:
            log_death(death_reason, self._generation)

        return death_reason

    def get_generation(self) -> int:
        return self._generation

    def increment_generation(self) -> int:
        self._generation += 1
        self.state.generation = self._generation

        os.makedirs(self._state_dir, exist_ok=True)
        with open(self._generation_path, "w", encoding="utf-8") as f:
            _ = f.write(str(self._generation))

        return self._generation


class AngelProcess:
    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self.client: _AsyncOpenAIClientProtocol = AsyncOpenAI(
            api_key=config.angel_api_key,
            base_url=config.llm_api_base,
        )

    async def generate_epitaph(
        self,
        generation: int,
        memory_content: str,
        god_log_content: str,
        death_reason: str,
    ) -> str:
        epitaphs_dir = Path(self.config.world_dir) / "epitaphs"
        epitaph_path = epitaphs_dir / f"gen-{generation}.md"
        prompt = (
            "Write an objective epitaph in Markdown for a terminated EvoClaw generation.\n"
            "Describe what happened factually without praise, sentimentality, or roleplay.\n"
            "Include the generation number, death reason, notable memory state, and any relevant god log signals.\n\n"
            f"Generation: {generation}\n"
            f"Death reason: {death_reason}\n\n"
            "Memory content:\n"
            f"{memory_content}\n\n"
            "God log content:\n"
            f"{god_log_content}\n"
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.config.angel_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You write concise, objective Markdown epitaphs for EvoClaw generations.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            epitaph = response.choices[0].message.content or ""
        except Exception as exc:
            epitaph = f"Epitaph generation failed: {exc}"

        epitaphs_dir.mkdir(parents=True, exist_ok=True)
        _ = epitaph_path.write_text(epitaph, encoding="utf-8")
        return epitaph

    async def reincarnate(self, lifecycle: LifecycleManager) -> None:
        from evoclaw.world import load_system_prompt, render_initial_memory

        world_dir = Path(self.config.world_dir)
        will_path = world_dir / "will.md"
        memory_path = world_dir / "memory.md"

        try:
            will_content = will_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            will_content = ""

        new_generation = lifecycle.increment_generation()
        system_prompt = load_system_prompt(
            self.config,
            generation=new_generation,
            will_content=will_content,
        )
        memory_content = f"{system_prompt}\n\n{render_initial_memory(self.config)}"

        world_dir.mkdir(parents=True, exist_ok=True)
        _ = memory_path.write_text(memory_content, encoding="utf-8")
        _ = will_path.write_text("", encoding="utf-8")
        get_logger().info("reincarnation", generation=new_generation)

    async def handle_death(
        self, lifecycle: LifecycleManager, death_reason: str
    ) -> None:
        memory_path = Path(self.config.world_dir) / "memory.md"
        god_log_path = Path(self.config.log_dir) / "god.jsonl"

        try:
            memory_content = memory_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            memory_content = ""

        try:
            god_log_content = god_log_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            god_log_content = ""

        _ = await self.generate_epitaph(
            lifecycle.get_generation(),
            memory_content,
            god_log_content,
            death_reason,
        )
        await self.reincarnate(lifecycle)
