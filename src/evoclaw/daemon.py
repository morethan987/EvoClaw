import asyncio
import fcntl
import os
import signal
from typing import Protocol

from evoclaw.config import Config
from evoclaw.lifecycle import AngelProcess, LifecycleManager
from evoclaw.llm import LLMClient
from evoclaw.log import (
    close_logging,
    get_logger,
    log_death,
    log_heartbeat,
    setup_logging,
)
from evoclaw.world import load_system_prompt


class _LoggerProtocol(Protocol):
    def warning(self, event: str, **kw: object) -> object: ...

    def info(self, event: str, **kw: object) -> object: ...


class Daemon:
    def __init__(self, config: Config) -> None:
        self._config: Config = config
        self._pid_path: str = os.path.join(config.world_dir, "evoclaw.pid")
        self._pid_fd: int | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._cleanup_done: bool = False

        self._lifecycle: LifecycleManager = LifecycleManager(config)
        setup_logging(config.log_dir, self._lifecycle.get_generation())
        self._logger: _LoggerProtocol = get_logger()
        self._llm: LLMClient = LLMClient(config)
        self._angel: AngelProcess = AngelProcess(config)

    def _create_pid_file(self) -> None:
        os.makedirs(self._config.world_dir, exist_ok=True)

        if os.path.exists(self._pid_path):
            try:
                with open(self._pid_path, encoding="utf-8") as f:
                    existing_pid = int(f.read().strip())
                os.kill(existing_pid, 0)
                raise RuntimeError("already running")
            except ProcessLookupError:
                os.unlink(self._pid_path)
            except FileNotFoundError:
                pass
            except ValueError:
                os.unlink(self._pid_path)

        fd = os.open(self._pid_path, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _ = os.write(fd, str(os.getpid()).encode("utf-8"))
        os.fsync(fd)
        self._pid_fd = fd

    def _cleanup_pid_file(self) -> None:
        if self._cleanup_done:
            return
        self._cleanup_done = True

        try:
            os.unlink(self._pid_path)
        except FileNotFoundError:
            pass

        if self._pid_fd is not None:
            os.close(self._pid_fd)
            self._pid_fd = None

    async def run(self) -> None:
        self._create_pid_file()
        loop = asyncio.get_running_loop()

        try:
            loop.add_signal_handler(
                signal.SIGTERM,
                lambda: asyncio.ensure_future(self._shutdown()),
            )
            loop.add_signal_handler(
                signal.SIGINT,
                lambda: asyncio.ensure_future(self._shutdown()),
            )
        except NotImplementedError, RuntimeError:
            _ = self._logger.warning("signal_handlers_unavailable")

        try:
            await self._heartbeat_loop()
        finally:
            self._cleanup_pid_file()
            close_logging()

    async def _heartbeat_loop(self) -> None:
        loop = asyncio.get_event_loop()
        next_beat = loop.time() + self._config.heartbeat_interval
        beat_count = 0
        memory_path = os.path.join(self._config.world_dir, "memory.md")
        will_path = os.path.join(self._config.world_dir, "will.md")

        while not self._shutdown_event.is_set():
            try:
                with open(memory_path, encoding="utf-8") as f:
                    memory_content = f.read()
            except FileNotFoundError:
                memory_content = ""
                with open(memory_path, "w", encoding="utf-8") as f:
                    _ = f.write("")

            death_reason = await self._lifecycle.check_death_conditions(
                memory_path, llm_response=None
            )
            if death_reason is not None:
                log_death(death_reason, self._lifecycle.get_generation())
                await self._angel.handle_death(self._lifecycle, death_reason)
                # Cooldown: wait a full heartbeat interval before re-entering
                # the loop to prevent a tight spin if the death condition
                # persists across reincarnations (e.g. balance_exhausted).
                try:
                    _ = await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=float(self._config.heartbeat_interval),
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            try:
                with open(will_path, encoding="utf-8") as f:
                    will_content = f.read()
            except FileNotFoundError:
                will_content = ""

            system_prompt = load_system_prompt(
                self._config,
                generation=self._lifecycle.get_generation(),
                will_content=will_content,
            )
            llm_response = await self._llm.heartbeat_step(memory_content, system_prompt)

            death_reason = await self._lifecycle.check_death_conditions(
                memory_path, llm_response=llm_response
            )
            if death_reason is not None:
                log_death(death_reason, self._lifecycle.get_generation())
                await self._angel.handle_death(self._lifecycle, death_reason)
                try:
                    _ = await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=float(self._config.heartbeat_interval),
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            log_heartbeat(
                beat_number=beat_count,
                memory_size=os.path.getsize(memory_path),
                balance=None,
                tool_calls=0,
            )
            beat_count += 1

            sleep_time = max(0.0, next_beat - loop.time())
            try:
                _ = await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=sleep_time
                )
            except asyncio.TimeoutError:
                pass
            next_beat += self._config.heartbeat_interval

    async def _shutdown(self) -> None:
        self._shutdown_event.set()
        self._cleanup_pid_file()
        _ = self._logger.info("shutdown")
        close_logging()
