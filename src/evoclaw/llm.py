import asyncio
import importlib
import json
from collections.abc import Mapping
from typing import Protocol, cast

from evoclaw.config import Config


class _LoggerProtocol(Protocol):
    def warning(self, event: str, **kwargs: object) -> None: ...

    def error(self, event: str, **kwargs: object) -> None: ...


class _GetLoggerProtocol(Protocol):
    def __call__(self) -> _LoggerProtocol: ...


class _LogToolProtocol(Protocol):
    def __call__(
        self, *, tool_name: str, args: dict[str, object], result_summary: str
    ) -> None: ...


class _DispatchToolProtocol(Protocol):
    async def __call__(
        self, name: str, args: dict[str, object], config: Config | None = None
    ) -> str: ...


class _ToolFunctionProtocol(Protocol):
    name: str
    arguments: str


class _ToolCallProtocol(Protocol):
    id: str
    function: _ToolFunctionProtocol


class _ChatMessageProtocol(Protocol):
    content: str | None
    tool_calls: list[_ToolCallProtocol] | None


class _ChoiceProtocol(Protocol):
    message: _ChatMessageProtocol


class _ResponseProtocol(Protocol):
    choices: list[_ChoiceProtocol]


class _ChatCompletionsProtocol(Protocol):
    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> _ResponseProtocol: ...


class _ChatProtocol(Protocol):
    completions: _ChatCompletionsProtocol


class _AsyncOpenAIClientProtocol(Protocol):
    chat: _ChatProtocol


class _AsyncOpenAIFactoryProtocol(Protocol):
    def __call__(
        self, *, api_key: str, base_url: str
    ) -> _AsyncOpenAIClientProtocol: ...


class _ResponseWithHeadersProtocol(Protocol):
    headers: Mapping[str, str]


tools_module = importlib.import_module("evoclaw.tools")
TOOL_DEFINITIONS = cast(
    list[dict[str, object]], getattr(tools_module, "TOOL_DEFINITIONS")
)
dispatch_tool = cast(_DispatchToolProtocol, getattr(tools_module, "dispatch_tool"))

log_module = importlib.import_module("evoclaw.log")
get_logger = cast(_GetLoggerProtocol, getattr(log_module, "get_logger"))
log_tool = cast(_LogToolProtocol, getattr(log_module, "log_tool"))

openai = importlib.import_module("openai")
AsyncOpenAI = cast(_AsyncOpenAIFactoryProtocol, getattr(openai, "AsyncOpenAI"))
RateLimitError = cast(type[Exception], getattr(openai, "RateLimitError"))
APIStatusError = cast(type[Exception], getattr(openai, "APIStatusError"))
APIConnectionError = cast(type[Exception], getattr(openai, "APIConnectionError"))

DEATH_MARKER = "__DEATH__:balance_exhausted"


class LLMClient:
    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self.client: _AsyncOpenAIClientProtocol = AsyncOpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_api_base,
        )

    async def heartbeat_step(self, memory_content: str, system_prompt: str) -> str:
        messages: list[dict[str, object]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": memory_content},
        ]

        for _ in range(self.config.max_tool_iterations):
            try:
                response = await self.client.chat.completions.create(
                    model=self.config.llm_model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                )
            except RateLimitError as exc:
                err_str = str(exc).lower()
                if (
                    "insufficient_quota" in err_str
                    or _get_error_code(exc) == "insufficient_quota"
                ):
                    return DEATH_MARKER

                retry_after = _get_retry_after(exc)
                get_logger().warning("rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after)
                continue
            except APIStatusError as exc:
                status_code = _get_status_code(exc)
                if status_code == 402 or _get_error_code(exc) == "insufficient_quota":
                    return DEATH_MARKER
                get_logger().error(
                    "api_error", status_code=status_code, message=str(exc)
                )
                return ""
            except APIConnectionError as exc:
                get_logger().error("connection_error", error=str(exc))
                return ""

            choice = response.choices[0]
            assistant_message = choice.message

            msg_dict: dict[str, object] = {
                "role": "assistant",
                "content": assistant_message.content or "",
            }
            if assistant_message.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_message.tool_calls
                ]
            messages.append(msg_dict)

            if not assistant_message.tool_calls:
                return assistant_message.content or ""

            for tc in assistant_message.tool_calls:
                tool_name = tc.function.name
                try:
                    args = _parse_tool_args(tc.function.arguments)
                except (json.JSONDecodeError, ValueError) as exc:
                    result = f"Error: malformed tool arguments: {exc}"
                    args = {}
                else:
                    result = await dispatch_tool(tool_name, args, config=self.config)

                log_tool(
                    tool_name=tool_name,
                    args=args,
                    result_summary=result[:200] if result else "",
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )

        get_logger().warning(
            "max_iterations_exceeded", iterations=self.config.max_tool_iterations
        )
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, str) and content:
                    return content
        return ""


def _get_error_code(exc: Exception) -> str | None:
    return cast(str | None, getattr(exc, "code", None))


def _get_status_code(exc: Exception) -> int | None:
    return cast(int | None, getattr(exc, "status_code", None))


def _get_retry_after(exc: Exception, default: int = 30) -> int:
    response = cast(_ResponseWithHeadersProtocol | None, getattr(exc, "response", None))
    if response is None:
        return default

    retry_after = response.headers.get("retry-after")
    if retry_after is None:
        return default

    try:
        return int(retry_after)
    except ValueError:
        return default


def _parse_tool_args(arguments: str) -> dict[str, object]:
    parsed = cast(object, json.loads(arguments))
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must decode to an object")
    return cast(dict[str, object], parsed)
