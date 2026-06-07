#!/usr/bin/env python3
"""Generate, review, and revise a multi-chapter novel with a switchable LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm_client import LLMConfig, call_llm_json, call_llm_text, resolve_llm_config
from novel_utils import (
    DEFAULT_API_KEY,
    backup_pre_revision_chapter_files,
    chapter_finished,
    collect_previous_chapters_text,
    get_chapter_paths,
    get_review_result_path,
    get_revision_result_path,
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
    build_review_split_user_prompt,
    build_revision_user_prompt,
    build_revision_split_user_prompt,
    build_writer_user_prompt,
    build_writer_split_user_prompt,
)
from writing_context import (
    build_split_writing_context,
    infer_total_chapters,
    split_outline_available,
    write_split_context_debug,
)

DEFAULT_PROVIDER = "deepseek"
DEFAULT_WRITER_PROVIDER = "volcengine"
DEFAULT_REVISION_PROVIDER = "volcengine"
DEFAULT_MODEL = ""
DEFAULT_OUTLINE_FILE = "Abstract.txt"
DEFAULT_ENV_FILE = ".env"
DEFAULT_MAX_TOKENS = 12000
DEFAULT_REVIEW_TEMPERATURE = 0.7
DEFAULT_REVISION_TEMPERATURE = 0.8
DEFAULT_OUTLINE_MODE = "auto"
DEFAULT_RECENT_CHAPTERS = 3
LONG_CONTEXT_MODEL_HINT = (
    "提示: Abstract/大纲 agent 会读取整篇原文，review agent 会读取大量前文；"
    "最好使用百万上下文或足够长上下文的模型，避免截断、漏读或连载状态漂移。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用可切换 LLM 自动按章节写小说, 支持中断后续写。"
    )
    parser.add_argument("workspace", help="小说工作目录")
    parser.add_argument("total_chapters", type=int, nargs="?", help="小说总章节数")
    parser.add_argument(
        "--total-chapters",
        dest="total_chapters_override",
        type=int,
        help="小说总章节数；优先级高于位置参数，split 模式不填时会读取 outline_state.json",
    )
    parser.add_argument(
        "--outline-mode",
        choices=("auto", "merged", "split"),
        default=DEFAULT_OUTLINE_MODE,
        help=(
            "大纲读取模式: merged=读取 Abstract.txt, split=读取 Abstract_global/outlines/module9/module10, "
            f"auto=自动判断, 默认: {DEFAULT_OUTLINE_MODE}"
        ),
    )
    parser.add_argument(
        "--outline-file",
        default=DEFAULT_OUTLINE_FILE,
        help=f"大纲文件名或路径, 默认: {DEFAULT_OUTLINE_FILE}",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help="通用 API Key；也可在 .env 中配置 provider 对应的环境变量",
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f".env 文件名或路径, 相对路径按当前运行目录解析, 默认: {DEFAULT_ENV_FILE}",
    )
    parser.add_argument(
        "--provider",
        default="",
        help="通用 provider；为空时写作/修订默认 volcengine，审阅默认 deepseek",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="通用 OpenAI-compatible base_url；默认读取 provider 内置值或 .env",
    )
    parser.add_argument(
        "--model",
        default="",
        help="通用模型名；为空时读取 .env/provider 默认，火山默认 kimi2.6",
    )
    parser.add_argument(
        "--writer-provider",
        default="",
        help="写作阶段 provider；为空时使用 --provider；仍为空则默认 volcengine",
    )
    parser.add_argument(
        "--writer-base-url",
        default="",
        help="写作阶段 base_url；为空时使用 --base-url/provider 默认值",
    )
    parser.add_argument(
        "--writer-api-key",
        default="",
        help="写作阶段 API Key；为空时使用 --api-key 或 provider 对应环境变量",
    )
    parser.add_argument(
        "--writer-model",
        default="",
        help="写作阶段模型；为空时使用 --model",
    )
    parser.add_argument(
        "--review-provider",
        default="",
        help="审阅阶段 provider；建议使用百万上下文/长上下文模型；为空时使用 --provider，仍为空则默认 deepseek",
    )
    parser.add_argument(
        "--review-base-url",
        default="",
        help="审阅阶段 base_url；为空时使用 --base-url/provider 默认值",
    )
    parser.add_argument(
        "--review-api-key",
        default="",
        help="审阅阶段 API Key；为空时使用 --api-key 或 provider 对应环境变量",
    )
    parser.add_argument(
        "--review-model",
        default="",
        help="审阅阶段模型；建议使用百万上下文/长上下文模型；为空时使用 --model",
    )
    parser.add_argument(
        "--revision-provider",
        default="",
        help="修订阶段 provider；为空时使用 --provider；仍为空则默认 volcengine",
    )
    parser.add_argument(
        "--revision-base-url",
        default="",
        help="修订阶段 base_url；为空时使用 --base-url/provider 默认值",
    )
    parser.add_argument(
        "--revision-api-key",
        default="",
        help="修订阶段 API Key；为空时使用 --api-key 或 provider 对应环境变量",
    )
    parser.add_argument(
        "--revision-model",
        default="",
        help="修订阶段模型；为空时使用 --model",
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
    parser.add_argument(
        "--recent-chapters",
        type=int,
        default=DEFAULT_RECENT_CHAPTERS,
        help=f"split 模式写作/修订时额外提供最近 N 章正文, 默认: {DEFAULT_RECENT_CHAPTERS}",
    )
    parser.add_argument(
        "--include-all-previous-text",
        action="store_true",
        help="split 模式下向写作/修订也提供所有前文章节正文；默认只提供最近 N 章正文",
    )
    parser.add_argument(
        "--no-context-debug",
        action="store_true",
        help="split 模式下不保存 chapter_N_writing_context.txt 调试文件",
    )
    return parser.parse_args()


def resolve_stage_llm_config(args: argparse.Namespace, stage: str) -> LLMConfig:
    stage_default_providers = {
        "writer": DEFAULT_WRITER_PROVIDER,
        "revision": DEFAULT_REVISION_PROVIDER,
        "review": DEFAULT_PROVIDER,
    }
    provider = getattr(args, f"{stage}_provider") or args.provider or stage_default_providers[stage]
    base_url = getattr(args, f"{stage}_base_url") or args.base_url
    api_key = getattr(args, f"{stage}_api_key") or args.api_key
    model = getattr(args, f"{stage}_model") or args.model
    return resolve_llm_config(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        env_file=args.env_file,
    )


def load_outline(workspace: Path, outline_file: str) -> tuple[Path, str]:
    outline_path = resolve_relative_to_workspace(workspace, outline_file)
    if not outline_path.exists():
        raise FileNotFoundError(f"找不到小说大纲文件: {outline_path}")

    outline = read_text(outline_path)
    if not outline:
        raise ValueError(f"小说大纲为空: {outline_path}")

    return outline_path, outline


def resolve_total_chapters(args: argparse.Namespace, workspace: Path, outline_mode: str) -> int:
    explicit_total = args.total_chapters_override or args.total_chapters
    if outline_mode == "split":
        return infer_total_chapters(workspace, explicit_total)
    if not explicit_total:
        raise ValueError("merged 模式必须提供 total_chapters。")
    if explicit_total <= 0:
        raise ValueError("total_chapters 必须大于 0。")
    return explicit_total


def resolve_outline_mode(workspace: Path, requested_mode: str) -> str:
    if requested_mode != "auto":
        return requested_mode
    return "split" if split_outline_available(workspace) else "merged"


def generate_chapter(
    *,
    workspace: Path,
    outline: str,
    chapter_index: int,
    llm_config: LLMConfig,
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
    return call_llm_json(
        config=llm_config,
        system_prompt=WRITER_SYSTEM_PROMPT,
        user_prompt=writer_user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        retries=retries,
        retry_interval=retry_interval,
        parse_response=parse_chapter_json,
    )


def generate_chapter_split(
    *,
    workspace: Path,
    chapter_index: int,
    total_chapters: int,
    llm_config: LLMConfig,
    max_tokens: int,
    temperature: float,
    timeout: int,
    retries: int,
    retry_interval: int,
    recent_chapters: int,
    include_all_previous_text: bool,
    write_context_debug: bool,
) -> dict[str, str]:
    context = build_split_writing_context(
        workspace,
        chapter_index,
        total_chapters=total_chapters,
        recent_chapters=recent_chapters,
        include_all_previous_text=include_all_previous_text,
    )
    if write_context_debug:
        write_split_context_debug(workspace, context)
    writer_user_prompt = build_writer_split_user_prompt(
        global_outline=context.global_outline,
        all_chapter_outlines=context.all_chapter_outlines,
        current_chapter_outline=context.current_chapter_outline,
        module9=context.module9,
        module10=context.module10,
        previous_creative_notes=context.previous_creative_notes,
        previous_chapters_text=context.previous_chapters_text,
        chapter_index=chapter_index,
        total_chapters=total_chapters,
    )
    return call_llm_json(
        config=llm_config,
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
    llm_config: LLMConfig,
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
    review_content = call_llm_text(
        config=llm_config,
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


def run_chapter_review_split(
    *,
    workspace: Path,
    chapter_index: int,
    total_chapters: int,
    llm_config: LLMConfig,
    max_tokens: int,
    timeout: int,
    retries: int,
    retry_interval: int,
) -> Path:
    context = build_split_writing_context(
        workspace,
        chapter_index,
        total_chapters=total_chapters,
        include_all_previous_text=True,
    )
    content_path, notes_path = get_chapter_paths(workspace, chapter_index)
    review_user_prompt = build_review_split_user_prompt(
        global_outline=context.global_outline,
        all_chapter_outlines=context.all_chapter_outlines,
        current_chapter_outline=context.current_chapter_outline,
        module9=context.module9,
        module10=context.module10,
        previous_chapters_text=context.previous_chapters_text,
        current_chapter_content=read_text(content_path),
        current_creative_notes=read_text(notes_path),
        chapter_index=chapter_index,
    )
    review_content = call_llm_text(
        config=llm_config,
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
    llm_config: LLMConfig,
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
    revision_result = call_llm_json(
        config=llm_config,
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


def run_chapter_revision_split(
    *,
    workspace: Path,
    chapter_index: int,
    total_chapters: int,
    llm_config: LLMConfig,
    max_tokens: int,
    timeout: int,
    retries: int,
    retry_interval: int,
    recent_chapters: int,
    include_all_previous_text: bool,
    write_context_debug: bool,
) -> Path:
    context = build_split_writing_context(
        workspace,
        chapter_index,
        total_chapters=total_chapters,
        recent_chapters=recent_chapters,
        include_all_previous_text=include_all_previous_text,
    )
    if write_context_debug:
        write_split_context_debug(workspace, context, suffix="revision_context")

    content_path, notes_path = get_chapter_paths(workspace, chapter_index)
    review_path = get_review_result_path(workspace, chapter_index)
    backup_dir = backup_pre_revision_chapter_files(workspace, chapter_index)

    current_chapter_content = read_text(content_path)
    current_creative_notes = read_text(notes_path)
    review_feedback = read_text(review_path)

    writer_user_prompt = build_writer_split_user_prompt(
        global_outline=context.global_outline,
        all_chapter_outlines=context.all_chapter_outlines,
        current_chapter_outline=context.current_chapter_outline,
        module9=context.module9,
        module10=context.module10,
        previous_creative_notes=context.previous_creative_notes,
        previous_chapters_text=context.previous_chapters_text,
        chapter_index=chapter_index,
        total_chapters=total_chapters,
    )
    revision_user_prompt = build_revision_split_user_prompt(
        global_outline=context.global_outline,
        current_chapter_outline=context.current_chapter_outline,
        module9=context.module9,
        module10=context.module10,
        previous_creative_notes=context.previous_creative_notes,
        previous_chapters_text=context.previous_chapters_text,
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
    revision_result = call_llm_json(
        config=llm_config,
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

    outline_mode = resolve_outline_mode(workspace, args.outline_mode)
    total_chapters = resolve_total_chapters(args, workspace, outline_mode)
    writer_config: LLMConfig | None = None
    review_config: LLMConfig | None = None
    revision_config: LLMConfig | None = None
    outline_path: Path | None = None
    outline = ""
    if outline_mode == "merged":
        outline_path, outline = load_outline(workspace, args.outline_file)

    print(f"工作目录: {workspace}")
    print(f"大纲模式: {outline_mode}")
    if outline_path is not None:
        print(f"大纲文件: {outline_path}")
    else:
        print("大纲文件: Abstract_global.txt + outlines/chapter_N_outline.txt + module9/module10")
    print(f"目标章节数: {total_chapters}")
    print(LONG_CONTEXT_MODEL_HINT)
    print("写作模型: 默认 volcengine/kimi2.6，可用 --writer-provider/--writer-model 覆盖")
    print("审阅模型: 默认 deepseek，可用 --review-provider/--review-model 覆盖")
    print("修订模型: 默认 volcengine/kimi2.6，可用 --revision-provider/--revision-model 覆盖")

    for chapter_index in range(1, total_chapters + 1):
        content_path, notes_path = get_chapter_paths(workspace, chapter_index)
        review_path = get_review_result_path(workspace, chapter_index)
        revision_path = get_revision_result_path(workspace, chapter_index)

        if not chapter_finished(workspace, chapter_index):
            if content_path.exists() or notes_path.exists():
                print(
                    f"[重写] 第 {chapter_index} 章文件不完整, 将重新生成: {content_path.name}, {notes_path.name}"
                )
            print(f"[生成] 第 {chapter_index} 章...")
            if writer_config is None:
                writer_config = resolve_stage_llm_config(args, "writer")
            if outline_mode == "split":
                result = generate_chapter_split(
                    workspace=workspace,
                    chapter_index=chapter_index,
                    total_chapters=total_chapters,
                    llm_config=writer_config,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    timeout=args.timeout,
                    retries=args.retries,
                    retry_interval=args.retry_interval,
                    recent_chapters=args.recent_chapters,
                    include_all_previous_text=args.include_all_previous_text,
                    write_context_debug=not args.no_context_debug,
                )
            else:
                result = generate_chapter(
                    workspace=workspace,
                    outline=outline,
                    chapter_index=chapter_index,
                    llm_config=writer_config,
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
            if review_config is None:
                review_config = resolve_stage_llm_config(args, "review")
                print(f"[审阅模型] {review_config.provider}/{review_config.model} ({review_config.base_url})")
            if outline_mode == "split":
                run_chapter_review_split(
                    workspace=workspace,
                    chapter_index=chapter_index,
                    total_chapters=total_chapters,
                    llm_config=review_config,
                    max_tokens=args.max_tokens,
                    timeout=args.timeout,
                    retries=args.retries,
                    retry_interval=args.retry_interval,
                )
            else:
                run_chapter_review(
                    workspace=workspace,
                    outline=outline,
                    chapter_index=chapter_index,
                    llm_config=review_config,
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
            if revision_config is None:
                revision_config = resolve_stage_llm_config(args, "revision")
            if outline_mode == "split":
                run_chapter_revision_split(
                    workspace=workspace,
                    chapter_index=chapter_index,
                    total_chapters=total_chapters,
                    llm_config=revision_config,
                    max_tokens=args.max_tokens,
                    timeout=args.timeout,
                    retries=args.retries,
                    retry_interval=args.retry_interval,
                    recent_chapters=args.recent_chapters,
                    include_all_previous_text=args.include_all_previous_text,
                    write_context_debug=not args.no_context_debug,
                )
            else:
                run_chapter_revision(
                    workspace=workspace,
                    outline=outline,
                    chapter_index=chapter_index,
                    llm_config=revision_config,
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
