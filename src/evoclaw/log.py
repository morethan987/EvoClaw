import json
import os
import re
import sys
from collections.abc import Callable, MutableMapping
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


_COLORS: dict[str, str] = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "bright_red": "\033[91m",
    "bright_green": "\033[92m",
}

_NO_COLORS: dict[str, str] = {k: "" for k in _COLORS}

_TOOL_ICONS: dict[str, str] = {
    "file_read": "📖",
    "file_edit": "✏️",
    "shell_execute": "🐚",
    "balance_check": "💰",
}

type _EntryFormatter = Callable[[dict[str, object], bool], str]


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _fmt_timestamp(ts: str) -> str:
    if "T" in ts:
        return ts.split("T")[1][:8]
    return ts


def _truncate(text: str, max_len: int = 120) -> str:
    text = text.replace("\n", "↵ ")
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def _pick_colors(color: bool) -> dict[str, str]:
    return _COLORS if color else _NO_COLORS


def _format_tool_call(entry: dict[str, object], color: bool) -> str:
    cl = _pick_colors(color)
    tool_name = str(entry.get("tool_name", "?"))
    args = entry.get("args", {})
    result = str(entry.get("result_summary", ""))
    icon = _TOOL_ICONS.get(tool_name, "🔧")

    if isinstance(args, dict):
        if tool_name == "file_read":
            args_str = str(args.get("path", ""))
        elif tool_name == "file_edit":
            path = str(args.get("path", ""))
            content = str(args.get("content", ""))
            args_str = f"{path} ({len(content)} chars)"
        elif tool_name == "shell_execute":
            args_str = _truncate(str(args.get("command", "")), 80)
        elif tool_name == "balance_check":
            args_str = ""
        else:
            args_str = json.dumps(args, ensure_ascii=False)
    else:
        args_str = str(args)

    result_short = _truncate(result, 100)

    if args_str:
        line = f"  {icon} {cl['cyan']}{tool_name}{cl['reset']} {cl['dim']}{args_str}{cl['reset']}"
    else:
        line = f"  {icon} {cl['cyan']}{tool_name}{cl['reset']}"

    if result_short:
        line += f"\n     {cl['dim']}→ {result_short}{cl['reset']}"

    return line


def _format_heartbeat(entry: dict[str, object], color: bool) -> str:
    cl = _pick_colors(color)
    mem = entry.get("memory_size", "?")
    bal = entry.get("balance")
    calls = entry.get("tool_calls", 0)
    beat = entry.get("beat_number", "?")
    bal_str = f"{bal} CNY" if bal is not None else "N/A"
    return (
        f"  💓 {cl['green']}Heartbeat #{beat}{cl['reset']} "
        f"— memory={mem}B, balance={bal_str}, tool_calls={calls}"
    )


def _format_death(entry: dict[str, object], color: bool) -> str:
    cl = _pick_colors(color)
    reason = entry.get("reason", "?")
    gen = entry.get("generation", "?")
    return f"  💀 {cl['bright_red']}{cl['bold']}DEATH{cl['reset']} — Gen {gen}, reason: {reason}"


def _format_reincarnation(entry: dict[str, object], color: bool) -> str:
    cl = _pick_colors(color)
    gen = entry.get("generation", "?")
    return (
        f"  🔄 {cl['magenta']}{cl['bold']}REINCARNATION{cl['reset']} — Gen {gen} begins"
    )


def _format_max_iter(entry: dict[str, object], color: bool) -> str:
    cl = _pick_colors(color)
    iters = entry.get("iterations", "?")
    return f"  ⚠️  {cl['yellow']}Max iterations exceeded ({iters}){cl['reset']}"


def _format_shutdown(entry: dict[str, object], color: bool) -> str:
    cl = _pick_colors(color)
    return f"  🛑 {cl['bold']}SHUTDOWN{cl['reset']}"


def _format_api_error(entry: dict[str, object], color: bool) -> str:
    cl = _pick_colors(color)
    msg = entry.get("message", "")
    code = entry.get("status_code", "")
    return f"  ❌ {cl['red']}API Error{cl['reset']}: {code} — {msg}"


_EVENT_FORMATTERS: dict[str, _EntryFormatter] = {
    "tool_call": _format_tool_call,
    "heartbeat": _format_heartbeat,
    "death": _format_death,
    "reincarnation": _format_reincarnation,
    "max_iterations_exceeded": _format_max_iter,
    "shutdown": _format_shutdown,
    "api_error": _format_api_error,
}


def format_god_log(
    log_path: str,
    *,
    color: bool = True,
    generation: int | None = None,
    output: TextIO | None = None,
) -> None:
    """Read god.jsonl and write a human-readable, colorized timeline to output."""
    out: TextIO = output if output is not None else sys.stdout
    cl = _pick_colors(color)

    entries: list[dict[str, object]] = []
    with open(log_path, encoding="utf-8") as f:
        for line_num, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                _ = out.write(f"  [line {line_num}: invalid JSON]\n")

    if not entries:
        _ = out.write("(empty log)\n")
        return

    if generation is not None:
        entries = [e for e in entries if e.get("generation") == generation]
        if not entries:
            _ = out.write(f"(no events for generation {generation})\n")
            return

    current_gen: int | None = None
    current_beat: int | None = None
    first_ts: str | None = None
    last_ts: str | None = None

    for entry in entries:
        gen = entry.get("generation")
        beat = entry.get("beat_number")
        ts = str(entry.get("timestamp", ""))
        event = str(entry.get("event", "unknown"))
        time_str = _fmt_timestamp(ts)

        if first_ts is None:
            first_ts = ts
        last_ts = ts

        if gen is not None and gen != current_gen:
            current_gen = int(str(gen))
            current_beat = None
            _ = out.write(f"\n{cl['bold']}{cl['blue']}{'═' * 60}{cl['reset']}\n")
            _ = out.write(
                f"{cl['bold']}{cl['blue']}  Generation {current_gen}{cl['reset']}\n"
            )
            _ = out.write(f"{cl['bold']}{cl['blue']}{'═' * 60}{cl['reset']}\n")

        if beat is not None and beat != current_beat:
            current_beat = int(str(beat))
            _ = out.write(
                f"\n{cl['dim']}── Beat {current_beat} ─── {time_str} "
                f"──────────────────────────{cl['reset']}\n"
            )

        formatter = _EVENT_FORMATTERS.get(event)
        if formatter is not None:
            formatted = formatter(entry, color)
        else:
            formatted = f"  {event}: {json.dumps(entry, ensure_ascii=False)}"

        _ = out.write(f"{cl['dim']}{time_str}{cl['reset']} {formatted}\n")

    _ = out.write(f"\n{cl['bold']}{'─' * 60}{cl['reset']}\n")
    total = len(entries)
    gens = {e.get("generation") for e in entries if e.get("generation") is not None}
    deaths = sum(1 for e in entries if e.get("event") == "death")
    tool_calls = sum(1 for e in entries if e.get("event") == "tool_call")
    ts_range = ""
    if first_ts and last_ts:
        ts_range = f" ({_fmt_timestamp(first_ts)} → {_fmt_timestamp(last_ts)})"
    _ = out.write(
        f"{cl['bold']}Summary:{cl['reset']} {total} events, "
        f"{len(gens)} generation(s), {deaths} death(s), "
        f"{tool_calls} tool call(s){ts_range}\n"
    )
