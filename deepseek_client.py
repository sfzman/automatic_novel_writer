"""Backward-compatible DeepSeek helpers built on the generic LLM client."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from llm_client import LLMConfig, call_llm_json, call_llm_text

API_URL = "https://api.deepseek.com/chat/completions"

T = TypeVar("T")


def _config(api_key: str, model: str) -> LLMConfig:
    return LLMConfig(
        provider="deepseek",
        model=model,
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )


def call_deepseek_text(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
    retries: int,
    retry_interval: int,
    response_format: dict[str, Any] | None = None,
    extra_messages: list[dict[str, str]] | None = None,
) -> str:
    return call_llm_text(
        config=_config(api_key, model),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        retries=retries,
        retry_interval=retry_interval,
        response_format=response_format,
        extra_messages=extra_messages,
    )


def call_deepseek_json(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
    retries: int,
    retry_interval: int,
    parse_response: Callable[[str], T],
    extra_messages: list[dict[str, str]] | None = None,
) -> T:
    return call_llm_json(
        config=_config(api_key, model),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        retries=retries,
        retry_interval=retry_interval,
        parse_response=parse_response,
        extra_messages=extra_messages,
    )
