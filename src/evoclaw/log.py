import json
import os
import sys
from collections.abc import MutableMapping
from typing import TextIO, cast

import structlog
from structlog.types import FilteringBoundLogger

_logger: FilteringBoundLogger | None = None
_log_file: TextIO | None = None


def setup_logging(log_dir: str, generation: int) -> None:
    """Configure structlog for JSON output to stdout and file."""
    global _logger, _log_file
    close_logging()
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(os.path.join(log_dir, "god.jsonl"), "a", buffering=1)
    _log_file = log_file

    def dual_output(
        logger: object, method: str, event_dict: MutableMapping[str, object]
    ) -> MutableMapping[str, object]:
        _ = logger, method
        line = json.dumps(event_dict, ensure_ascii=False) + "\n"
        _ = sys.stdout.write(line)
        _ = sys.stdout.flush()
        _ = log_file.write(line)
        _ = log_file.flush()
        raise structlog.DropEvent()

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.contextvars.merge_contextvars,
            dual_output,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    structlog.contextvars.clear_contextvars()
    _ = structlog.contextvars.bind_contextvars(generation=generation, beat_number=0)
    _logger = cast(FilteringBoundLogger, structlog.get_logger())


def get_logger() -> FilteringBoundLogger:
    """Return the configured logger (call setup_logging first)."""
    if _logger is None:
        # Fallback: unconfigured logger that prints to stdout
        return cast(FilteringBoundLogger, structlog.get_logger())
    return _logger


def log_heartbeat(
    beat_number: int, memory_size: int, balance: float | None, tool_calls: int
) -> None:
    _ = structlog.contextvars.bind_contextvars(beat_number=beat_number)
    get_logger().info(
        "heartbeat",
        memory_size=memory_size,
        balance=balance,
        tool_calls=tool_calls,
    )


def log_death(reason: str, generation: int) -> None:
    get_logger().critical(
        "death",
        reason=reason,
        generation=generation,
    )


def log_tool(tool_name: str, args: dict[str, object], result_summary: str) -> None:
    get_logger().info(
        "tool_call",
        tool_name=tool_name,
        args=args,
        result_summary=result_summary,
    )


def close_logging() -> None:
    """Flush and close the God's Log file handle."""
    global _log_file
    if _log_file is not None:
        try:
            _log_file.flush()
            _log_file.close()
        except Exception:
            pass
        _log_file = None
