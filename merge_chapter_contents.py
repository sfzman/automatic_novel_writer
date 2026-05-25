"""Merge chapter_{index}_content.txt files from a target directory."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHAPTER_PATTERN = re.compile(r"chapter_(\d+)_content\.txt$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge chapter_{index}_content.txt files in numeric order."
    )
    parser.add_argument("folder", help="Folder containing chapter content files")
    return parser.parse_args()


def find_chapter_files(folder: Path) -> list[tuple[int, Path]]:
    chapter_files: list[tuple[int, Path]] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        match = CHAPTER_PATTERN.fullmatch(path.name)
        if not match:
            continue
        chapter_files.append((int(match.group(1)), path))

    return sorted(chapter_files, key=lambda item: item[0])


def build_output_path(folder: Path, chapter_indexes: list[int]) -> Path:
    start = chapter_indexes[0]
    end = chapter_indexes[-1]
    return folder / f"all_chapters_{start}_to_{end}_merged.txt"


def merge_chapters(folder: Path) -> Path:
    if not folder.exists():
        raise FileNotFoundError(f"目录不存在: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"输入路径不是文件夹: {folder}")

    chapter_files = find_chapter_files(folder)
    if not chapter_files:
        raise FileNotFoundError(
            f"在 {folder} 中没有找到 chapter_{{index}}_content.txt 文件"
        )

    chapter_indexes = [index for index, _ in chapter_files]
    merged_parts = []
    for chapter_index, path in chapter_files:
        chapter_title = f"----------第{chapter_index}章----------"
        chapter_content = path.read_text(encoding="utf-8").strip()
        merged_parts.append(f"{chapter_title}\n{chapter_content}")

    output_path = build_output_path(folder, chapter_indexes)
    output_path.write_text("\n\n".join(merged_parts).strip() + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    args = parse_args()
    folder = Path(args.folder).expanduser().resolve()

    try:
        output_path = merge_chapters(folder)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"合并完成: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
