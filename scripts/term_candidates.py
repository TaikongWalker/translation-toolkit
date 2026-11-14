#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从原文 Markdown 提取术语候选，输出 glossary/candidates.csv。

候选只是起点，不是术语表。请人工筛选、查证、定名后移入 glossary/terms.csv。

用法：
    python scripts/term_candidates.py --project projects/my-book
    python scripts/term_candidates.py --project . --min-count 3 --limit 400
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

# 句首常见词，避免把普通句子开头当成专名
STOP_STARTS = {
    "The", "This", "That", "These", "Those", "A", "An", "In", "On", "At",
    "By", "For", "From", "With", "As", "But", "And", "Or", "If", "When",
    "While", "Although", "However", "Thus", "Therefore", "Because", "Since",
    "It", "Its", "He", "She", "They", "We", "I", "You", "His", "Her",
    "Their", "Our", "My", "Your", "There", "Here", "What", "Which", "Who",
    "Why", "How", "Where", "Chapter", "Figure", "Table", "Part", "Note",
    "See", "Yet", "Still", "Even", "Only", "Not", "No", "All", "Some",
    "Many", "Most", "Such", "Both", "Each", "Every", "One", "Two", "Three",
}

# 常见普通词，避免“Soviet Union”之外的泛化搭配被过度收录
STOP_PHRASES = {
    "Soviet", "Russian", "American", "European", "Western", "New", "Old",
    "First", "Second", "Third", "Last", "Great", "Little", "Good", "Bad",
}


def read_sources(project: Path) -> list[Path]:
    source = project / "source"
    files = sorted(source.glob("*.md")) + sorted((source / "frontmatter").glob("*.md"))
    return [f for f in files if f.name.lower() != "readme.md"]


def add(counter: Counter, examples: dict, phrase: str, context: str) -> None:
    phrase = re.sub(r"\s+", " ", phrase).strip(" .,;:()[]“”‘’\"'")
    if not phrase:
        return
    if len(phrase) < 3 or len(phrase) > 60:
        return
    counter[phrase] += 1
    examples.setdefault(phrase, context.strip()[:120])


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="提取术语候选")
    parser.add_argument("--project", default=".")
    parser.add_argument("--min-count", type=int, default=2)
    parser.add_argument("--limit", type=int, default=400)
    args = parser.parse_args()

    project = Path(args.project).resolve()
    files = read_sources(project)
    if not files:
        print(f"[错误] 在 {project / 'source'} 找不到 *.md")
        return 1

    counts: Counter = Counter()
    examples: dict[str, str] = {}
    categories: dict[str, str] = {}

    proper = re.compile(
        r"\b([A-Z][A-Za-z'’\-]+(?:\s+(?:of|the|and|de|van|von|der)?\s*"
        r"[A-Z][A-Za-z'’\-]+){1,3})\b"
    )
    italic = re.compile(r"\*([A-Za-z][A-Za-z'’\- ]{1,45})\*")
    acronym = re.compile(r"\b([A-Z]{2,6})\b")

    for path in files:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        # 只保留正文，去掉脚注定义（注释里专名也会出现，但先避免噪声）
        body = re.sub(r"(?m)^\[\^[^\]]+\]:.*$", "", text)
        for m in proper.finditer(body):
            phrase = m.group(1)
            first = phrase.split()[0]
            if first in STOP_STARTS:
                continue
            if phrase in STOP_PHRASES:
                continue
            add(counts, examples, phrase, body[max(0, m.start() - 50):m.end() + 50])
            categories.setdefault(phrase, "待定")
        for m in italic.finditer(body):
            phrase = m.group(1).strip()
            if len(phrase.split()) > 5:
                continue
            # 斜体多为外来词/术语，也可能只是强调；交给人工判断
            add(counts, examples, phrase, body[max(0, m.start() - 50):m.end() + 50])
            categories.setdefault(phrase, "术语")
        for m in acronym.finditer(body):
            phrase = m.group(1)
            if phrase in {"THE", "AND", "FOR", "NOT", "BUT"}:
                continue
            add(counts, examples, phrase, body[max(0, m.start() - 50):m.end() + 50])
            categories.setdefault(phrase, "待定")

    selected = [
        (phrase, count)
        for phrase, count in counts.most_common()
        if count >= args.min_count
    ][: args.limit]

    out = project / "glossary" / "candidates.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "source", "target", "category", "status", "notes",
            "forbidden", "count", "example",
        ])
        for phrase, count in selected:
            writer.writerow([
                phrase, "", categories.get(phrase, "待定"), "draft", "",
                "", count, examples.get(phrase, ""),
            ])

    print(f"[terms] 已生成 {out.relative_to(project)}：{len(selected)} 个候选")
    print("\n高频候选（前 20）：")
    for phrase, count in selected[:20]:
        print(f"  {count:>4}  {phrase}")
    print("\n下一步：人工筛选 → 查证译名 → 填入 glossary/terms.csv（status=final）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
