"""Scan chapter content files for suspicious meta-narrative phrases."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PATTERNS = {
    "chapter_ref": re.compile(r"第\s*\d+\s*章"),
    "prev_chapter": re.compile(r"上一章"),
    "next_chapter": re.compile(r"下一章"),
    "current_chapter": re.compile(r"本章"),
    "reader": re.compile(r"读者"),
    "author": re.compile(r"作者后记|——作者|作者按|作者注"),
    "camera": re.compile(r"镜头"),
    "scene": re.compile(r"这一幕"),
    "paragraph": re.compile(r"本段"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan chapter_*_content.txt files for suspicious meta phrases."
    )
    parser.add_argument("folders", nargs="+", help="Novel folders to scan")
    return parser.parse_args()


def iter_content_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("chapter_*_content.txt"))


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    matches: list[tuple[int, str, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                matches.append((line_no, label, line.strip()))
    return matches


def main() -> int:
    args = parse_args()
    for raw_folder in args.folders:
        folder = Path(raw_folder).expanduser().resolve()
        print(f"== {folder} ==")
        if not folder.exists() or not folder.is_dir():
            print("ERROR: folder not found")
            print()
            continue

        total_files = 0
        suspicious_files = 0
        total_matches = 0

        for path in iter_content_files(folder):
            total_files += 1
            matches = scan_file(path)
            if not matches:
                continue

            suspicious_files += 1
            total_matches += len(matches)
            print(f"{path.name}: {len(matches)} match(es)")
            for line_no, label, line in matches:
                print(f"  L{line_no} [{label}] {line}")

        print(
            f"SUMMARY files={total_files} suspicious_files={suspicious_files} matches={total_matches}"
        )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
