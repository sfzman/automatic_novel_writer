#!/usr/bin/env python3
"""Generate, review, and revise a multi-chapter novel with the DeepSeek API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from deepseek_client import call_deepseek_json, call_deepseek_text
from novel_utils import (
    DEFAULT_API_KEY,
    backup_pre_revision_chapter_files,
    chapter_finished,
    collect_previous_chapters_text,
    ensure_api_key,
    get_chapter_paths,
    get_review_result_path,
    get_revision_result_path,
    load_api_key_from_env_file,
    load_previous_notes,
    parse_chapter_json,
    parse_revision_json,
    read_text,
    resolve_relative_to_workspace,
    review_finished,
    revision_finished,
    write_text,
)
from prompts import (
    REVIEW_SYSTEM_PROMPT,
    REVISION_SYSTEM_PROMPT,
    WRITER_SYSTEM_PROMPT,
    build_review_user_prompt,
    build_revision_user_prompt,
    build_writer_user_prompt,
)

DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_OUTLINE_FILE = "Abstract.txt"
DEFAULT_ENV_FILE = ".env"
DEFAULT_MAX_TOKENS = 12000
DEFAULT_REVIEW_TEMPERATURE = 0.7
DEFAULT_REVISION_TEMPERATURE = 0.8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 DeepSeek 自动按章节写小说, 支持中断后续写。"
    )
    parser.add_argument("workspace", help="小说工作目录, 默认在该目录下读取 Abstract.txt")
    parser.add_argument("total_chapters", type=int, help="小说总章节数")
    parser.add_argument(
        "--outline-file",
        default=DEFAULT_OUTLINE_FILE,
        help=f"大纲文件名或路径, 默认: {DEFAULT_OUTLINE_FILE}",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help="DeepSeek API Key, 默认是占位符, 请自行替换",
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f".env 文件名或路径, 相对路径按当前运行目录解析, 默认: {DEFAULT_ENV_FILE}",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"DeepSeek 模型名, 默认: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"单章生成、审阅和修订的最大输出 token 数, 默认: {DEFAULT_MAX_TOKENS}",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=1.5,
        help="写作阶段的采样温度, 创意写作推荐偏高, 默认: 1.5",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="单次请求超时时间(秒), 默认: 300",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="接口失败时的最大重试次数, 默认: 3",
    )
    parser.add_argument(
        "--retry-interval",
        type=int,
        default=5,
        help="重试间隔(秒), 默认: 5",
    )
    return parser.parse_args()


def resolve_api_key(args: argparse.Namespace) -> str:
    env_path = Path(args.env_file).expanduser()
    api_key = args.api_key
    if api_key == DEFAULT_API_KEY:
        api_key = load_api_key_from_env_file(env_path) or os.environ.get(
            "DEEPSEEK_API_KEY", DEFAULT_API_KEY
        )
    ensure_api_key(api_key)
    return api_key


def load_outline(workspace: Path, outline_file: str) -> tuple[Path, str]:
    outline_path = resolve_relative_to_workspace(workspace, outline_file)
    if not outline_path.exists():
        raise FileNotFoundError(f"找不到小说大纲文件: {outline_path}")

    outline = read_text(outline_path)
    if not outline:
        raise ValueError(f"小说大纲为空: {outline_path}")

    return outline_path, outline


def generate_chapter(
    *,
    workspace: Path,
    outline: str,
    chapter_index: int,
    api_key: str,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
    retries: int,
    retry_interval: int,
) -> dict[str, str]:
    previous_creative_notes = load_previous_notes(workspace, chapter_index)
    writer_user_prompt = build_writer_user_prompt(
        outline=outline,
        previous_creative_notes=previous_creative_notes,
        chapter_index=chapter_index,
    )
    return call_deepseek_json(
        api_key=api_key,
        model=model,
        system_prompt=WRITER_SYSTEM_PROMPT,
        user_prompt=writer_user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        retries=retries,
        retry_interval=retry_interval,
        parse_response=parse_chapter_json,
    )


def run_chapter_review(
    *,
    workspace: Path,
    outline: str,
    chapter_index: int,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: int,
    retries: int,
    retry_interval: int,
) -> Path:
    previous_chapters_text = collect_previous_chapters_text(workspace, chapter_index)
    content_path, notes_path = get_chapter_paths(workspace, chapter_index)
    review_user_prompt = build_review_user_prompt(
        outline=outline,
        previous_chapters_text=previous_chapters_text,
        current_chapter_content=read_text(content_path),
        current_creative_notes=read_text(notes_path),
        chapter_index=chapter_index,
    )
    review_content = call_deepseek_text(
        api_key=api_key,
        model=model,
        system_prompt=REVIEW_SYSTEM_PROMPT,
        user_prompt=review_user_prompt,
        max_tokens=max_tokens,
        temperature=DEFAULT_REVIEW_TEMPERATURE,
        timeout=timeout,
        retries=retries,
        retry_interval=retry_interval,
    )
    review_path = get_review_result_path(workspace, chapter_index)
    write_text(review_path, review_content)
    return review_path


def run_chapter_revision(
    *,
    workspace: Path,
    outline: str,
    chapter_index: int,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: int,
    retries: int,
    retry_interval: int,
) -> Path:
    previous_creative_notes = load_previous_notes(workspace, chapter_index)
    content_path, notes_path = get_chapter_paths(workspace, chapter_index)
    review_path = get_review_result_path(workspace, chapter_index)
    backup_dir = backup_pre_revision_chapter_files(workspace, chapter_index)

    current_chapter_content = read_text(content_path)
    current_creative_notes = read_text(notes_path)
    review_feedback = read_text(review_path)

    writer_user_prompt = build_writer_user_prompt(
        outline=outline,
        previous_creative_notes=previous_creative_notes,
        chapter_index=chapter_index,
    )
    revision_user_prompt = build_revision_user_prompt(
        current_chapter_content=current_chapter_content,
        current_creative_notes=current_creative_notes,
        review_feedback=review_feedback,
        chapter_index=chapter_index,
    )
    writer_history = [
        {"role": "user", "content": writer_user_prompt},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "chapter_content": current_chapter_content,
                    "creative_notes": current_creative_notes,
                },
                ensure_ascii=False,
            ),
        },
    ]
    revision_result = call_deepseek_json(
        api_key=api_key,
        model=model,
        system_prompt=REVISION_SYSTEM_PROMPT,
        user_prompt=revision_user_prompt,
        max_tokens=max_tokens,
        temperature=DEFAULT_REVISION_TEMPERATURE,
        timeout=timeout,
        retries=retries,
        retry_interval=retry_interval,
        parse_response=parse_revision_json,
        extra_messages=writer_history,
    )

    write_text(content_path, revision_result["chapter_content"])
    write_text(notes_path, revision_result["creative_notes"])
    revision_path = get_revision_result_path(workspace, chapter_index)
    write_text(revision_path, revision_result["raw_json"])
    print(f"[备份] 第 {chapter_index} 章修订前副本已保存到 {backup_dir}")
    return revision_path


def generate_novel(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    if args.total_chapters <= 0:
        raise ValueError("total_chapters 必须大于 0。")

    api_key = resolve_api_key(args)
    outline_path, outline = load_outline(workspace, args.outline_file)

    print(f"工作目录: {workspace}")
    print(f"大纲文件: {outline_path}")
    print(f"目标章节数: {args.total_chapters}")

    for chapter_index in range(1, args.total_chapters + 1):
        content_path, notes_path = get_chapter_paths(workspace, chapter_index)
        review_path = get_review_result_path(workspace, chapter_index)
        revision_path = get_revision_result_path(workspace, chapter_index)

        if not chapter_finished(workspace, chapter_index):
            if content_path.exists() or notes_path.exists():
                print(
                    f"[重写] 第 {chapter_index} 章文件不完整, 将重新生成: {content_path.name}, {notes_path.name}"
                )
            print(f"[生成] 第 {chapter_index} 章...")
            result = generate_chapter(
                workspace=workspace,
                outline=outline,
                chapter_index=chapter_index,
                api_key=api_key,
                model=args.model,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                timeout=args.timeout,
                retries=args.retries,
                retry_interval=args.retry_interval,
            )
            write_text(content_path, result["chapter_content"])
            write_text(notes_path, result["creative_notes"])
            print(f"[完成] 第 {chapter_index} 章已保存到 {content_path.name} 和 {notes_path.name}")
        else:
            print(f"[跳过] 第 {chapter_index} 章已存在: {content_path.name}, {notes_path.name}")

        if not review_finished(workspace, chapter_index):
            print(f"[审阅] 第 {chapter_index} 章...")
            run_chapter_review(
                workspace=workspace,
                outline=outline,
                chapter_index=chapter_index,
                api_key=api_key,
                model=args.model,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                retries=args.retries,
                retry_interval=args.retry_interval,
            )
            print(f"[完成] 第 {chapter_index} 章审阅结果已保存到 {review_path.name}")
        else:
            print(f"[跳过] 第 {chapter_index} 章审阅结果已存在: {review_path.name}")

        if not revision_finished(workspace, chapter_index):
            print(f"[修订] 第 {chapter_index} 章...")
            run_chapter_revision(
                workspace=workspace,
                outline=outline,
                chapter_index=chapter_index,
                api_key=api_key,
                model=args.model,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                retries=args.retries,
                retry_interval=args.retry_interval,
            )
            print(f"[完成] 第 {chapter_index} 章修订结果已保存到 {revision_path.name}")
        else:
            print(f"[跳过] 第 {chapter_index} 章修订结果已存在: {revision_path.name}")

    print("全部章节处理完成。")


def main() -> int:
    args = parse_args()
    try:
        generate_novel(args)
    except KeyboardInterrupt:
        print("\n已中断, 下次运行会自动跳过已完成章节。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
