"""Anthropic tool-use wrapper.

The SDK in use (0.52) has no strict-tool flag, so a call is strict in practice:
tool_choice forces the tool, and the tool input is validated against a Pydantic
model before it is trusted. One retry on a schema miss. Demo mode never reaches
this module's network call.
"""

from __future__ import annotations

from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from .config import Settings
from .models import Usage


class ModelRejected(RuntimeError):
    pass


def call_tool(
    settings: Settings,
    model: str,
    system: str,
    content: str | list[dict[str, Any]],
    tool_name: str,
    tool_description: str,
    schema: dict[str, Any],
    result_model: type[BaseModel],
    usage: Usage,
    max_tokens: int = 4096,
) -> BaseModel:
    if settings.use_demo:
        raise RuntimeError("call_tool was reached in demo mode; the caller must use rules instead.")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
    last_error = "no response"
    for _attempt in range(2):
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=[{"name": tool_name, "description": tool_description, "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name},
            messages=messages,
        )
        spent = response.usage
        usage.add(
            model,
            input_tokens=spent.input_tokens or 0,
            output_tokens=spent.output_tokens or 0,
            cache_read_tokens=getattr(spent, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(spent, "cache_creation_input_tokens", 0) or 0,
        )
        payload = _tool_input(response, tool_name)
        try:
            return result_model.model_validate(payload)
        except ValidationError as exc:
            last_error = str(exc)
            messages = [
                {"role": "user", "content": content},
                {"role": "assistant", "content": response.content},
                {
                    "role": "user",
                    "content": f"That tool input failed schema validation: {last_error}. Call the tool again with valid input.",
                },
            ]
    raise ModelRejected(f"{model} did not return a valid {tool_name} payload: {last_error}")


def _tool_input(response: Any, tool_name: str) -> dict[str, Any]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return dict(block.input)
    raise ModelRejected(f"{tool_name} was not called.")
