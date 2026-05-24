"""Minimal DeepSeek chat completions client helpers."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable, TypeVar
from urllib import error, request

from novel_utils import DeepSeekAPIError

API_URL = "https://api.deepseek.com/chat/completions"

T = TypeVar("T")


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
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if extra_messages:
        messages.extend(extra_messages)
    messages.append({"role": "user", "content": user_prompt})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = request.Request(API_URL, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                raw_text = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            last_error = DeepSeekAPIError(
                f"DeepSeek API HTTP {exc.code}: {response_text}"
            )
        except error.URLError as exc:
            last_error = DeepSeekAPIError(f"请求 DeepSeek API 失败: {exc}")
        except TimeoutError as exc:
            last_error = DeepSeekAPIError(f"请求 DeepSeek API 超时: {exc}")
        else:
            try:
                response_data = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                last_error = DeepSeekAPIError(f"API 响应不是合法 JSON: {raw_text}")
            else:
                choices = response_data.get("choices") or []
                if not choices:
                    last_error = DeepSeekAPIError(f"API 响应缺少 choices: {raw_text}")
                else:
                    message = choices[0].get("message") or {}
                    content = (message.get("content") or "").strip()
                    if content:
                        return content
                    last_error = DeepSeekAPIError(
                        f"API 返回空 content, 完整响应: {raw_text}"
                    )

        if attempt < retries:
            print(
                f"第 {attempt} 次调用失败, {retry_interval} 秒后重试...\n原因: {last_error}",
                file=sys.stderr,
            )
            time.sleep(retry_interval)

    raise DeepSeekAPIError(f"调用 DeepSeek API 失败: {last_error}")


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
    for attempt in range(1, retries + 1):
        try:
            content = call_deepseek_text(
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                retries=1,
                retry_interval=retry_interval,
                response_format={"type": "json_object"},
                extra_messages=extra_messages,
            )
            return parse_response(content)
        except DeepSeekAPIError as exc:
            if attempt >= retries:
                raise DeepSeekAPIError(f"调用 DeepSeek API 失败: {exc}") from exc
            print(
                f"第 {attempt} 次调用失败, {retry_interval} 秒后重试...\n原因: {exc}",
                file=sys.stderr,
            )
            time.sleep(retry_interval)

    raise DeepSeekAPIError("调用 DeepSeek API 失败: 未知错误")
