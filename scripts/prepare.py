#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 project.json 生成 LaTeX 元信息，从 glossary/terms.csv 生成术语对照表。

用法：
    python scripts/prepare.py --project projects/my-book
    python scripts/prepare.py --project . --all   # 连 draft 术语一起排入对照表
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

CATEGORY_ORDER = ["人名", "地名", "机构", "作品", "术语", "其他"]

LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    """转义 LaTeX 特殊字符，保留中文与常见标点。"""
    return "".join(LATEX_ESCAPES.get(ch, ch) for ch in text)


def load_project(project: Path) -> dict:
    path = project / "project.json"
    if not path.exists():
        raise SystemExit(f"[错误] 找不到 {path}")
    with path.open(encoding="utf-8-sig") as fh:
        return json.load(fh)


def write_meta(project: Path, meta: dict) -> None:
    fields = [
        ("booktitle", meta.get("title", "")),
        ("booksubtitle", meta.get("subtitle", "")),
        ("booktitleoriginal", meta.get("title_original", "")),
        ("booksubtitleoriginal", meta.get("subtitle_original", "")),
        ("bookauthor", meta.get("author", "")),
        ("bookauthororiginal", meta.get("author_original", "")),
        ("booktranslator", meta.get("translator", "")),
        ("bookseries", meta.get("series", "")),
        ("bookpublisher", meta.get("publisher", "")),
        ("bookoriginalpublisher", meta.get("original_publisher", "")),
        ("bookoriginalyear", str(meta.get("original_year", ""))),
        ("bookyear", str(meta.get("year", ""))),
        ("bookversion", str(meta.get("version", "0.1"))),
        ("bookrights", meta.get("rights", "")),
        ("bookkeywords", meta.get("keywords", "")),
    ]
    lines = ["% 由 scripts/prepare.py 从 project.json 生成，请勿手改"]
    for name, value in fields:
        lines.append(rf"\newcommand{{\{name}}}{{{latex_escape(str(value))}}}")
    out = project / "generated" / "meta.tex"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[prepare] 已生成 {out.relative_to(project)}")


def load_terms(path: Path) -> list[dict]:
    if not path.exists():
        print(f"[prepare] 未找到 {path}，术语表将为空")
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"source", "target", "category", "status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"[错误] {path} 缺少列：{', '.join(sorted(missing))}")
        rows = []
        for lineno, row in enumerate(reader, start=2):
            source = (row.get("source") or "").strip()
            target = (row.get("target") or "").strip()
            if not source and not target:
                continue
            if not source or not target:
                print(f"[警告] {path.name} 第 {lineno} 行缺 source 或 target，已跳过")
                continue
            row = {k: (v or "").strip() for k, v in row.items() if k}
            rows.append(row)
    return rows


def glossary_tex(rows: list[dict], include_draft: bool) -> str:
    rows = [
        r for r in rows
        if (r.get("status", "").lower() != "deprecated")
        and (include_draft or r.get("status", "").lower() == "final")
    ]
    if not rows:
        return (
            "% 由 scripts/prepare.py 从 glossary/terms.csv 生成，请勿手改\n"
            "\\begin{center}\\small 术语表尚未生成（尚无 status=final 的条目）。\\end{center}\n"
        )

    # 分类 → 排序
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.get("category", "其他") or "其他", []).append(row)
    ordered = [c for c in CATEGORY_ORDER if c in grouped]
    ordered += sorted(c for c in grouped if c not in CATEGORY_ORDER)

    out = [
        "% 由 scripts/prepare.py 从 glossary/terms.csv 生成，请勿手改",
        "\\begingroup",
        "\\small",
        "\\renewcommand{\\arraystretch}{1.28}",
        "\\begin{longtable}{@{}"
        "p{0.30\\textwidth}p{0.25\\textwidth}p{0.36\\textwidth}@{}}",
        "\\toprule",
        "\\textbf{原文} & \\textbf{译名} & \\textbf{备注} \\\\",
        "\\midrule",
        "\\endfirsthead",
        "\\toprule",
        "\\textbf{原文} & \\textbf{译名} & \\textbf{备注（续）} \\\\",
        "\\midrule",
        "\\endhead",
        "\\bottomrule",
        "\\endlastfoot",
    ]
    for category in ordered:
        out.append(
            rf"\multicolumn{{3}}{{@{{}}l}}{{\sffamily\bfseries {latex_escape(category)}}} \\[2pt]"
        )
        for row in sorted(grouped[category], key=lambda r: r["source"].casefold()):
            target = row["target"]
            if row.get("status", "").lower() != "final":
                target += "（暂定）"
            cells = [
                latex_escape(row["source"]),
                latex_escape(target),
                latex_escape(row.get("notes", "")),
            ]
            out.append(" & ".join(cells) + r" \\")
        out.append(r"\addlinespace[4pt]")
    out += ["\\end{longtable}", "\\endgroup"]
    return "\n".join(out) + "\n"


def write_chapter_list(project: Path) -> None:
    r"""扫描 chapters/*.tex，生成按自然顺序排列的 \input 列表。"""
    chapters_dir = project / "chapters"
    files = []
    if chapters_dir.exists():
        for path in chapters_dir.glob("*.tex"):
            if path.name.startswith("_"):
                continue
            files.append(path)
    files.sort(key=lambda p: [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", p.name)
    ])
    lines = ["% 由 scripts/prepare.py 自动生成，请勿手改（按文件名自然排序）"]
    for path in files:
        rel = path.relative_to(project).with_suffix("").as_posix()
        lines.append(rf"\input{{{rel}}}")
    out = project / "generated" / "chapters.tex"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[prepare] 已生成 {out.relative_to(project)}（{len(files)} 章）")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="生成 LaTeX 元信息与术语表")
    parser.add_argument("--project", default=".", help="项目目录（默认当前目录）")
    parser.add_argument("--final-only", action="store_true",
                        help="术语表只收录 status=final 的条目（默认含暂定条目）")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    meta = load_project(project)
    write_meta(project, meta)

    terms_path = project / "glossary" / "terms.csv"
    rows = load_terms(terms_path)
    tex = glossary_tex(rows, include_draft=not args.final_only)
    out = project / "generated" / "glossary.tex"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tex, encoding="utf-8")
    write_chapter_list(project)

    final_count = sum(1 for r in rows if r.get("status", "").lower() == "final")
    print(
        f"[prepare] 已生成 {out.relative_to(project)}"
        f"（术语 {len(rows)} 条，其中 final {final_count} 条）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
