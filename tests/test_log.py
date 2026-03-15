import io
import json
import os
import pytest
import structlog
import structlog.contextvars
from evoclaw.log import (
    setup_logging,
    log_heartbeat,
    log_death,
    log_tool,
    get_logger,
    format_god_log,
    _fmt_timestamp,
    _truncate,
    _strip_ansi,
)


def test_setup_creates_log_dir(tmp_path):
    log_dir = str(tmp_path / "logs")
    setup_logging(log_dir, generation=1)
    assert os.path.isdir(log_dir)


def test_log_heartbeat_writes_json(tmp_path):
    log_dir = str(tmp_path / "logs")
    setup_logging(log_dir, generation=1)
    log_heartbeat(beat_number=1, memory_size=1024, balance=5.0, tool_calls=3)

    log_file = tmp_path / "logs" / "god.jsonl"
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1
    data = json.loads(lines[-1])
    assert data["event"] == "heartbeat"
    assert data["memory_size"] == 1024
    assert data["balance"] == 5.0
    assert data["tool_calls"] == 3


def test_log_death_contains_reason(tmp_path):
    log_dir = str(tmp_path / "logs")
    setup_logging(log_dir, generation=1)
    log_death(reason="memory_exceeded", generation=1)

    log_file = tmp_path / "logs" / "god.jsonl"
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    data = json.loads(lines[-1])
    assert data["event"] == "death"
    assert data["reason"] == "memory_exceeded"


def test_log_tool_writes_tool_name(tmp_path):
    log_dir = str(tmp_path / "logs")
    setup_logging(log_dir, generation=1)
    log_tool(tool_name="file_read", args={"path": "/tmp/test"}, result_summary="ok")

    log_file = tmp_path / "logs" / "god.jsonl"
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    data = json.loads(lines[-1])
    assert data["tool_name"] == "file_read"


def test_json_lines_parseable(tmp_path):
    log_dir = str(tmp_path / "logs")
    setup_logging(log_dir, generation=2)
    log_heartbeat(beat_number=1, memory_size=100, balance=None, tool_calls=0)
    log_heartbeat(beat_number=2, memory_size=200, balance=4.5, tool_calls=1)

    log_file = tmp_path / "logs" / "god.jsonl"
    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        data = json.loads(line)  # must not raise
        assert "event" in data
        assert "timestamp" in data


# ---------------------------------------------------------------------------
# Helper to build JSONL log files for format_god_log tests
# ---------------------------------------------------------------------------


def _write_log(path: os.PathLike[str], entries: list[dict[str, object]]) -> str:
    """Write a list of dicts as JSONL and return the file path as str."""
    file_path = str(path)
    with open(file_path, "w", encoding="utf-8") as f:
        for entry in entries:
            _ = f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return file_path


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


def test_fmt_timestamp_extracts_time():
    assert _fmt_timestamp("2025-03-15T15:07:36.123Z") == "15:07:36"


def test_fmt_timestamp_passthrough():
    assert _fmt_timestamp("15:07:36") == "15:07:36"


def test_truncate_short_string():
    assert _truncate("hello", 120) == "hello"


def test_truncate_long_string():
    long = "a" * 200
    result = _truncate(long, 50)
    assert len(result) == 50
    assert result.endswith("…")


def test_truncate_replaces_newlines():
    assert "↵" in _truncate("line1\nline2")


def test_strip_ansi_removes_codes():
    assert _strip_ansi("\033[31mred\033[0m") == "red"


def test_strip_ansi_noop_plain():
    assert _strip_ansi("plain") == "plain"


# ---------------------------------------------------------------------------
# format_god_log — basic rendering
# ---------------------------------------------------------------------------


def test_format_god_log_empty_file(tmp_path):
    log_file = _write_log(tmp_path / "empty.jsonl", [])
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    assert buf.getvalue().strip() == "(empty log)"


def test_format_god_log_heartbeat(tmp_path):
    entries = [
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:07:36Z",
            "memory_size": 1024,
            "balance": 5.0,
            "tool_calls": 3,
        }
    ]
    log_file = _write_log(tmp_path / "hb.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "Generation 1" in out
    assert "Heartbeat #1" in out
    assert "memory=1024B" in out
    assert "balance=5.0 CNY" in out
    assert "tool_calls=3" in out


def test_format_god_log_tool_call(tmp_path):
    entries = [
        {
            "event": "tool_call",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:08:00Z",
            "tool_name": "file_read",
            "args": {"path": "/tmp/test.md"},
            "result_summary": "ok",
        }
    ]
    log_file = _write_log(tmp_path / "tc.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "file_read" in out
    assert "/tmp/test.md" in out
    assert "→ ok" in out


def test_format_god_log_death(tmp_path):
    entries = [
        {
            "event": "death",
            "generation": 3,
            "beat_number": 10,
            "timestamp": "2025-03-15T16:00:00Z",
            "reason": "memory_exceeded",
        }
    ]
    log_file = _write_log(tmp_path / "death.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "DEATH" in out
    assert "memory_exceeded" in out
    assert "Gen 3" in out


def test_format_god_log_reincarnation(tmp_path):
    entries = [
        {
            "event": "reincarnation",
            "generation": 4,
            "beat_number": 0,
            "timestamp": "2025-03-15T16:01:00Z",
        }
    ]
    log_file = _write_log(tmp_path / "reincarnation.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "REINCARNATION" in out
    assert "Gen 4" in out


def test_format_god_log_max_iter(tmp_path):
    entries = [
        {
            "event": "max_iterations_exceeded",
            "generation": 1,
            "beat_number": 5,
            "timestamp": "2025-03-15T16:02:00Z",
            "iterations": 20,
        }
    ]
    log_file = _write_log(tmp_path / "maxiter.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "Max iterations exceeded" in out
    assert "20" in out


def test_format_god_log_shutdown(tmp_path):
    entries = [
        {
            "event": "shutdown",
            "generation": 2,
            "beat_number": 0,
            "timestamp": "2025-03-15T17:00:00Z",
        }
    ]
    log_file = _write_log(tmp_path / "shutdown.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "SHUTDOWN" in out


def test_format_god_log_api_error(tmp_path):
    entries = [
        {
            "event": "api_error",
            "generation": 1,
            "beat_number": 2,
            "timestamp": "2025-03-15T15:10:00Z",
            "message": "rate limited",
            "status_code": 429,
        }
    ]
    log_file = _write_log(tmp_path / "apierr.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "API Error" in out
    assert "429" in out
    assert "rate limited" in out


# ---------------------------------------------------------------------------
# format_god_log — filtering by generation
# ---------------------------------------------------------------------------


def test_format_god_log_generation_filter(tmp_path):
    entries = [
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "memory_size": 100,
            "balance": 5.0,
            "tool_calls": 0,
        },
        {
            "event": "heartbeat",
            "generation": 2,
            "beat_number": 1,
            "timestamp": "2025-03-15T16:00:00Z",
            "memory_size": 200,
            "balance": 4.0,
            "tool_calls": 1,
        },
    ]
    log_file = _write_log(tmp_path / "filter.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, generation=2, output=buf)
    out = buf.getvalue()
    assert "Generation 2" in out
    assert "Generation 1" not in out


def test_format_god_log_generation_filter_no_match(tmp_path):
    entries = [
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "memory_size": 100,
            "balance": None,
            "tool_calls": 0,
        },
    ]
    log_file = _write_log(tmp_path / "nomatch.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, generation=99, output=buf)
    assert buf.getvalue().strip() == "(no events for generation 99)"


# ---------------------------------------------------------------------------
# format_god_log — summary footer
# ---------------------------------------------------------------------------


def test_format_god_log_summary_footer(tmp_path):
    entries = [
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "memory_size": 100,
            "balance": None,
            "tool_calls": 0,
        },
        {
            "event": "tool_call",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:01Z",
            "tool_name": "file_read",
            "args": {"path": "/x"},
            "result_summary": "ok",
        },
        {
            "event": "death",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:02Z",
            "reason": "memory_exceeded",
        },
    ]
    log_file = _write_log(tmp_path / "summary.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "Summary:" in out
    assert "3 events" in out
    assert "1 generation(s)" in out
    assert "1 death(s)" in out
    assert "1 tool call(s)" in out


# ---------------------------------------------------------------------------
# format_god_log — color vs no-color
# ---------------------------------------------------------------------------


def test_format_god_log_no_color(tmp_path):
    entries = [
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "memory_size": 100,
            "balance": None,
            "tool_calls": 0,
        },
    ]
    log_file = _write_log(tmp_path / "nc.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    assert "\033[" not in buf.getvalue()


def test_format_god_log_with_color(tmp_path):
    entries = [
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "memory_size": 100,
            "balance": None,
            "tool_calls": 0,
        },
    ]
    log_file = _write_log(tmp_path / "c.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=True, output=buf)
    assert "\033[" in buf.getvalue()


# ---------------------------------------------------------------------------
# format_god_log — invalid JSON lines
# ---------------------------------------------------------------------------


def test_format_god_log_invalid_json(tmp_path):
    file_path = tmp_path / "bad.jsonl"
    _ = file_path.write_text("not json\n", encoding="utf-8")
    buf = io.StringIO()
    format_god_log(str(file_path), color=False, output=buf)
    out = buf.getvalue()
    assert "invalid JSON" in out
    assert "(empty log)" in out


# ---------------------------------------------------------------------------
# format_god_log — unknown event type
# ---------------------------------------------------------------------------


def test_format_god_log_unknown_event(tmp_path):
    entries = [
        {
            "event": "custom_event",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "extra_data": "hello",
        }
    ]
    log_file = _write_log(tmp_path / "unknown.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "custom_event" in out


# ---------------------------------------------------------------------------
# format_god_log — generation/beat grouping headers
# ---------------------------------------------------------------------------


def test_format_god_log_groups_by_generation_and_beat(tmp_path):
    entries = [
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "memory_size": 100,
            "balance": None,
            "tool_calls": 0,
        },
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 2,
            "timestamp": "2025-03-15T15:01:00Z",
            "memory_size": 200,
            "balance": None,
            "tool_calls": 1,
        },
        {
            "event": "death",
            "generation": 1,
            "beat_number": 2,
            "timestamp": "2025-03-15T15:01:30Z",
            "reason": "memory_exceeded",
        },
        {
            "event": "reincarnation",
            "generation": 2,
            "beat_number": 0,
            "timestamp": "2025-03-15T15:02:00Z",
        },
    ]
    log_file = _write_log(tmp_path / "groups.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "Generation 1" in out
    assert "Generation 2" in out
    assert "Beat 1" in out
    assert "Beat 2" in out
    assert "Beat 0" in out


# ---------------------------------------------------------------------------
# format_god_log — tool_call arg formatting variants
# ---------------------------------------------------------------------------


def test_format_tool_call_file_edit(tmp_path):
    entries = [
        {
            "event": "tool_call",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "tool_name": "file_edit",
            "args": {"path": "/tmp/x.md", "content": "hello world"},
            "result_summary": "written",
        }
    ]
    log_file = _write_log(tmp_path / "edit.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "file_edit" in out
    assert "/tmp/x.md" in out
    assert "11 chars" in out


def test_format_tool_call_shell_execute(tmp_path):
    entries = [
        {
            "event": "tool_call",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "tool_name": "shell_execute",
            "args": {"command": "ls -la"},
            "result_summary": "file1\nfile2",
        }
    ]
    log_file = _write_log(tmp_path / "shell.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "shell_execute" in out
    assert "ls -la" in out


def test_format_tool_call_balance_check(tmp_path):
    entries = [
        {
            "event": "tool_call",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "tool_name": "balance_check",
            "args": {},
            "result_summary": "4.5 CNY",
        }
    ]
    log_file = _write_log(tmp_path / "balance.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    out = buf.getvalue()
    assert "balance_check" in out
    assert "4.5 CNY" in out


# ---------------------------------------------------------------------------
# format_god_log — balance=None renders as N/A
# ---------------------------------------------------------------------------


def test_format_heartbeat_balance_none(tmp_path):
    entries = [
        {
            "event": "heartbeat",
            "generation": 1,
            "beat_number": 1,
            "timestamp": "2025-03-15T15:00:00Z",
            "memory_size": 100,
            "balance": None,
            "tool_calls": 0,
        },
    ]
    log_file = _write_log(tmp_path / "balnone.jsonl", entries)
    buf = io.StringIO()
    format_god_log(log_file, color=False, output=buf)
    assert "balance=N/A" in buf.getvalue()
