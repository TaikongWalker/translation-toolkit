#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全书整体核对：逐章比对原文与译文的脚注、节、图、字数及占位残留。

用法：
    python scripts/global_check.py --project projects/my-book

退出码：0 = 全部通过；1 = 有阻断性问题（缺章、占位、数量不符）。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def stats_source(path: Path) -> dict:
    text = read(path)
    headings = [ln for ln in text.splitlines() if ln.startswith("## ")]
    sections = max(0, len(headings) - (1 if any("注释" in h for h in headings) else 0))
    return {
        "footnotes": len(re.findall(r"(?m)^\[\^[^\]]+\]:", text)),
        "figures": len(re.findall(r"!\[[^\]]*\]\(", text)),
        "sections": sections,
    }


def stats_target(path: Path) -> dict:
    text = read(path)
    return {
        "chars": len(CJK.findall(text)),
        "footnotes": len(re.findall(r"\\footnote\s*\{", text)),
        "figures": len(re.findall(r"\\begin\{figure\}", text)),
        # 只统计编号节；原文的加粗小标题可排成 \section*，不计入对照
        "sections": len(re.findall(r"\\section\s*\{", text)),
        "todo": len(re.findall(r"%%\s*TODO|\\todo\{", text)),
        "placeholder": "（待译）" in text,
        "empty": not text.strip(),
    }


def manifest_titles(project: Path) -> dict[str, str]:
    path = project / "source" / "manifest.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {row["file"]: row.get("title", "") for row in csv.DictReader(fh)}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="全书整体核对")
    parser.add_argument("--project", default=".")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    source_dir = project / "source"
    chapters_dir = project / "chapters"

    titles = manifest_titles(project)
    rows = []
    errors = 0
    for md in sorted(source_dir.glob("*.md")):
        if md.name.lower() == "readme.md":
            continue
        stem = md.stem
        if stem == "conclusion":
            target = chapters_dir / "conclusion.tex"
        elif re.fullmatch(r"ch\d+", stem):
            target = chapters_dir / f"{stem}.tex"
        else:
            continue
        if not target.exists():
            rows.append((stem, "缺文件", "-", "-", "-", "-", "-", "-", "ERROR"))
            errors += 1
            continue
        s = stats_source(md)
        t = stats_target(target)
        problems = []
        if t["placeholder"] or t["empty"]:
            problems.append("仍是占位/空文件")
        if s["footnotes"] != t["footnotes"]:
            problems.append(f"脚注 {s['footnotes']}→{t['footnotes']}")
        if s["figures"] != t["figures"]:
            problems.append(f"图 {s['figures']}→{t['figures']}")
        if s["sections"] != t["sections"]:
            problems.append(f"节 {s['sections']}→{t['sections']}")
        if t["todo"]:
            problems.append(f"TODO {t['todo']}")
        status = "OK" if not problems else "ERROR"
        if problems:
            errors += 1
        rows.append((
            stem,
            str(t["chars"]),
            f"{s['sections']}→{t['sections']}",
            f"{s['footnotes']}→{t['footnotes']}",
            f"{s['figures']}→{t['figures']}",
            str(t["todo"]),
            "是" if t["placeholder"] else "否",
            "；".join(problems) if problems else "—",
            status,
        ))

    headers = ["章", "中文字数", "节（原→译）", "脚注（原→译）",
               "图（原→译）", "TODO", "占位", "问题", "状态"]
    widths = [12, 10, 12, 12, 12, 6, 6, 40, 6]
    print("=" * 100)
    print("全书整体核对")
    print("=" * 100)
    print("".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-" * 100)
    for row in rows:
        print("".join(str(c).ljust(w) for c, w in zip(row, widths)))
    print("-" * 100)
    total_chars = sum(int(r[1]) for r in rows if r[1].isdigit())
    print(f"合计中文字数：{total_chars:,}")
    print(f"问题章节：{errors}")
    if errors:
        print("结论：存在数量不符或占位残留，需修正后再编译。")
    else:
        print("结论：各章数量与原文一致，可以进入编译与通读检查。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
