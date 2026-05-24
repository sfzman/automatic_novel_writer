"""Filesystem, parsing, and chapter-state helpers for the novel pipeline."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_API_KEY = "YOUR_DEEPSEEK_API_KEY"


class DeepSeekAPIError(RuntimeError):
    """Raised when the DeepSeek API returns an invalid response."""


def resolve_relative_to_workspace(workspace: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return workspace / candidate


def load_api_key_from_env_file(env_path: Path) -> str | None:
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        if key.strip() != "DEEPSEEK_API_KEY":
            continue

        parsed = value.strip()
        if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {"'", '"'}:
            parsed = parsed[1:-1]
        return parsed.strip() or None

    return None


def ensure_api_key(api_key: str) -> None:
    if not api_key or api_key == DEFAULT_API_KEY:
        raise ValueError(
            "请先在脚本里填入 DeepSeek API Key, 或通过 --api-key / .env / 环境变量 DEEPSEEK_API_KEY 提供真实的 key。"
        )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def write_text(path: Path, content: str) -> None:
    path.write_text(content.strip() + "\n", encoding="utf-8")


def get_chapter_paths(workspace: Path, chapter_index: int) -> tuple[Path, Path]:
    return (
        workspace / f"chapter_{chapter_index}_content.txt",
        workspace / f"chapter_{chapter_index}_notes.txt",
    )


def get_review_result_path(workspace: Path, chapter_index: int) -> Path:
    return workspace / f"chapter_{chapter_index}_review_result.txt"


def get_revision_result_path(workspace: Path, chapter_index: int) -> Path:
    return workspace / f"chapter_{chapter_index}_revision_result.txt"


def get_pre_revision_backup_root(workspace: Path) -> Path:
    return workspace / "_pre_revision_backups"


def backup_pre_revision_chapter_files(workspace: Path, chapter_index: int) -> Path:
    content_path, notes_path = get_chapter_paths(workspace, chapter_index)
    missing = [str(path.name) for path in (content_path, notes_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"修订前备份失败，缺少文件: {', '.join(missing)}"
        )

    backup_root = get_pre_revision_backup_root(workspace)
    chapter_backup_dir = backup_root / f"chapter_{chapter_index}"
    chapter_backup_dir.mkdir(parents=True, exist_ok=True)

    existing_versions = sorted(
        path for path in chapter_backup_dir.iterdir() if path.is_dir() and path.name.startswith("snapshot_")
    )
    snapshot_dir = chapter_backup_dir / f"snapshot_{len(existing_versions) + 1:03d}"
    snapshot_dir.mkdir()

    (snapshot_dir / content_path.name).write_text(
        content_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (snapshot_dir / notes_path.name).write_text(
        notes_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (snapshot_dir / "backup_info.json").write_text(
        json.dumps(
            {
                "chapter_index": chapter_index,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_files": [content_path.name, notes_path.name],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return snapshot_dir


def chapter_finished(workspace: Path, chapter_index: int) -> bool:
    content_path, notes_path = get_chapter_paths(workspace, chapter_index)
    return all(
        path.exists() and path.stat().st_size > 0
        for path in (content_path, notes_path)
    )


def review_finished(workspace: Path, chapter_index: int) -> bool:
    review_path = get_review_result_path(workspace, chapter_index)
    return review_path.exists() and review_path.stat().st_size > 0


def revision_finished(workspace: Path, chapter_index: int) -> bool:
    revision_path = get_revision_result_path(workspace, chapter_index)
    return revision_path.exists() and revision_path.stat().st_size > 0


def load_previous_notes(workspace: Path, chapter_index: int) -> str:
    if chapter_index <= 1:
        return "创作笔记:\n暂无, 这是第一章, 请直接展开故事并埋下后续钩子。"

    previous_notes: list[str] = []
    for idx in range(1, chapter_index):
        _, notes_path = get_chapter_paths(workspace, idx)
        if notes_path.exists() and notes_path.stat().st_size > 0:
            previous_notes.append(f"第{idx}章创作笔记:\n{read_text(notes_path)}")

    if not previous_notes:
        return "创作笔记:\n暂无可用历史笔记, 请在本章完成后补充完整剧情脉络。"

    return "创作笔记:\n" + "\n\n".join(previous_notes)


def collect_previous_chapters_text(workspace: Path, chapter_index: int) -> str:
    previous_chapters: list[str] = []
    for idx in range(1, chapter_index):
        content_path, _ = get_chapter_paths(workspace, idx)
        if content_path.exists() and content_path.stat().st_size > 0:
            previous_chapters.append(f"## 第{idx}章正文\n{read_text(content_path)}")

    if not previous_chapters:
        return "无。这是第一章，暂无之前完成的篇章正文。"

    return "\n\n".join(previous_chapters)


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def repair_common_json_issues(text: str) -> str:
    """Best-effort repair for common model JSON mistakes.

    Today we only fix raw control characters that appear inside JSON strings,
    which is the most common failure mode when the model emits multi-line text
    without escaping newlines.
    """

    repaired_chars: list[str] = []
    in_string = False
    escape_next = False

    for char in text:
        if in_string:
            if escape_next:
                repaired_chars.append(char)
                escape_next = False
                continue
            if char == "\\":
                repaired_chars.append(char)
                escape_next = True
                continue
            if char == '"':
                repaired_chars.append(char)
                in_string = False
                continue
            if char == "\n":
                repaired_chars.append("\\n")
                continue
            if char == "\r":
                repaired_chars.append("\\r")
                continue
            if char == "\t":
                repaired_chars.append("\\t")
                continue
            repaired_chars.append(char)
            continue

        repaired_chars.append(char)
        if char == '"':
            in_string = True

    return "".join(repaired_chars)


def load_json_with_repair(text: str) -> tuple[dict[str, Any], str]:
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise DeepSeekAPIError("模型输出的 JSON 不是对象。")
        return data, text
    except json.JSONDecodeError:
        repaired = repair_common_json_issues(text)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise DeepSeekAPIError(f"模型输出不是合法 JSON: {text}") from exc
        if not isinstance(data, dict):
            raise DeepSeekAPIError("模型输出的 JSON 不是对象。")
        return data, repaired


def parse_chapter_json(content: str) -> dict[str, Any]:
    cleaned = strip_code_fences(content)
    data, normalized_json = load_json_with_repair(cleaned)

    chapter_content = str(data.get("chapter_content", "")).strip()
    creative_notes = str(data.get("creative_notes", "")).strip()
    if not chapter_content:
        raise DeepSeekAPIError("模型输出缺少 chapter_content。")
    if not creative_notes:
        raise DeepSeekAPIError("模型输出缺少 creative_notes。")

    return {
        "chapter_content": chapter_content,
        "creative_notes": creative_notes,
        "raw_json": normalized_json,
    }


def _normalize_object_list(items: Any, key_map: tuple[str, ...]) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            normalized_item = {
                key: str(item.get(key, "")).strip()
                for key in key_map
            }
            normalized.append(normalized_item)
        elif isinstance(item, str):
            normalized.append({key_map[0]: item.strip(), key_map[1]: ""})
    return normalized


def _normalize_string_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def parse_revision_json(content: str) -> dict[str, Any]:
    base = parse_chapter_json(content)
    data, _ = load_json_with_repair(base["raw_json"])

    revision_summary = str(data.get("revision_summary", "")).strip()
    if not revision_summary:
        raise DeepSeekAPIError("模型输出缺少 revision_summary。")

    adopted_review_items = _normalize_object_list(
        data.get("adopted_review_items"),
        ("issue", "action"),
    )
    rejected_review_items = _normalize_object_list(
        data.get("rejected_review_items"),
        ("issue", "reason"),
    )
    changed_sections = _normalize_string_list(data.get("changed_sections"))

    normalized = {
        "chapter_content": base["chapter_content"],
        "creative_notes": base["creative_notes"],
        "revision_summary": revision_summary,
        "adopted_review_items": adopted_review_items,
        "rejected_review_items": rejected_review_items,
        "changed_sections": changed_sections,
    }
    normalized["raw_json"] = json.dumps(
        normalized,
        ensure_ascii=False,
        indent=2,
    )
    return normalized
