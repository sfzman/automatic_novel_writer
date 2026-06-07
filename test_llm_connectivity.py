#!/usr/bin/env python3
"""Quick connectivity test for the configured OpenAI-compatible LLM provider."""

from __future__ import annotations

import argparse
import sys

from llm_client import call_llm_text, resolve_llm_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="测试 LLM provider / base_url / model / API Key 是否可用。")
    parser.add_argument("--provider", default="volcengine", help="默认: volcengine；也支持 ark/kimi/deepseek/aliyun/bailian/qwen/custom")
    parser.add_argument("--env-file", default=".env", help="默认读取当前目录 .env")
    parser.add_argument("--base-url", default="", help="覆盖 base_url；默认从 .env 或 provider 默认值读取")
    parser.add_argument("--model", default="", help="覆盖模型；默认从 .env 或 provider 默认值读取")
    parser.add_argument("--api-key", default="", help="覆盖 API Key；默认从 .env 或环境变量读取")
    parser.add_argument("--timeout", type=int, default=30, help="请求超时时间，默认 30 秒")
    parser.add_argument("--retries", type=int, default=1, help="重试次数，默认 1")
    parser.add_argument("--max-tokens", type=int, default=128, help="最大输出 token，推理模型需要给 reasoning 留空间，默认 128")
    parser.add_argument("--dry-run", action="store_true", help="只打印解析出的配置，不发起请求")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = resolve_llm_config(
            provider=args.provider,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            env_file=args.env_file,
        )
        print(f"provider: {config.provider}")
        print(f"model: {config.model}")
        print(f"api_url: {config.api_url}")
        print(f"api_key: {'已读取' if config.api_key else '未读取'}")
        if args.dry_run:
            return 0

        content = call_llm_text(
            config=config,
            system_prompt="You are a connectivity probe. Keep reasoning minimal and reply with exactly: pong",
            user_prompt="Connectivity test. Reply with exactly one word: pong",
            max_tokens=args.max_tokens,
            temperature=0,
            timeout=args.timeout,
            retries=args.retries,
            retry_interval=2,
        )
        print(f"response: {content}")
        print("OK: LLM 接口连通，鉴权和模型调用成功。")
        return 0
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
