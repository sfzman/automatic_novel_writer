"""Build split-outline context for the chapter writing agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from novel_utils import collect_previous_chapters_text, load_previous_notes, read_text, write_text
from outline_workspace import (
    global_outline_path,
    list_chapter_outlines,
    module9_path,
    module10_path,
    read_chapter_outline,
    read_state,
)


DEFAULT_RECENT_CHAPTERS = 3


@dataclass
class SplitWritingContext:
    workspace: Path
    chapter_index: int
    total_chapters: int
    global_outline: str
    all_chapter_outlines: str
    current_chapter_outline: str
    module9: str
    module10: str
    previous_creative_notes: str
    previous_chapters_text: str

    def as_debug_text(self) -> str:
        return "\n\n".join(
            [
                f"# Split Writing Context\nchapter_index={self.chapter_index}\ntotal_chapters={self.total_chapters}",
                "## Abstract_global.txt\n" + self.global_outline,
                "## 已生成模块5逐章大纲\n" + self.all_chapter_outlines,
                f"## 当前第{self.chapter_index}章执行大纲\n" + self.current_chapter_outline,
                "## module9_foreshadowing.txt\n" + self.module9,
                "## module10_pacing.txt\n" + self.module10,
                "## 前文创作笔记\n" + self.previous_creative_notes,
                "## 最近已完成正文\n" + self.previous_chapters_text,
            ]
        )


def split_outline_available(workspace: Path) -> bool:
    return (
        global_outline_path(workspace).exists()
        and (workspace / "outlines").is_dir()
        and module9_path(workspace).exists()
        and module10_path(workspace).exists()
    )


def infer_total_chapters(workspace: Path, explicit_total: int | None = None) -> int:
    if explicit_total and explicit_total > 0:
        return explicit_total
    state = read_state(workspace)
    if state.total_chapters > 0:
        return state.total_chapters
    chapter_indexes = list_chapter_outlines(workspace)
    if chapter_indexes:
        return max(chapter_indexes)
    raise ValueError("无法确定总章节数：请传入 total_chapters，或提供 outline_state.json。")


def collect_recent_chapters_text(
    workspace: Path,
    chapter_index: int,
    recent_chapters: int = DEFAULT_RECENT_CHAPTERS,
) -> str:
    if recent_chapters <= 0:
        return "未提供最近正文。"
    start = max(1, chapter_index - recent_chapters)
    parts = []
    for idx in range(start, chapter_index):
        content_path = workspace / f"chapter_{idx}_content.txt"
        if content_path.exists() and content_path.stat().st_size > 0:
            parts.append(f"## 第{idx}章正文\n{read_text(content_path)}")
    if not parts:
        return "无。这是第一章，或最近章节正文尚未生成。"
    return "\n\n".join(parts)


def read_chapter_outlines_until(workspace: Path, max_chapter_index: int) -> str:
    parts = []
    for chapter_index in list_chapter_outlines(workspace):
        if chapter_index > max_chapter_index:
            continue
        content = read_chapter_outline(workspace, chapter_index)
        if content:
            parts.append(f"## 已生成第{chapter_index}章大纲\n{content}")
    if not parts:
        return "无。当前尚未生成任何模块5逐章大纲。"
    return "\n\n---\n\n".join(parts)


def build_split_writing_context(
    workspace: Path,
    chapter_index: int,
    total_chapters: int | None = None,
    recent_chapters: int = DEFAULT_RECENT_CHAPTERS,
    include_all_previous_text: bool = False,
) -> SplitWritingContext:
    resolved_total = infer_total_chapters(workspace, total_chapters)
    global_path = global_outline_path(workspace)
    if not global_path.exists():
        raise FileNotFoundError(f"缺少全局大纲文件: {global_path}")

    current_chapter_outline = read_chapter_outline(workspace, chapter_index)
    if not current_chapter_outline:
        raise FileNotFoundError(
            f"缺少第 {chapter_index} 章模块5大纲: {workspace / 'outlines' / f'chapter_{chapter_index}_outline.txt'}"
        )

    previous_text = (
        collect_previous_chapters_text(workspace, chapter_index)
        if include_all_previous_text
        else collect_recent_chapters_text(workspace, chapter_index, recent_chapters)
    )
    return SplitWritingContext(
        workspace=workspace,
        chapter_index=chapter_index,
        total_chapters=resolved_total,
        global_outline=read_text(global_path),
        all_chapter_outlines=read_chapter_outlines_until(workspace, resolved_total),
        current_chapter_outline=current_chapter_outline,
        module9=read_text(module9_path(workspace)),
        module10=read_text(module10_path(workspace)),
        previous_creative_notes=load_previous_notes(workspace, chapter_index),
        previous_chapters_text=previous_text,
    )


def write_split_context_debug(
    workspace: Path,
    context: SplitWritingContext,
    suffix: str = "writing_context",
) -> Path:
    path = workspace / f"chapter_{context.chapter_index}_{suffix}.txt"
    write_text(path, context.as_debug_text())
    return path
