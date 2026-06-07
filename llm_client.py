"""OpenAI-compatible chat completions client with a declarative provider registry."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable, TypeVar
from urllib import error, request

from novel_utils import DEFAULT_API_KEY, DeepSeekAPIError

T = TypeVar("T")

CHAT_COMPLETIONS_PATH = "/chat/completions"
SHARED_ENV_PREFIXES = ("LLM",)


@dataclass(frozen=True)
class ProviderSpec:
    """Connection defaults for one OpenAI-compatible provider."""

    name: str
    base_url: str
    default_model: str = ""
    aliases: tuple[str, ...] = ()
    env_prefixes: tuple[str, ...] = ()
    supports_json_response_format: bool = True
    extra_api_key_envs: tuple[str, ...] = ()
    extra_base_url_envs: tuple[str, ...] = ()
    extra_model_envs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.env_prefixes:
            object.__setattr__(self, "env_prefixes", (self.name.upper(),))

    def env_names(self, field_name: str) -> tuple[str, ...]:
        suffixes = {
            "api_key": "API_KEY",
            "base_url": "BASE_URL",
            "model": "MODEL",
        }
        extras = {
            "api_key": self.extra_api_key_envs,
            "base_url": self.extra_base_url_envs,
            "model": self.extra_model_envs,
        }
        suffix = suffixes[field_name]
        names = [f"{prefix}_{suffix}" for prefix in self.env_prefixes]
        names.extend(extras[field_name])
        names.extend(f"{prefix}_{suffix}" for prefix in SHARED_ENV_PREFIXES)
        return tuple(dict.fromkeys(names))


# Add a new OpenAI-compatible provider here. The rest of the code path is shared.
PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        name="deepseek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
        supports_json_response_format=True,
    ),
    "volcengine": ProviderSpec(
        name="volcengine",
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
        default_model="kimi2.6",
        aliases=("ark", "volcano", "volc", "kimi", "kimi-volcengine"),
        env_prefixes=("VOLCENGINE", "ARK", "KIMI"),
        supports_json_response_format=False,
    ),
    "aliyun": ProviderSpec(
        name="aliyun",
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        aliases=("bailian", "aliyun-bailian", "dashscope", "qwen"),
        env_prefixes=("ALIYUN", "ALIYUN_BAILIAN", "BAILIAN", "DASHSCOPE"),
        supports_json_response_format=False,
    ),
    "custom": ProviderSpec(
        name="custom",
        base_url="",
        default_model="",
        aliases=("openai-compatible",),
        env_prefixes=("CUSTOM", "OPENAI"),
        supports_json_response_format=False,
    ),
}

PROVIDER_ALIASES = {
    alias: name
    for name, spec in PROVIDER_SPECS.items()
    for alias in (name, *spec.aliases)
}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: str
    supports_json_response_format: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return build_chat_completions_url(self.base_url)


def normalize_provider(provider: str | None) -> str:
    normalized = (provider or "deepseek").strip().lower()
    provider_name = PROVIDER_ALIASES.get(normalized, normalized)
    if provider_name not in PROVIDER_SPECS:
        supported = ", ".join(sorted(PROVIDER_SPECS))
        aliases = ", ".join(sorted(alias for alias in PROVIDER_ALIASES if alias not in PROVIDER_SPECS))
        raise ValueError(
            f"不支持的 LLM provider: {provider!r}; 当前支持: {supported}; aliases: {aliases}"
        )
    return provider_name


def parse_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed = value.strip()
        if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {"'", '"'}:
            parsed = parsed[1:-1]
        values[key.strip()] = parsed.strip()
    return values


def _first_env_value(names: tuple[str, ...], env_values: dict[str, str]) -> str | None:
    import os

    for name in names:
        value = env_values.get(name) or os.environ.get(name)
        if value:
            return value
    return None


def _resolve_required_value(
    *,
    explicit_value: str | None,
    env_names: tuple[str, ...],
    env_values: dict[str, str],
    default_value: str,
    provider_name: str,
    label: str,
    cli_hint: str,
    ignore_placeholder: bool = False,
) -> str:
    explicit = (explicit_value or "").strip()
    if ignore_placeholder and explicit == DEFAULT_API_KEY:
        explicit = ""
    resolved = explicit or _first_env_value(env_names, env_values) or default_value
    if resolved:
        return resolved

    env_hint = " / ".join(env_names)
    raise ValueError(
        f"请为 {provider_name} 配置{label}: 可通过 {cli_hint}, "
        f"或在 .env/环境变量中设置 {env_hint}。"
    )


def resolve_llm_config(
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    env_file: str | Path = ".env",
) -> LLMConfig:
    provider_name = normalize_provider(provider)
    spec = PROVIDER_SPECS[provider_name]
    env_values = parse_env_file(Path(env_file).expanduser())

    resolved_key = _resolve_required_value(
        explicit_value=api_key,
        env_names=spec.env_names("api_key"),
        env_values=env_values,
        default_value="",
        provider_name=provider_name,
        label=" API Key",
        cli_hint="--api-key/阶段专用 --*-api-key",
        ignore_placeholder=True,
    )
    resolved_model = _resolve_required_value(
        explicit_value=model,
        env_names=spec.env_names("model"),
        env_values=env_values,
        default_value=spec.default_model,
        provider_name=provider_name,
        label="模型名",
        cli_hint="--model/阶段专用 --*-model",
    )
    resolved_base_url = _resolve_required_value(
        explicit_value=base_url,
        env_names=spec.env_names("base_url"),
        env_values=env_values,
        default_value=spec.base_url,
        provider_name=provider_name,
        label=" base_url",
        cli_hint="--base-url/阶段专用 --*-base-url",
    )

    return LLMConfig(
        provider=provider_name,
        model=resolved_model,
        api_key=resolved_key,
        base_url=resolved_base_url,
        supports_json_response_format=spec.supports_json_response_format,
    )


def build_chat_completions_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith(CHAT_COMPLETIONS_PATH):
        return normalized
    return normalized + CHAT_COMPLETIONS_PATH


def call_llm_text(
    *,
    config: LLMConfig,
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
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        **config.extra_headers,
    }

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = request.Request(config.api_url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                raw_text = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            last_error = DeepSeekAPIError(
                f"{config.provider} API HTTP {exc.code}: {response_text}"
            )
        except error.URLError as exc:
            last_error = DeepSeekAPIError(f"请求 {config.provider} API 失败: {exc}")
        except TimeoutError as exc:
            last_error = DeepSeekAPIError(f"请求 {config.provider} API 超时: {exc}")
        else:
            try:
                response_data = json.loads(raw_text)
            except json.JSONDecodeError:
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

    raise DeepSeekAPIError(f"调用 {config.provider} API 失败: {last_error}")


def call_llm_json(
    *,
    config: LLMConfig,
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
            content = call_llm_text(
                config=config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                retries=1,
                retry_interval=retry_interval,
                response_format={"type": "json_object"}
                if config.supports_json_response_format
                else None,
                extra_messages=extra_messages,
            )
            return parse_response(content)
        except DeepSeekAPIError as exc:
            if attempt >= retries:
                raise DeepSeekAPIError(f"调用 {config.provider} API 失败: {exc}") from exc
            print(
                f"第 {attempt} 次调用失败, {retry_interval} 秒后重试...\n原因: {exc}",
                file=sys.stderr,
            )
            time.sleep(retry_interval)

    raise DeepSeekAPIError(f"调用 {config.provider} API 失败: 未知错误")
