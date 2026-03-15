# pyright: reportMissingImports=false, reportMissingTypeStubs=false

import json
from dataclasses import dataclass
from typing import cast
from unittest.mock import patch

import httpx
import openai
import pytest

from evoclaw.config import Config
from evoclaw.llm import (
    DEATH_MARKER,
    LLMClient,
    _BASE_MESSAGE_COUNT,
    _estimate_perception_bytes,
    _trim_perception,
)


def make_config(**overrides: object) -> Config:
    cfg = Config.__new__(Config)
    Config.__init__(
        cfg,
        heartbeat_interval=60,
        memory_max_bytes=307200,
        shell_timeout=300,
        max_tool_iterations=5,
        perception_max_bytes=51200,
        llm_api_base="https://api.deepseek.com",
        llm_api_key="test-key",
        llm_model="deepseek-chat",
        angel_api_key="angel-key",
        angel_model="deepseek-chat",
        world_dir="./world",
        log_dir="./logs",
        telegram_bot_token="",
        telegram_chat_id="",
    )
    for key, value in overrides.items():
        object.__setattr__(cfg, key, value)
    return cfg


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction


@dataclass
class FakeMessage:
    content: str | None
    tool_calls: list[FakeToolCall] | None


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeResponse:
    choices: list[FakeChoice]


class FakeCompletions:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self._responses: list[FakeResponse | Exception] = list(responses)

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> FakeResponse:
        _ = model, messages, tools
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeChat:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.completions: FakeCompletions = FakeCompletions(responses)


class FakeOpenAIClient:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.chat: FakeChat = FakeChat(responses)


class DispatchRecorder:
    def __init__(self, results: str | list[str]) -> None:
        self._results: list[str] = (
            [results] if isinstance(results, str) else list(results)
        )
        self.calls: list[tuple[str, dict[str, object], Config | None]] = []

    async def __call__(
        self, name: str, args: dict[str, object], config: Config | None = None
    ) -> str:
        self.calls.append((name, args, config))
        if len(self._results) == 1:
            return self._results[0]
        return self._results.pop(0)


def make_text_response(content: str) -> FakeResponse:
    return FakeResponse([FakeChoice(FakeMessage(content=content, tool_calls=None))])


def make_tool_call_response(
    tool_name: str, args: dict[str, object], call_id: str = "call_123"
) -> FakeResponse:
    return FakeResponse(
        [
            FakeChoice(
                FakeMessage(
                    content=None,
                    tool_calls=[
                        FakeToolCall(
                            id=call_id,
                            function=FakeFunction(
                                name=tool_name,
                                arguments=json.dumps(args),
                            ),
                        )
                    ],
                )
            )
        ]
    )


@pytest.fixture
def cfg() -> Config:
    return make_config()


async def test_simple_text_response(cfg: Config) -> None:
    fake_client = FakeOpenAIClient([make_text_response("Hello from LLM!")])

    with patch("evoclaw.llm.AsyncOpenAI", return_value=fake_client):
        client = LLMClient(cfg)
        result = await client.heartbeat_step("my memory", "system prompt")

    assert result == "Hello from LLM!"


async def test_tool_call_then_text(cfg: Config) -> None:
    fake_client = FakeOpenAIClient(
        [
            make_tool_call_response("file_read", {"path": "/tmp/test.txt"}),
            make_text_response("I read the file successfully"),
        ]
    )
    recorder = DispatchRecorder("file contents here")

    with (
        patch("evoclaw.llm.AsyncOpenAI", return_value=fake_client),
        patch("evoclaw.llm.dispatch_tool", new=recorder),
    ):
        client = LLMClient(cfg)
        result = await client.heartbeat_step("memory", "prompt")

    assert result == "I read the file successfully"
    assert recorder.calls == [("file_read", {"path": "/tmp/test.txt"}, cfg)]


async def test_multiple_tool_calls(cfg: Config) -> None:
    fake_client = FakeOpenAIClient(
        [
            make_tool_call_response("file_read", {"path": "/a"}, "call_1"),
            make_tool_call_response(
                "file_edit", {"path": "/b", "content": "x"}, "call_2"
            ),
            make_text_response("done"),
        ]
    )
    recorder = DispatchRecorder("result")

    with (
        patch("evoclaw.llm.AsyncOpenAI", return_value=fake_client),
        patch("evoclaw.llm.dispatch_tool", new=recorder),
    ):
        client = LLMClient(cfg)
        result = await client.heartbeat_step("memory", "prompt")

    assert result == "done"
    assert recorder.calls == [
        ("file_read", {"path": "/a"}, cfg),
        ("file_edit", {"path": "/b", "content": "x"}, cfg),
    ]


async def test_max_iterations_exceeded() -> None:
    cfg_limited = make_config(max_tool_iterations=2)
    fake_client = FakeOpenAIClient(
        [
            make_tool_call_response("file_read", {"path": "/x"}, f"call_{i}")
            for i in range(10)
        ]
    )
    recorder = DispatchRecorder("result")

    with (
        patch("evoclaw.llm.AsyncOpenAI", return_value=fake_client),
        patch("evoclaw.llm.dispatch_tool", new=recorder),
    ):
        client = LLMClient(cfg_limited)
        result = await client.heartbeat_step("memory", "prompt")

    assert isinstance(result, str)


async def test_malformed_tool_args(cfg: Config) -> None:
    bad_response = FakeResponse(
        [
            FakeChoice(
                FakeMessage(
                    content=None,
                    tool_calls=[
                        FakeToolCall(
                            id="call_bad",
                            function=FakeFunction(
                                name="file_read", arguments="NOT VALID JSON {"
                            ),
                        )
                    ],
                )
            )
        ]
    )
    fake_client = FakeOpenAIClient([bad_response, make_text_response("self-corrected")])
    recorder = DispatchRecorder("recovered")

    with (
        patch("evoclaw.llm.AsyncOpenAI", return_value=fake_client),
        patch("evoclaw.llm.dispatch_tool", new=recorder),
    ):
        client = LLMClient(cfg)
        result = await client.heartbeat_step("memory", "prompt")

    assert result == "self-corrected"
    assert recorder.calls == []


async def test_insufficient_quota_returns_death_marker(cfg: Config) -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(status_code=429, headers={}, request=request)
    error = openai.RateLimitError(
        message="insufficient_quota",
        response=response,
        body={"error": {"code": "insufficient_quota"}},
    )
    fake_client = FakeOpenAIClient([cast(Exception, error)])

    with patch("evoclaw.llm.AsyncOpenAI", return_value=fake_client):
        client = LLMClient(cfg)
        result = await client.heartbeat_step("memory", "prompt")

    assert result == DEATH_MARKER


async def test_network_error_returns_empty(cfg: Config) -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    error = openai.APIConnectionError(request=request)
    fake_client = FakeOpenAIClient([cast(Exception, error)])

    with patch("evoclaw.llm.AsyncOpenAI", return_value=fake_client):
        client = LLMClient(cfg)
        result = await client.heartbeat_step("memory", "prompt")

    assert result == ""


def test_estimate_perception_bytes_empty() -> None:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "mem"},
    ]
    assert _estimate_perception_bytes(messages) == 0


def test_estimate_perception_bytes_with_tool_interactions() -> None:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "mem"},
        {"role": "assistant", "content": "thinking"},
        {"role": "tool", "tool_call_id": "c1", "content": "x" * 100},
    ]
    expected = len("thinking".encode("utf-8")) + 100
    assert _estimate_perception_bytes(messages) == expected


def test_trim_perception_removes_oldest_first() -> None:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "mem"},
        {"role": "assistant", "content": "a" * 500},
        {"role": "tool", "tool_call_id": "c1", "content": "b" * 500},
        {"role": "assistant", "content": "c" * 50},
        {"role": "tool", "tool_call_id": "c2", "content": "d" * 50},
    ]
    _trim_perception(messages, max_bytes=200)
    assert len(messages) > _BASE_MESSAGE_COUNT
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert _estimate_perception_bytes(messages) <= 200


def test_trim_perception_noop_when_under_limit() -> None:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "mem"},
        {"role": "assistant", "content": "ok"},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
    ]
    original_len = len(messages)
    _trim_perception(messages, max_bytes=51200)
    assert len(messages) == original_len


async def test_perception_trimming_during_tool_loop() -> None:
    cfg_tiny = make_config(perception_max_bytes=100)
    fake_client = FakeOpenAIClient(
        [
            make_tool_call_response("file_read", {"path": "/a"}, "call_1"),
            make_tool_call_response("file_read", {"path": "/b"}, "call_2"),
            make_text_response("done"),
        ]
    )
    recorder = DispatchRecorder("x" * 80)

    with (
        patch("evoclaw.llm.AsyncOpenAI", return_value=fake_client),
        patch("evoclaw.llm.dispatch_tool", new=recorder),
    ):
        client = LLMClient(cfg_tiny)
        result = await client.heartbeat_step("memory", "prompt")

    assert result == "done"
    assert len(recorder.calls) == 2
