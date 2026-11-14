#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 source/ 的抽取结果，为每一章生成 chapters/*.tex 骨架。

已存在的章节文件不会被覆盖（除非 --force）。

用法：
    python scripts/scaffold.py --project projects/my-book
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


def natural_key(path: Path):
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", path.name)]


def load_manifest(project: Path) -> dict[str, dict]:
    path = project / "source" / "manifest.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {row["file"]: row for row in csv.DictReader(fh)}


def title_of(md: str) -> str:
    for line in md.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="生成章节 LaTeX 骨架")
    parser.add_argument("--project", default=".")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    source = project / "source"
    if not source.exists():
        print(f"[错误] 找不到 {source}")
        return 1

    manifest = load_manifest(project)
    chapters_dir = project / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    front_dir = project / "frontmatter"
    front_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    md_files = sorted(source.glob("*.md"), key=natural_key)
    md_files += sorted((source / "frontmatter").glob("acknowledgments.md"))
    for md_path in md_files:
        if md_path.name.lower() == "readme.md" or not md_path.exists():
            continue
        rel = md_path.relative_to(source).as_posix()
        stem = md_path.stem
        is_ack = "acknowledg" in stem.lower()
        if is_ack:
            target = front_dir / "acknowledgments.tex"
            chapter = (
                "\\chapter*{致谢}\n"
                "\\addcontentsline{toc}{chapter}{致谢}\n"
                "\\markboth{致谢}{致谢}\n"
            )
        elif re.fullmatch(r"ch\d+", stem) or stem == "conclusion":
            target = chapters_dir / f"{stem}.tex"
            if stem == "conclusion":
                chapter = (
                    "\\chapter*{结论（待译）}\n"
                    "\\addcontentsline{toc}{chapter}{结论}\n"
                    "\\markboth{结论}{结论}\n"
                )
            else:
                chapter = f"\\chapter{{（待译）}}\n\\label{{ch:{stem}}}\n"
        else:
            continue

        if target.exists() and not args.force:
            continue

        md = md_path.read_text(encoding="utf-8-sig", errors="replace")
        original_title = title_of(md)
        info = manifest.get(rel, {})
        notes = len(re.findall(r"(?m)^\[\^[^\]]+\]:", md))
        figures = len(re.findall(r"!\[[^\]]*\]\(", md))
        words = info.get("words", "")
        header = [
            f"% 源文件：source/{rel}",
            f"% 原文标题：{original_title}",
        ]
        if words:
            header.append(f"% 原文规模：{words} 词，{notes} 条脚注，{figures} 幅图")
        header += [
            "% TODO: 通读本章 → 补术语 → 翻译 → 自校",
            "% 翻译完成后删除上面的 TODO 注释",
            "",
        ]
        content = "\n".join(header) + chapter + "\n"
        target.write_text(content, encoding="utf-8")
        created += 1
        print(f"  + {target.relative_to(project)}")

    print(f"[scaffold] 新建 {created} 个章节骨架")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
