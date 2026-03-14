import json
import os
import pytest
import structlog
import structlog.contextvars
from evoclaw.log import setup_logging, log_heartbeat, log_death, log_tool, get_logger


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
