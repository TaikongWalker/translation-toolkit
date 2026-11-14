#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 LaTeX 书稿导出为 PDF 之外的格式（通过 Pandoc）。

支持：md / html / epub / docx / all。
PDF 仍由 build.ps1 生成；本脚本只处理其他格式。

做法：把 frontmatter、chapters、backmatter 拼成一个 LaTeX 片段，
替换项目自定义宏（\\zhu、\\term、\\orig、\\todo 等），再用 Pandoc
从 LaTeX 读取并输出目标格式。图片通过 --resource-path 查找。

用法：
    python scripts/export.py --project . --format md
    python scripts/export.py --project . --format epub --json
    python scripts/export.py --project . --format all
    python scripts/export.py --check

退出码：0 = 成功；1 = 缺 Pandoc、文件或转换失败。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FORMATS = {
    "md": ("gfm", ".md"),
    "html": ("html5", ".html"),
    "epub": ("epub3", ".epub"),
    "docx": ("docx", ".docx"),
}
CJK_DIGITS = "零一二三四五六七八九十"


def find_pandoc() -> str:
    found = shutil.which("pandoc")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Pandoc" / "pandoc.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Pandoc" / "pandoc.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return ""


def take_group(text: str, index: int) -> tuple[str, int]:
    """text[index] == '{'；返回 (内容, 右括号之后的位置)。"""
    depth = 0
    i = index
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[index + 1:i], i + 1
        i += 1
    return text[index + 1:], len(text)


def replace_macro(text: str, name: str, fn) -> str:
    """替换单参数宏；支持嵌套花括号与可选方括号。"""
    out, i, pat = [], 0, "\\" + name
    while True:
        j = text.find(pat, i)
        if j < 0:
            out.append(text[i:])
            break
        k = j + len(pat)
        if k < len(text) and (text[k].isalpha() or text[k] == "@"):
            out.append(text[i:k])
            i = k
            continue
        out.append(text[i:j])
        if k < len(text) and text[k] == "[":
            close = text.find("]", k)
            k = close + 1 if close >= 0 else k
        if k < len(text) and text[k] == "{":
            arg, k = take_group(text, k)
            out.append(fn(arg))
        else:
            out.append(text[j:k])
        i = k
    return "".join(out)


def replace_two_arg(text: str, name: str, fn) -> str:
    out, i, pat = [], 0, "\\" + name
    while True:
        j = text.find(pat, i)
        if j < 0:
            out.append(text[i:])
            break
        k = j + len(pat)
        if k < len(text) and (text[k].isalpha() or text[k] == "@"):
            out.append(text[i:k])
            i = k
            continue
        out.append(text[i:j])
        if k < len(text) and text[k] == "[":
            close = text.find("]", k)
            k = close + 1 if close >= 0 else k
        if k < len(text) and text[k] == "{":
            first, k = take_group(text, k)
        else:
            out.append(text[j:k])
            i = k
            continue
        while k < len(text) and text[k] in " \t":
            k += 1
        if k < len(text) and text[k] == "{":
            second, k = take_group(text, k)
            out.append(fn(first, second))
        else:
            out.append(text[j:k])
        i = k
    return "".join(out)


def replace_n_args(text: str, name: str, count: int, fn=lambda args: "") -> str:
    out, i, pat = [], 0, "\\" + name
    while True:
        j = text.find(pat, i)
        if j < 0:
            out.append(text[i:])
            break
        k = j + len(pat)
        if k < len(text) and (text[k].isalpha() or text[k] == "@"):
            out.append(text[i:k])
            i = k
            continue
        out.append(text[i:j])
        if k < len(text) and text[k] == "[":
            close = text.find("]", k)
            k = close + 1 if close >= 0 else k
        args = []
        while len(args) < count and k < len(text) and text[k] in " \t\n":
            k += 1
        while len(args) < count and k < len(text) and text[k] == "{":
            arg, k = take_group(text, k)
            args.append(arg)
            while k < len(text) and text[k] in " \t\n":
                k += 1
        if len(args) == count:
            out.append(fn(args))
        else:
            out.append(text[j:k])
        i = k
    return "".join(out)


def strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        cut = None
        for match in re.finditer(r"(?<!\\)%", line):
            cut = match.start()
            break
        lines.append(line if cut is None else line[:cut])
    return "\n".join(lines)


def chapter_labels(project: Path, files: list[Path]) -> dict[str, str]:
    labels: dict[str, str] = {}
    counter = 0
    for path in files:
        text = strip_comments(path.read_text(encoding="utf-8-sig", errors="replace"))
        for match in re.finditer(
            r"\\(chapter\*?)\{([^{}]*)\}(?:\s*\\label\{([^{}]*)\})?", text
        ):
            star, title, label = match.group(1), match.group(2), match.group(3)
            if star == "chapter*":
                name = title
            else:
                counter += 1
                name = CJK_DIGITS[counter] if counter < len(CJK_DIGITS) else str(counter)
            if label:
                labels[label] = name
    return labels


def convert_fragment(text: str, labels: dict[str, str], meta: dict) -> str:
    text = strip_comments(text)
    for key in sorted(("booktitle", "booksubtitle", "bookauthor", "bookyear",
                       "booktitleoriginal", "booksubtitleoriginal",
                       "bookauthororiginal"), key=len, reverse=True):
        value = meta.get(key, "")
        text = text.replace("\\" + key, value or "")

    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    text = re.sub(r"\\ref\{([^{}]*)\}",
                  lambda m: labels.get(m.group(1), "?"), text)
    text = replace_n_args(text, "addcontentsline", 3)
    text = replace_n_args(text, "markboth", 2)
    text = replace_n_args(text, "setcounter", 2)
    text = replace_n_args(text, "thispagestyle", 1)
    text = replace_n_args(text, "vspace", 1)
    text = replace_n_args(text, "hspace", 1)
    text = text.replace("\\begin{flushleft}", "").replace("\\end{flushleft}", "")

    def chapterquote(match: re.Match) -> str:
        source, body = match.group(1), match.group(2)
        tail = f"\\par\\hfill ——{source}" if source else ""
        return "\\begin{quote}\\itshape " + body + tail + "\\end{quote}"

    text = re.sub(
        r"\\begin\{chapterquote\}\{([^{}]*)\}(.*?)\\end\{chapterquote\}",
        chapterquote, text, flags=re.S)

    text = replace_macro(text, "zhu", lambda a: "\\footnote{译者注：" + a + "}")
    text = replace_two_arg(text, "term", lambda a, b: f"{a}（\\textit{{{b}}}）")
    for name in ("orig", "bookorig", "textit", "emph"):
        text = replace_macro(text, name, lambda a: "\\textit{" + a + "}")
    for name in ("textbf", "bfseries"):
        text = replace_macro(text, name, lambda a: "\\textbf{" + a + "}")
    text = replace_macro(text, "todo", lambda a: "\\textbf{TODO：" + a + "}")
    text = replace_macro(text, "figsource", lambda a: "\\par\\emph{" + a + "}")
    text = replace_macro(text, "mbox", lambda a: a)

    text = text.replace("\\par", "\n\n")
    text = text.replace("\\hfill", " ")
    text = text.replace("\\cleardoublepage", "")
    text = text.replace("\\newpage", "")
    text = text.replace("\\hrule", "")
    text = text.replace("\\\\", "\\newline ")
    return text


def render_tikz(text: str, unit: str, workdir: Path) -> str:
    """把 tikzpicture 编译为 PNG，替换为 includegraphics，供 Pandoc 使用。"""
    start_tag = "\\begin{tikzpicture}"
    end_tag = "\\end{tikzpicture}"
    index = 0
    while True:
        start = text.find(start_tag, index)
        if start < 0:
            break
        end = text.find(end_tag, start)
        if end < 0:
            break
        end += len(end_tag)
        code = text[start:end]
        index = end
        xelatex = shutil.which("xelatex")
        if not xelatex:
            continue
        workdir.mkdir(parents=True, exist_ok=True)
        name = f"{unit}-tikz-{index}"
        tex_path = workdir / f"{name}.tex"
        tex_path.write_text(
            "\\documentclass[UTF8,fontset=none,border=4pt]{standalone}\n"
            "\\usepackage{ctex}\n\\setCJKmainfont{SimSun}\n"
            "\\usepackage{tikz}\n\\usetikzlibrary{positioning}\n"
            "\\begin{document}\n" + code + "\n\\end{document}\n",
            encoding="utf-8",
        )
        for _ in range(2):
            subprocess.run([xelatex, "-interaction=nonstopmode", "-halt-on-error",
                            tex_path.name], cwd=workdir,
                           capture_output=True)
        pdf = workdir / f"{name}.pdf"
        png = workdir / f"{name}.png"
        if not pdf.exists():
            continue
        try:
            import pymupdf
            doc = pymupdf.open(str(pdf))
            pix = doc[0].get_pixmap(dpi=200)
            pix.save(str(png))
            doc.close()
        except Exception:
            continue
        if png.exists():
            rel = f"figures/{name}.png"
            text = (text[:start]
                    + f"\\includegraphics[width=0.9\\textwidth]{{{rel}}}"
                    + text[end:])
    return text


def collect_files(project: Path, include_backmatter: bool) -> list[Path]:
    files: list[Path] = []
    for name in ("frontmatter/preface.tex", "frontmatter/acknowledgments.tex",
                 "frontmatter/dedication.tex"):
        path = project / name
        if path.exists():
            files.append(path)
    chapters = project / "generated" / "chapters.tex"
    if chapters.exists():
        for rel in re.findall(r"\\input\{([^{}]*)\}",
                              chapters.read_text(encoding="utf-8-sig")):
            path = project / (rel + ".tex")
            if path.exists():
                files.append(path)
    for name in ("backmatter/afterword.tex",):
        path = project / name
        if path.exists():
            files.append(path)
    if include_backmatter:
        for name in ("backmatter/glossary.tex", "backmatter/bibliography.tex",
                     "backmatter/index.tex"):
            path = project / name
            if path.exists():
                files.append(path)
    return files


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="导出 PDF 之外的格式（Pandoc）")
    parser.add_argument("--project", default=".")
    parser.add_argument("--format", default="md",
                        choices=[*FORMATS, "all"])
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--include-backmatter", action="store_true",
                        help="连同术语表、参考文献、索引一起导出")
    parser.add_argument("--check", action="store_true",
                        help="只检查 Pandoc 是否可用")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    pandoc = find_pandoc()
    if args.check or not pandoc:
        result = {"ok": bool(pandoc), "exit_code": 0 if pandoc else 1,
                  "pandoc": pandoc, "formats": list(FORMATS)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Pandoc：{pandoc or '未找到'}")
        return result["exit_code"]

    project = Path(args.project).resolve()
    if not (project / "project.json").exists():
        print(f"[错误] {project} 不是项目目录（缺 project.json）")
        return 1
    meta_raw = json.loads((project / "project.json").read_text(encoding="utf-8-sig"))
    meta = {
        "booktitle": meta_raw.get("title", ""),
        "booksubtitle": meta_raw.get("subtitle", ""),
        "bookauthor": meta_raw.get("author", ""),
        "bookyear": meta_raw.get("year", ""),
        "booktitleoriginal": meta_raw.get("title_original", ""),
        "booksubtitleoriginal": meta_raw.get("subtitle_original", ""),
        "bookauthororiginal": meta_raw.get("author_original", ""),
    }
    files = collect_files(project, args.include_backmatter)
    if not files:
        print("[错误] 没有可导出的章节文件")
        return 1

    labels = chapter_labels(project, files)
    build_dir = project / "build" / "export"
    build_dir.mkdir(parents=True, exist_ok=True)
    fragments = []
    chapter_no = 0
    for path in files:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        raw = render_tikz(raw, path.stem, build_dir / "figures")
        fragment = convert_fragment(raw, labels, meta)

        def number(match: re.Match) -> str:
            nonlocal chapter_no
            chapter_no += 1
            name = (CJK_DIGITS[chapter_no]
                    if chapter_no < len(CJK_DIGITS) else str(chapter_no))
            return f"\\chapter{{第{name}章 {match.group(1)}}}"

        fragment = re.sub(r"\\chapter\{([^{}]*)\}", number, fragment)
        fragments.append(fragment)
    combined = "\n\n".join(fragments)

    build_dir = project / "build" / "export"
    build_dir.mkdir(parents=True, exist_ok=True)
    combined_path = build_dir / "book.tex"
    combined_path.write_text(combined, encoding="utf-8")

    slug = meta_raw.get("slug", project.name)
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    elif project.parent.name == "projects":
        # 工作区结构：<workspace>/projects/<slug> → <workspace>/成品/<slug>
        out_dir = project.parent.parent / "成品" / slug
    else:
        out_dir = project / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    resource = os.pathsep.join([
        str(project), str(project / "figures"), str(project / "source" / "images"),
        str(build_dir),
    ])
    targets = list(FORMATS) if args.format == "all" else [args.format]

    results = []
    for fmt in targets:
        writer, ext = FORMATS[fmt]
        output = out_dir / f"{slug}{ext}"
        cmd = [pandoc, str(combined_path), "-f", "latex", "-t", writer,
               "-o", str(output), "--resource-path", resource,
               "--metadata", f"title={meta['booktitle']}",
               "--metadata", f"author={meta['bookauthor']}",
               "--metadata", "lang=zh-CN"]
        if fmt in {"html", "epub"}:
            cmd += ["--toc", "--toc-depth=2"]
        if fmt == "html":
            cmd += ["--standalone", "--embed-resources"]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        results.append({
            "format": fmt,
            "output": str(output) if output.exists() else "",
            "ok": proc.returncode == 0 and output.exists(),
            "error": (proc.stderr or proc.stdout).strip()[-800:] if proc.returncode else "",
        })

    ok = all(r["ok"] for r in results)
    payload = {"ok": ok, "exit_code": 0 if ok else 1,
               "combined": str(combined_path), "results": results}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Pandoc：{pandoc}")
        for row in results:
            status = "OK" if row["ok"] else "FAIL"
            print(f"  [{status}] {row['format']:<5} {row['output'] or row['error']}")
    return payload["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
