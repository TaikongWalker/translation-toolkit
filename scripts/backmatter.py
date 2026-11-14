#!/usr/bin/env python3
"""把 source/backmatter 下的 Markdown 参考文献/索引转换为 LaTeX。

用法：python -I scripts/backmatter.py --project projects/<slug>
仅使用标准库。生成的 .tex 写入 generated/，不要手改。
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


def escape_tex(text: str) -> str:
    text = html.unescape(text)
    repl = {
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
    return "".join(repl.get(ch, ch) for ch in text)


def strip_links(text: str) -> str:
    # [text](url) -> text
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)


def emphasis(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"\\textit{\1}", text)
    return text


def clean_line(line: str) -> str:
    line = strip_links(line.strip())
    line = escape_tex(line)
    return emphasis(line)


def hyphenate_long_words(text: str) -> str:
    """给索引中的超长拉丁词加可断点，避免窄栏溢出。"""
    def repl(m: re.Match) -> str:
        w = m.group(0)
        return r"\-".join(w[i:i + 6] for i in range(0, len(w), 6))
    return re.sub(r"[A-Za-z]{16,}", repl, text)

def convert_bibliography(src: Path) -> str:
    raw = src.read_text(encoding="utf-8")
    paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
    if paras and paras[0].strip("﻿* ").rstrip("*").lower() == "bibliography":
        paras = paras[1:]
    out = ["% 由 scripts/backmatter.py 生成；勿手改。"]
    for p in paras:
        lines = [clean_line(x) for x in p.splitlines() if x.strip()]
        out.append(r"\noindent\hangindent=2em\hangafter=1 " + " ".join(lines) + r"\par")
    return "\n".join(out) + "\n"


def convert_index(src: Path) -> str:
    raw = src.read_text(encoding="utf-8")
    paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
    if paras and paras[0].strip("﻿* ").rstrip("*").lower() == "index":
        paras = paras[1:]
    out = ["% 由 scripts/backmatter.py 生成；勿手改。"]
    for p in paras:
        p = p.replace("*See also*", "另见").replace("*See*", "参见")
        p = re.sub(r"\bSee also\b", "另见", p)
        p = re.sub(r"\bSee\b", "参见", p)
        lines = [clean_line(x) for x in p.splitlines() if x.strip()]
        text = hyphenate_long_words(" ".join(lines))
        # 索引页码/条目之间保留分号与逗号，不额外断行
        out.append(r"\noindent\hangindent=1.2em\hangafter=1 " + text + r"\par\vspace{0.15em}")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    args = ap.parse_args()
    proj = Path(args.project).resolve()
    src_dir = proj / "source" / "backmatter"
    gen = proj / "generated"
    gen.mkdir(exist_ok=True)

    bib = src_dir / "bibliography.md"
    idx = src_dir / "index.md"
    if bib.exists():
        (gen / "bibliography.tex").write_text(convert_bibliography(bib), encoding="utf-8")
        print(f"[backmatter] 参考文献 -> generated/bibliography.tex")
    if idx.exists():
        (gen / "index.tex").write_text(convert_index(idx), encoding="utf-8")
        print(f"[backmatter] 索引 -> generated/index.tex")


if __name__ == "__main__":
    main()
