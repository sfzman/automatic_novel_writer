"""Workspace files and state helpers for the outline agent."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SOURCE_NOVEL_FILE = "source_novel.txt"
USER_REQUIREMENTS_FILE = "user_requirements.txt"
GLOBAL_OUTLINE_FILE = "Abstract_global.txt"
MODULE9_FILE = "module9_foreshadowing.txt"
MODULE10_FILE = "module10_pacing.txt"
STATE_FILE = "outline_state.json"
OUTLINES_DIR = "outlines"
FINAL_ABSTRACT_FILE = "Abstract.txt"

CHAPTER_PATTERN = re.compile(
    r"(?im)(?:^|\n)\s*(?:第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*[章节回卷部集]|chapter\s*\d+)\b"
)


@dataclass
class OutlineState:
    total_chapters: int = 0
    generated_chapters: list[int] | None = None
    source_meaningful_chars: int = 0
    detected_source_chapters: int = 0
    target_total_chars: int = 0
    auto_confirm: bool = False

    def __post_init__(self) -> None:
        if self.generated_chapters is None:
            self.generated_chapters = []


def ensure_workspace(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / OUTLINES_DIR).mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def count_meaningful_chars(text: str) -> int:
    """Count content characters, excluding punctuation, separators, and controls."""

    count = 0
    for char in text:
        category = unicodedata.category(char)
        if category.startswith(("P", "Z", "C")):
            continue
        count += 1
    return count


def detect_chapter_count(text: str) -> int:
    matches = CHAPTER_PATTERN.findall(text)
    return len(matches)


def suggest_target_chapters(meaningful_chars: int, detected_chapters: int) -> int:
    if detected_chapters > 0:
        return max(1, detected_chapters)
    if meaningful_chars <= 10_000:
        return max(1, round(meaningful_chars / 1500))
    if meaningful_chars <= 50_000:
        return max(8, round(meaningful_chars / 1500))
    if meaningful_chars <= 120_000:
        return max(25, round(meaningful_chars / 1700))
    return max(70, round(meaningful_chars / 1800))


def save_source_novel(workspace: Path, source_text: str) -> None:
    ensure_workspace(workspace)
    write_text(workspace / SOURCE_NOVEL_FILE, source_text)


def read_source_novel(workspace: Path) -> str:
    return read_text(workspace / SOURCE_NOVEL_FILE)


def read_user_requirements(workspace: Path) -> str:
    return read_text(workspace / USER_REQUIREMENTS_FILE)


def write_user_requirements(workspace: Path, content: str) -> None:
    write_text(workspace / USER_REQUIREMENTS_FILE, content)


def read_state(workspace: Path) -> OutlineState:
    path = workspace / STATE_FILE
    if not path.exists():
        return OutlineState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return OutlineState(
        total_chapters=int(data.get("total_chapters") or 0),
        generated_chapters=[int(item) for item in data.get("generated_chapters") or []],
        source_meaningful_chars=int(data.get("source_meaningful_chars") or 0),
        detected_source_chapters=int(data.get("detected_source_chapters") or 0),
        target_total_chars=int(data.get("target_total_chars") or 0),
        auto_confirm=bool(data.get("auto_confirm") or False),
    )


def write_state(workspace: Path, state: OutlineState) -> None:
    ensure_workspace(workspace)
    data = asdict(state)
    data["generated_chapters"] = sorted(set(data["generated_chapters"] or []))
    (workspace / STATE_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def global_outline_path(workspace: Path) -> Path:
    return workspace / GLOBAL_OUTLINE_FILE


def module9_path(workspace: Path) -> Path:
    return workspace / MODULE9_FILE


def module10_path(workspace: Path) -> Path:
    return workspace / MODULE10_FILE


def chapter_outline_path(workspace: Path, chapter_index: int) -> Path:
    return workspace / OUTLINES_DIR / f"chapter_{chapter_index}_outline.txt"


def read_global_outline(workspace: Path) -> str:
    return read_text(global_outline_path(workspace))


def write_global_outline(workspace: Path, content: str) -> None:
    write_text(global_outline_path(workspace), content)


def read_module9(workspace: Path) -> str:
    return read_text(module9_path(workspace))


def write_module9(workspace: Path, content: str) -> None:
    write_text(module9_path(workspace), content)


def read_module10(workspace: Path) -> str:
    return read_text(module10_path(workspace))


def write_module10(workspace: Path, content: str) -> None:
    write_text(module10_path(workspace), content)


def read_chapter_outline(workspace: Path, chapter_index: int) -> str:
    return read_text(chapter_outline_path(workspace, chapter_index))


def write_chapter_outline(workspace: Path, chapter_index: int, content: str) -> None:
    write_text(chapter_outline_path(workspace, chapter_index), content)


def list_chapter_outlines(workspace: Path) -> list[int]:
    outlines_root = workspace / OUTLINES_DIR
    if not outlines_root.exists():
        return []
    chapter_indexes: list[int] = []
    for path in outlines_root.glob("chapter_*_outline.txt"):
        match = re.fullmatch(r"chapter_(\d+)_outline\.txt", path.name)
        if match:
            chapter_indexes.append(int(match.group(1)))
    return sorted(chapter_indexes)


def read_all_chapter_outlines(workspace: Path) -> str:
    parts = []
    for chapter_index in list_chapter_outlines(workspace):
        content = read_chapter_outline(workspace, chapter_index)
        if content:
            parts.append(f"## 已生成第{chapter_index}章大纲\n{content}")
    if not parts:
        return "无。当前尚未生成任何模块5逐章大纲。"
    return "\n\n---\n\n".join(parts)


def update_generated_chapter(workspace: Path, chapter_index: int) -> OutlineState:
    state = read_state(workspace)
    generated = set(state.generated_chapters or [])
    generated.add(chapter_index)
    state.generated_chapters = sorted(generated)
    write_state(workspace, state)
    return state


def next_chapter_index(workspace: Path) -> int:
    state = read_state(workspace)
    generated = sorted(set(state.generated_chapters or list_chapter_outlines(workspace)))
    if not generated:
        return 1
    return generated[-1] + 1


def build_abstract(workspace: Path) -> Path:
    user_requirements = read_user_requirements(workspace)
    global_outline = read_global_outline(workspace)
    module9 = read_module9(workspace)
    module10 = read_module10(workspace)
    chapter_parts = []
    for chapter_index in list_chapter_outlines(workspace):
        chapter_parts.append(read_chapter_outline(workspace, chapter_index))

    parts = [
        f"## 用户额外要求\n{user_requirements}" if user_requirements else "",
        global_outline,
        "## 模块5：逐章连载执行大纲",
        "\n\n---\n\n".join(part for part in chapter_parts if part),
        module9,
        module10,
    ]
    output = "\n\n---\n\n".join(part for part in parts if part.strip())
    output_path = workspace / FINAL_ABSTRACT_FILE
    write_text(output_path, output)
    return output_path


def init_from_source(workspace: Path, source_text: str) -> OutlineState:
    ensure_workspace(workspace)
    save_source_novel(workspace, source_text)
    meaningful_chars = count_meaningful_chars(source_text)
    detected_chapters = detect_chapter_count(source_text)
    target_chapters = suggest_target_chapters(meaningful_chars, detected_chapters)
    state = read_state(workspace)
    state.source_meaningful_chars = meaningful_chars
    state.detected_source_chapters = detected_chapters
    state.target_total_chars = meaningful_chars
    if state.total_chapters <= 0:
        state.total_chapters = target_chapters
    write_state(workspace, state)
    return state


def state_summary(workspace: Path) -> dict[str, Any]:
    state = read_state(workspace)
    generated = sorted(set(state.generated_chapters or list_chapter_outlines(workspace)))
    return {
        "total_chapters": state.total_chapters,
        "generated_chapters": generated,
        "generated_count": len(generated),
        "source_meaningful_chars": state.source_meaningful_chars,
        "detected_source_chapters": state.detected_source_chapters,
        "target_total_chars": state.target_total_chars,
        "next_chapter": next_chapter_index(workspace),
    }
