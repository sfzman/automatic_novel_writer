"""DeepSeek-powered outline agent for interactive novel planning."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from deepseek_client import call_deepseek_json
from novel_utils import (
    DEFAULT_API_KEY,
    DeepSeekAPIError,
    ensure_api_key,
    load_api_key_from_env_file,
    load_json_with_repair,
    strip_code_fences,
)
from outline_prompts import (
    CHAPTER_OUTLINE_SYSTEM_PROMPT,
    GLOBAL_OUTLINE_SYSTEM_PROMPT,
    build_chapter_outline_user_prompt,
    build_global_outline_user_prompt,
)
from outline_workspace import (
    build_abstract,
    init_from_source,
    next_chapter_index,
    read_all_chapter_outlines,
    read_global_outline,
    read_module9,
    read_module10,
    read_source_novel,
    read_state,
    save_source_novel,
    state_summary,
    update_generated_chapter,
    write_chapter_outline,
    write_global_outline,
    write_module9,
    write_module10,
    write_state,
)

DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_ENV_FILE = ".env"
DEFAULT_MAX_TOKENS = 24000
DEFAULT_TEMPERATURE = 0.9


def resolve_api_key(api_key: str, env_file: str) -> str:
    env_path = Path(env_file).expanduser()
    resolved = api_key
    if resolved == DEFAULT_API_KEY:
        resolved = load_api_key_from_env_file(env_path) or os.environ.get(
            "DEEPSEEK_API_KEY", DEFAULT_API_KEY
        )
    ensure_api_key(resolved)
    return resolved


def parse_global_outline_json(content: str) -> dict[str, Any]:
    data, normalized_json = load_json_with_repair(strip_code_fences(content))
    global_outline = str(data.get("global_outline", "")).strip()
    module9 = str(data.get("module9", "")).strip()
    module10 = str(data.get("module10", "")).strip()
    if not global_outline:
        raise DeepSeekAPIError("模型输出缺少 global_outline。")
    if not module9:
        raise DeepSeekAPIError("模型输出缺少 module9。")
    if not module10:
        raise DeepSeekAPIError("模型输出缺少 module10。")
    total_chapters = int(data.get("total_chapters") or 0)
    target_total_chars = int(data.get("target_total_chars") or 0)
    if total_chapters <= 0:
        raise DeepSeekAPIError("模型输出的 total_chapters 无效。")
    return {
        "global_outline": global_outline,
        "module9": module9,
        "module10": module10,
        "total_chapters": total_chapters,
        "target_total_chars": target_total_chars,
        "summary": str(data.get("summary", "")).strip(),
        "raw_json": normalized_json,
    }


def parse_chapter_outline_json(content: str) -> dict[str, Any]:
    data, normalized_json = load_json_with_repair(strip_code_fences(content))
    chapter_index = int(data.get("chapter_index") or 0)
    chapter_outline = str(data.get("chapter_outline", "")).strip()
    module9_updated = str(data.get("module9_updated", "")).strip()
    module10_updated = str(data.get("module10_updated", "")).strip()
    if chapter_index <= 0:
        raise DeepSeekAPIError("模型输出的 chapter_index 无效。")
    if not chapter_outline:
        raise DeepSeekAPIError("模型输出缺少 chapter_outline。")
    if not module9_updated:
        raise DeepSeekAPIError("模型输出缺少 module9_updated。")
    if not module10_updated:
        raise DeepSeekAPIError("模型输出缺少 module10_updated。")
    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    return {
        "chapter_index": chapter_index,
        "chapter_outline": chapter_outline,
        "module9_updated": module9_updated,
        "module10_updated": module10_updated,
        "progress_summary": str(data.get("progress_summary", "")).strip(),
        "is_final_chapter": bool(data.get("is_final_chapter")),
        "warnings": [str(item).strip() for item in warnings if str(item).strip()],
        "raw_json": normalized_json,
    }


def generate_global_outline(
    *,
    workspace: Path,
    source_text: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: int = 300,
    retries: int = 3,
    retry_interval: int = 5,
) -> dict[str, Any]:
    state = init_from_source(workspace, source_text)
    user_prompt = build_global_outline_user_prompt(
        source_text=source_text,
        meaningful_chars=state.source_meaningful_chars,
        detected_chapters=state.detected_source_chapters,
        suggested_total_chapters=state.total_chapters,
        target_total_chars=state.target_total_chars,
    )
    result = call_deepseek_json(
        api_key=api_key,
        model=model,
        system_prompt=GLOBAL_OUTLINE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        retries=retries,
        retry_interval=retry_interval,
        parse_response=parse_global_outline_json,
    )

    write_global_outline(workspace, result["global_outline"])
    write_module9(workspace, result["module9"])
    write_module10(workspace, result["module10"])
    state.total_chapters = int(result["total_chapters"])
    state.target_total_chars = int(result["target_total_chars"] or state.target_total_chars)
    write_state(workspace, state)
    return result


def generate_next_chapter_outline(
    *,
    workspace: Path,
    api_key: str,
    chapter_index: int | None = None,
    overwrite: bool = False,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: int = 300,
    retries: int = 3,
    retry_interval: int = 5,
) -> dict[str, Any]:
    state = read_state(workspace)
    if state.total_chapters <= 0:
        raise ValueError("请先生成全局大纲，或在 outline_state.json 中设置 total_chapters。")

    target_chapter = chapter_index or next_chapter_index(workspace)
    if target_chapter > state.total_chapters:
        raise ValueError(f"已达到目标终章: {state.total_chapters}")
    if target_chapter in (state.generated_chapters or []) and not overwrite:
        raise ValueError(f"第 {target_chapter} 章大纲已存在；如需重写请启用 overwrite。")

    global_outline = read_global_outline(workspace)
    if not global_outline:
        raise ValueError("缺少 Abstract_global.txt，请先生成或保存全局大纲。")

    user_prompt = build_chapter_outline_user_prompt(
        chapter_index=target_chapter,
        total_chapters=state.total_chapters,
        global_outline=global_outline,
        all_chapter_outlines=read_all_chapter_outlines(workspace),
        module9_current=read_module9(workspace),
        module10_current=read_module10(workspace),
    )
    result = call_deepseek_json(
        api_key=api_key,
        model=model,
        system_prompt=CHAPTER_OUTLINE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        retries=retries,
        retry_interval=retry_interval,
        parse_response=parse_chapter_outline_json,
    )

    if result["chapter_index"] != target_chapter:
        raise DeepSeekAPIError(
            f"模型返回章号 {result['chapter_index']}，但当前任务是第 {target_chapter} 章。"
        )

    write_chapter_outline(workspace, target_chapter, result["chapter_outline"])
    write_module9(workspace, result["module9_updated"])
    write_module10(workspace, result["module10_updated"])
    update_generated_chapter(workspace, target_chapter)
    return result


def generate_chapters_batch(
    *,
    workspace: Path,
    api_key: str,
    count: int,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: int = 300,
    retries: int = 3,
    retry_interval: int = 5,
) -> list[dict[str, Any]]:
    results = []
    for _ in range(max(0, count)):
        state = read_state(workspace)
        next_index = next_chapter_index(workspace)
        if state.total_chapters > 0 and next_index > state.total_chapters:
            break
        results.append(
            generate_next_chapter_outline(
                workspace=workspace,
                api_key=api_key,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                retries=retries,
                retry_interval=retry_interval,
            )
        )
    return results


def set_auto_confirm(workspace: Path, enabled: bool) -> None:
    state = read_state(workspace)
    state.auto_confirm = enabled
    write_state(workspace, state)


def save_source_only(workspace: Path, source_text: str) -> dict[str, Any]:
    state = init_from_source(workspace, source_text)
    save_source_novel(workspace, source_text)
    return state_summary(workspace)


def rebuild_final_abstract(workspace: Path) -> Path:
    return build_abstract(workspace)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="交互式小说大纲 agent。")
    parser.add_argument("workspace", help="小说工作目录")
    parser.add_argument("--source-file", help="原小说文本文件路径")
    parser.add_argument("--generate-global", action="store_true", help="生成全局大纲")
    parser.add_argument("--next-chapter", action="store_true", help="生成下一章模块5大纲")
    parser.add_argument("--batch", type=int, default=0, help="连续生成接下来 N 章")
    parser.add_argument("--build-abstract", action="store_true", help="合并为 Abstract.txt")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-interval", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    api_key = resolve_api_key(args.api_key, args.env_file)

    if args.generate_global:
        if args.source_file:
            source_text = Path(args.source_file).expanduser().read_text(encoding="utf-8")
        else:
            source_text = read_source_novel(workspace)
        if not source_text.strip():
            raise ValueError("缺少原小说文本，请提供 --source-file 或先保存 source_novel.txt。")
        result = generate_global_outline(
            workspace=workspace,
            source_text=source_text,
            api_key=api_key,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            timeout=args.timeout,
            retries=args.retries,
            retry_interval=args.retry_interval,
        )
        print(result.get("summary") or "全局大纲已生成。")

    if args.next_chapter:
        result = generate_next_chapter_outline(
            workspace=workspace,
            api_key=api_key,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            timeout=args.timeout,
            retries=args.retries,
            retry_interval=args.retry_interval,
        )
        print(result.get("progress_summary") or f"第 {result['chapter_index']} 章已生成。")

    if args.batch > 0:
        results = generate_chapters_batch(
            workspace=workspace,
            api_key=api_key,
            count=args.batch,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            timeout=args.timeout,
            retries=args.retries,
            retry_interval=args.retry_interval,
        )
        print(f"批量生成完成: {len(results)} 章。")

    if args.build_abstract:
        output_path = rebuild_final_abstract(workspace)
        print(f"已合并: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
