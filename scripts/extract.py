#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一原文抽取：把常见阅读文本格式转为按章拆分的 Markdown 原文档案。

支持：
    .epub .pdf .txt .text .md .markdown
    .html .htm .xhtml .docx .odt .rtf .fb2
    .mobi .azw3 .azw（需安装 Calibre 的 ebook-convert）

输出与 epub_extract.py 一致：source/*.md、source/frontmatter/*.md、
source/manifest.csv。脚注、图片、表格的保留程度取决于输入格式，详见
--list-formats。

用法：
    python scripts/extract.py --input book.pdf --out projects/my-book/source --clean
    python scripts/extract.py --input notes.txt --out source --json
    python scripts/extract.py --list-formats --json

仅用标准库；PDF 优先调用 poppler 的 pdftotext，其次 PyMuPDF；
MOBI/AZW3 调用 Calibre；两者都不是必需依赖。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_FIELDS = ["file", "title", "words", "paragraphs",
                   "figures", "footnotes", "tables", "source_file"]

NATIVE_FORMATS = {
    ".txt": "plain", ".text": "plain",
    ".md": "plain", ".markdown": "plain",
    ".html": "html", ".htm": "html", ".xhtml": "html",
    ".docx": "docx", ".odt": "odt", ".rtf": "rtf", ".fb2": "fb2",
}
OPTIONAL_FORMATS = {
    ".pdf": "pdf",
    ".mobi": "ebook", ".azw3": "ebook", ".azw": "ebook",
}
SUPPORTED_FORMATS = {".epub": "epub", **NATIVE_FORMATS, **OPTIONAL_FORMATS}

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
CHAPTER_RE = re.compile(
    r"^\s*(?:"
    r"第[0-9一二三四五六七八九十百千零〇两]+[章节卷篇部]"
    r"|Chapter\s+[0-9IVXLCDM]+"
    r"|CHAPTER\s+[0-9IVXLCDM]+"
    r"|Part\s+[0-9IVXLCDM]+"
    r"|第[0-9]+章"
    r")\b.*$"
)
STANDALONE_HEADINGS = {
    "前言", "序言", "导言", "引言", "绪论", "结论", "结语", "后记", "译后记",
    "附录", "参考文献", "索引",
    "preface", "introduction", "conclusion", "epilogue", "afterword",
    "appendix", "bibliography", "index", "contents",
}


def is_heading_line(line: str) -> bool:
    stripped = re.sub(r"^#{1,6}\s+", "", line.strip())
    if not stripped:
        return False
    if CHAPTER_RE.match(stripped):
        return True
    return stripped.lower() in STANDALONE_HEADINGS


# ----------------------------------------------------------------------
# 通用工具
# ----------------------------------------------------------------------
def count_words(text: str) -> int:
    """西文词 + 汉字数，作为跨语言可比的“词单位”。"""
    return len(LATIN_RE.findall(text)) + len(CJK_RE.findall(text))


def read_text_auto(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for encoding in ("utf-8", "gb18030", "big5"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_output(out: Path) -> None:
    for pattern in ("*.md", "frontmatter/*.md", "backmatter/*.md"):
        for path in out.glob(pattern):
            path.unlink()
    images = out / "images"
    if images.exists():
        shutil.rmtree(images)
    images.mkdir(parents=True, exist_ok=True)


def paragraphs_of(text: str) -> int:
    return len([b for b in re.split(r"\n\s*\n", text) if b.strip()])


def table_count(text: str) -> int:
    return len(re.findall(r"(?m)^\s*\|?[\s:|-]+\|[\s:|-]*$", text))


# ----------------------------------------------------------------------
# 切分
# ----------------------------------------------------------------------
def split_markdown(text: str, max_chars: int) -> list[dict]:
    lines = text.splitlines()
    h1 = [(i, m.group(1).strip()) for i, line in enumerate(lines)
          if (m := re.match(r"^#\s+(.+)$", line))]
    h2 = [(i, m.group(1).strip()) for i, line in enumerate(lines)
          if (m := re.match(r"^##\s+(.+)$", line))]
    if len(h1) >= 2:
        cuts, level = h1, 1
    elif len(h2) >= 2:
        cuts, level = h2, 2
    elif len(h1) == 1:
        cuts, level = h1, 1
    else:
        return split_plain(text, max_chars)

    segments = []
    first = cuts[0][0]
    preface = "\n".join(lines[:first]).strip()
    if preface:
        segments.append({"title": "", "body": preface, "front": True})
    for idx, (start, title) in enumerate(cuts):
        end = cuts[idx + 1][0] if idx + 1 < len(cuts) else len(lines)
        body = "\n".join(lines[start + 1:end]).strip()
        segments.append({"title": title, "body": body, "front": False})
    return dedupe_toc(segments)


def chapter_key(title: str) -> str:
    """目录页与实际章节的标题可能只共享“第 N 章”或“Chapter N”。"""
    match = re.match(
        r"^\s*(第[0-9一二三四五六七八九十百千零〇两]+[章节卷篇部]"
        r"|Chapter\s+[0-9IVXLCDM]+|Part\s+[0-9IVXLCDM]+)",
        title,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip().lower()
    return re.sub(r"[\s\d.．·…]+$", "", title).strip()


def dedupe_toc(segments: list[dict], threshold: int = 8000) -> list[dict]:
    """处理目录页与页眉造成的重复标题。

    - 编号章节：目录条目短、正文长，保留正文，丢弃短条目；
    - 独立标题（索引、参考文献等）：多为连续页的页眉，合并正文。
    """
    groups: dict[str, list[int]] = {}
    for i, seg in enumerate(segments):
        if seg.get("front"):
            continue
        key = chapter_key(seg.get("title", ""))
        if key:
            groups.setdefault(key, []).append(i)
    drop: set[int] = set()
    numbered = re.compile(r"^(第.+[章节卷篇部]|chapter\s|part\s)")
    for key, idxs in groups.items():
        if len(idxs) < 2:
            continue
        if numbered.match(key):
            keeper = max(idxs, key=lambda i: len(segments[i]["body"]))
            for i in idxs:
                if i != keeper and len(segments[i]["body"]) < threshold:
                    drop.add(i)
        else:
            target = idxs[0]
            bodies = [segments[i]["body"] for i in idxs if segments[i]["body"]]
            segments[target]["body"] = "\n\n".join(bodies)
            for i in idxs[1:]:
                drop.add(i)
    return [seg for i, seg in enumerate(segments) if i not in drop]


def drop_early_toc_entries(segments: list[dict], threshold: int = 5000) -> list[dict]:
    """目录若把“译后记/索引”等独立标题排在前部，会抢占章节序号。"""
    numbered = re.compile(r"^(第.+[章节卷篇部]|chapter\s|part\s)")
    first_numbered = None
    for i, seg in enumerate(segments):
        if seg.get("front"):
            continue
        if numbered.match(chapter_key(seg.get("title", ""))):
            first_numbered = i
            break
    if first_numbered is None:
        return segments
    drop = set()
    for i in range(first_numbered):
        seg = segments[i]
        if seg.get("front"):
            continue
        if (chapter_key(seg.get("title", "")) in STANDALONE_HEADINGS
                and len(seg.get("body", "")) < threshold):
            drop.add(i)
    return [seg for i, seg in enumerate(segments) if i not in drop]


def split_plain(text: str, max_chars: int) -> list[dict]:
    lines = text.splitlines()
    cuts = []
    for i, line in enumerate(lines):
        if is_heading_line(line):
            cuts.append((i, re.sub(r"^#{1,6}\s+", "", line.strip())))
    if len(cuts) >= 2:
        segments = []
        preface = "\n".join(lines[:cuts[0][0]]).strip()
        if preface:
            segments.append({"title": "", "body": preface, "front": True})
        for idx, (start, title) in enumerate(cuts):
            end = cuts[idx + 1][0] if idx + 1 < len(cuts) else len(lines)
            body = "\n".join(lines[start + 1:end]).strip()
            segments.append({"title": title, "body": body, "front": False})
        return drop_early_toc_entries(dedupe_toc(segments))

    # 没有可识别的章节标题：按空行聚合成不超过 max_chars 的块
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    segments, buf, size = [], [], 0
    for block in blocks:
        if buf and size + len(block) > max_chars:
            segments.append({"title": "", "body": "\n\n".join(buf), "front": False})
            buf, size = [], 0
        buf.append(block)
        size += len(block) + 2
    if buf:
        segments.append({"title": "", "body": "\n\n".join(buf), "front": False})
    return segments


def write_segments(segments: list[dict], out: Path, source_name: str,
                   clean: bool) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(parents=True, exist_ok=True)
    if clean:
        clean_output(out)

    rows = []
    chapter_no = 0
    for seg in segments:
        body = normalize_text(seg["body"])
        if not body:
            continue
        if seg.get("front"):
            rel = "frontmatter/front.md"
            title = "Front Matter"
            content = body
        else:
            chapter_no += 1
            rel = f"ch{chapter_no:02d}.md"
            title = seg.get("title") or f"Chunk {chapter_no}"
            heading = title if title.startswith("#") else f"# {title}"
            content = f"{heading}\n\n{body}"
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n", encoding="utf-8")
        rows.append({
            "file": rel.replace("\\", "/"),
            "title": title,
            "words": count_words(content),
            "paragraphs": paragraphs_of(content),
            "figures": content.count("!["),
            "footnotes": len(re.findall(r"(?m)^\[\^[^\]]+\]:", content)),
            "tables": table_count(content),
            "source_file": source_name,
        })
    return rows


# ----------------------------------------------------------------------
# HTML
# ----------------------------------------------------------------------
class MarkdownHTML(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "header", "footer",
             "blockquote", "pre", "table", "tr", "ul", "ol", "figure"}
    HEAD = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading_level = 0
        self.heading_buf: list[str] = []

    def close_heading(self) -> None:
        if self.heading_level:
            title = "".join(self.heading_buf).strip()
            if title:
                self.parts.append("#" * self.heading_level + " " + title + "\n\n")
            self.heading_level = 0
            self.heading_buf = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.HEAD:
            self.close_heading()
            self.parts.append("\n\n")
            self.heading_level = self.HEAD[tag]
            self.heading_buf = []
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "img":
            src = dict(attrs).get("src", "")
            alt = dict(attrs).get("alt", "")
            self.parts.append(f"![{alt}]({src})")
        elif tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.HEAD:
            self.close_heading()
            self.parts.append("\n\n")
        elif tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self.heading_level:
            self.heading_buf.append(data)
        else:
            self.parts.append(data)

    def markdown(self) -> str:
        self.close_heading()
        return normalize_text("".join(self.parts))


def extract_html(path: Path) -> str:
    text, _ = read_text_auto(path)
    parser = MarkdownHTML()
    parser.feed(text)
    return parser.markdown()


# ----------------------------------------------------------------------
# DOCX
# ----------------------------------------------------------------------
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_paragraph(elem: ET.Element) -> tuple[str, str]:
    style = ""
    for node in elem.iter(f"{W}pStyle"):
        style = node.get(f"{W}val", "")
        break
    parts = []
    for node in elem.iter():
        tag = node.tag
        if tag == f"{W}t":
            parts.append(node.text or "")
        elif tag == f"{W}tab":
            parts.append("\t")
        elif tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
        elif tag == f"{W}footnoteReference":
            parts.append(f"[^{node.get(f'{W}id', '')}]")
    return style, "".join(parts).strip()


def extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
        footnotes_xml = None
        if "word/footnotes.xml" in zf.namelist():
            footnotes_xml = zf.read("word/footnotes.xml")

    notes: dict[str, str] = {}
    if footnotes_xml:
        froot = ET.fromstring(footnotes_xml)
        for note in froot.iter(f"{W}footnote"):
            nid = note.get(f"{W}id", "")
            if nid in {"-1", "0", ""}:
                continue
            text = "".join(node.text or "" for node in note.iter(f"{W}t")).strip()
            if text:
                notes[nid] = text

    root = ET.fromstring(xml)
    lines: list[str] = []
    for elem in root.iter(f"{W}p"):
        style, text = docx_paragraph(elem)
        if not text:
            continue
        lower = style.lower()
        if lower.startswith("heading") or lower.startswith("标题"):
            match = re.search(r"(\d+)", style)
            level = int(match.group(1)) if match else 1
            lines.append("#" * min(max(level, 1), 6) + " " + text)
        else:
            lines.append(text)
        # 脚注定义紧随引用它的段落，避免全部堆到末章
        refs = [node.get(f"{W}id", "") for node in elem.iter(f"{W}footnoteReference")]
        for nid in dict.fromkeys(refs):
            if nid in notes:
                lines.append(f"[^{nid}]: {notes[nid]}")
        lines.append("")
    return normalize_text("\n".join(lines))


# ----------------------------------------------------------------------
# ODT
# ----------------------------------------------------------------------
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"


def odt_text(elem: ET.Element) -> str:
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag == f"{TEXT}note":
            parts.append("[^note]")
        elif child.tag == f"{TEXT}s":
            parts.append(" ")
        elif child.tag == f"{TEXT}tab":
            parts.append("\t")
        elif child.tag == f"{TEXT}line-break":
            parts.append("\n")
        else:
            parts.append(odt_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def extract_odt(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("content.xml"))
    body = root.find(f".//{OFFICE}text")
    if body is None:
        body = root
    lines: list[str] = []
    for elem in list(body):
        if elem.tag == f"{TEXT}h":
            level = int(elem.get(f"{TEXT}outline-level", "1") or 1)
            text = odt_text(elem)
            if text:
                lines.extend(["#" * min(max(level, 1), 6) + " " + text, ""])
        elif elem.tag == f"{TEXT}p":
            text = odt_text(elem)
            if text:
                lines.extend([text, ""])
    return normalize_text("\n".join(lines))


# ----------------------------------------------------------------------
# RTF
# ----------------------------------------------------------------------
def extract_rtf(path: Path) -> str:
    raw = path.read_bytes()
    charset = "gb18030" if b"\\ansicpg936" in raw else "cp1252"
    text = raw.decode("latin-1")

    # 丢弃 \* 目标组（字体表、样式表等）
    text = re.sub(r"\{\\\*.*?\}", "", text, flags=re.S)
    text = re.sub(r"\{\\(?:fonttbl|colortbl|stylesheet|info|pict).*?\}", "",
                  text, flags=re.S)
    text = text.replace("\\par", "\n\n").replace("\\line", "\n")
    text = text.replace("\\tab", "\t")
    text = re.sub(r"\\'([0-9a-fA-F]{2})",
                  lambda m: bytes([int(m.group(1), 16)]).decode(charset, "replace"),
                  text)
    text = re.sub(r"\\u(-?\d+)\??",
                  lambda m: chr(int(m.group(1)) % 65536), text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    text = text.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
    text = text.replace("{", "").replace("}", "")
    return normalize_text(text)


# ----------------------------------------------------------------------
# FB2
# ----------------------------------------------------------------------
def extract_fb2(path: Path) -> str:
    root = ET.fromstring(path.read_bytes())
    lines: list[str] = []
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag == "title":
            title = " ".join(t.strip() for t in elem.itertext() if t.strip())
            if title:
                lines.extend(["# " + title, ""])
        elif tag == "p":
            body = "".join(elem.itertext()).strip()
            if body:
                lines.extend([body, ""])
        elif tag == "empty-line":
            lines.append("")
    return normalize_text("\n".join(lines))


# ----------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------
def markitdown_version() -> str:
    try:
        import importlib.metadata as metadata
        return metadata.version("markitdown")
    except Exception:
        return ""


def markitdown_to_text(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise RuntimeError(
            "MarkItDown 不可用：请 pip install markitdown，并用非隔离模式运行"
            "（不要加 -I；-I 会禁用用户 site-packages）。"
        ) from exc
    try:
        return MarkItDown().convert(str(path)).text_content
    except Exception as exc:
        raise RuntimeError(f"MarkItDown 无法转换 {path.name}：{exc}") from exc


def pdf_backends() -> dict:
    pymupdf = (importlib.util.find_spec("pymupdf") is not None
               or importlib.util.find_spec("fitz") is not None)
    return {
        "pdftotext": shutil.which("pdftotext"),
        "pymupdf": pymupdf,
        "markitdown": markitdown_version(),
    }


def extract_pdf(path: Path) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    backends = pdf_backends()
    if backends["pdftotext"]:
        proc = subprocess.run(
            [backends["pdftotext"], "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
        )
        if proc.returncode == 0:
            text = proc.stdout.decode("utf-8", "replace")
            if text.strip():
                warnings.append("PDF 抽取不保留脚注编号与图片，需对照原书核对。")
                return text, "pdftotext", warnings
    if backends["pymupdf"]:
        try:
            import pymupdf  # type: ignore
        except ImportError:
            import fitz as pymupdf  # type: ignore
        doc = pymupdf.open(str(path))
        text = "\n\n".join(page.get_text("text") for page in doc)
        if text.strip():
            warnings.append("PDF 抽取不保留脚注编号与图片，需对照原书核对。")
            return text, "pymupdf", warnings
        raise RuntimeError("PDF 没有可抽取的文本，疑似扫描版；请先 OCR 或提供文本版。")
    raise RuntimeError(
        "没有可用的 PDF 后端：请安装 poppler（pdftotext）或 PyMuPDF"
        "（pip install pymupdf），或先把 PDF 转为 TXT/DOCX。"
    )


# ----------------------------------------------------------------------
# EPUB / MOBI
# ----------------------------------------------------------------------
def read_manifest(out: Path) -> list[dict]:
    path = out / "manifest.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = [row for row in csv.DictReader(fh)]
    for row in rows:
        for field in ("words", "paragraphs", "figures", "footnotes", "tables"):
            try:
                row[field] = int(row.get(field) or 0)
            except (TypeError, ValueError):
                row[field] = 0
    return rows


def extract_epub(path: Path, out: Path, clean: bool) -> tuple[list[dict], str]:
    cmd = [sys.executable, "-I", str(SCRIPT_DIR / "epub_extract.py"),
           "--epub", str(path), "--out", str(out)]
    if clean:
        cmd.append("--clean")
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip() \
            or proc.stdout.decode("utf-8", "replace").strip()
        raise RuntimeError(f"EPUB 抽取失败：{message[-800:]}")
    return read_manifest(out), "epub"


def extract_ebook(path: Path, out: Path, clean: bool) -> tuple[list[dict], str]:
    converter = shutil.which("ebook-convert")
    if not converter:
        raise RuntimeError(
            "MOBI/AZW3 需要 Calibre 的 ebook-convert；请安装 Calibre，"
            "或先用其转换为 EPUB/TXT 再抽取。"
        )
    with tempfile.TemporaryDirectory() as tmp:
        epub = Path(tmp) / "converted.epub"
        proc = subprocess.run([converter, str(path), str(epub)],
                              capture_output=True)
        if proc.returncode != 0 or not epub.exists():
            message = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"ebook-convert 失败：{message[-800:]}")
        return extract_epub(epub, out, clean)


# ----------------------------------------------------------------------
# 调度
# ----------------------------------------------------------------------
def format_info() -> list[dict]:
    backends = pdf_backends()
    ebook = shutil.which("ebook-convert")
    rows = []
    for ext, kind in sorted(SUPPORTED_FORMATS.items()):
        if kind == "epub":
            available, notes = True, "原生支持；保留脚注、图片、表格"
        elif kind in NATIVE_FORMATS.values():
            available, notes = True, {
                "plain": "原生支持；按 Markdown/章节标题或空行切分",
                "html": "原生支持；保留标题与段落，图片仅保留链接",
                "docx": "原生支持；保留标题样式与脚注，表格按段落展开",
                "odt": "原生支持；保留标题层级与段落，脚注转为引用标记",
                "rtf": "原生支持（基础）；复杂排版与图片不保留",
                "fb2": "原生支持；按 title 切分章节",
            }[kind]
        elif kind == "pdf":
            ok = bool(backends["pdftotext"] or backends["pymupdf"]
                      or backends["markitdown"])
            available = ok
            notes = "优先 MarkItDown；否则 pdftotext / PyMuPDF；不保留脚注编号与图片"
            if not ok:
                notes += "；当前后端均不可用"
        else:
            available = bool(ebook)
            notes = "需要 Calibre ebook-convert"
            if not ebook:
                notes += "；当前不可用"
        rows.append({"extension": ext, "kind": kind,
                     "available": available, "notes": notes})
    return rows


def extract(input_path: Path, out: Path, clean: bool,
            max_chars: int, engine: str = "auto") -> dict:
    ext = input_path.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise RuntimeError(
            f"不支持 {ext or '（无扩展名）'}。支持："
            + " ".join(sorted(SUPPORTED_FORMATS))
            + "；其他格式可先转换为 TXT/DOCX/EPUB。"
        )

    kind = SUPPORTED_FORMATS[ext]
    warnings: list[str] = []
    if kind == "epub" and engine != "markitdown":
        rows, backend = extract_epub(input_path, out, clean)
        return {"rows": rows, "backend": backend, "warnings": warnings}
    if kind == "ebook":
        rows, backend = extract_ebook(input_path, out, clean)
        return {"rows": rows, "backend": backend, "warnings": warnings}

    md_version = markitdown_version()
    # auto：PDF / HTML 优先 MarkItDown；结构化格式（EPUB/DOCX）仍用内置后端，
    # 因为后者能保留脚注位置与章节结构。--engine markitdown 可强制使用。
    use_markitdown = engine == "markitdown" or (
        engine == "auto" and kind in {"pdf", "html"} and bool(md_version)
    )

    text = ""
    backend = ""
    if use_markitdown:
        try:
            text = markitdown_to_text(input_path)
            backend = f"markitdown:{md_version}"
            warnings.append(
                "MarkItDown 输出不保证脚注编号与图片结构；需要逐注对照时，"
                "可用 --engine native 对结构化格式重新抽取。"
            )
        except RuntimeError:
            if engine == "markitdown":
                raise
            use_markitdown = False

    if not use_markitdown:
        if kind == "pdf":
            text, backend, warnings = extract_pdf(input_path)
        elif kind == "html":
            text, backend = extract_html(input_path), "html"
        elif kind == "docx":
            text, backend = extract_docx(input_path), "docx"
        elif kind == "odt":
            text, backend = extract_odt(input_path), "odt"
        elif kind == "rtf":
            text, backend = extract_rtf(input_path), "rtf"
        elif kind == "fb2":
            text, backend = extract_fb2(input_path), "fb2"
        else:
            text, encoding = read_text_auto(input_path)
            backend = f"plain:{encoding}"
            if input_path.suffix.lower() in {".md", ".markdown"}:
                warnings.append("Markdown 输入按 # / ## 标题切分。")

    text = normalize_text(text)
    if not text:
        raise RuntimeError(f"{input_path.name} 没有可抽取的文本。")
    structured = (backend in {"html", "docx", "odt", "fb2"}
                  or backend.startswith("markitdown")
                  or input_path.suffix.lower() in {".md", ".markdown"})
    if input_path.suffix.lower() == ".pdf":
        # PDF 转换出的 # 标题常包含目录页与页眉，按纯文本规则切分更稳
        structured = False
    segments = (split_markdown(text, max_chars) if structured
                else split_plain(text, max_chars))
    rows = write_segments(segments, out, input_path.name, clean)
    if not rows:
        raise RuntimeError("抽取后没有生成任何章节。")
    return {"rows": rows, "backend": backend, "warnings": warnings}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="统一原文抽取（多格式）")
    parser.add_argument("--input", help="输入文件")
    parser.add_argument("--out", help="输出目录（通常是项目/source）")
    parser.add_argument("--clean", action="store_true",
                        help="先清空输出目录中的 md 与 images")
    parser.add_argument("--max-chars", type=int, default=12000,
                        help="无标题文本的切块大小（默认 12000 字符）")
    parser.add_argument("--engine", choices=["auto", "markitdown", "native"],
                        default="auto",
                        help="auto（默认）、markitdown 或 native")
    parser.add_argument("--list-formats", action="store_true",
                        help="列出支持的格式与后端可用性")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读的 JSON（stdout 只有 JSON）")
    args = parser.parse_args()

    if args.list_formats:
        formats = format_info()
        md_version = markitdown_version()
        payload = {
            "ok": True,
            "exit_code": 0,
            "engines": {
                "markitdown": md_version or "",
                "pdftotext": shutil.which("pdftotext") or "",
                "pymupdf": pdf_backends()["pymupdf"],
                "ebook_convert": shutil.which("ebook-convert") or "",
            },
            "formats": formats,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"MarkItDown：{md_version or '未安装（非隔离模式下可用）'}")
            print(f"{'扩展名':<10}{'可用':<6}说明")
            for row in formats:
                mark = "是" if row["available"] else "否"
                print(f"{row['extension']:<10}{mark:<6}{row['notes']}")
        return 0

    if not args.input or not args.out:
        parser.error("--input 与 --out 为必填（或使用 --list-formats）")

    input_path = Path(args.input).resolve()
    out = Path(args.out).resolve()
    if not input_path.exists():
        if args.json:
            print(json.dumps({"ok": False, "exit_code": 1,
                              "error": f"找不到 {input_path}"},
                             ensure_ascii=False, indent=2))
        else:
            print(f"[错误] 找不到 {input_path}")
        return 1

    try:
        result = extract(input_path, out, args.clean, args.max_chars,
                         args.engine)
    except (RuntimeError, OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "exit_code": 1, "error": str(exc)},
                             ensure_ascii=False, indent=2))
        else:
            print(f"[错误] {exc}")
        return 1

    rows = result["rows"]
    total_words = sum(int(r.get("words", 0) or 0) for r in rows)
    payload = {
        "ok": True,
        "exit_code": 0,
        "input": str(input_path),
        "format": input_path.suffix.lower().lstrip("."),
        "backend": result["backend"],
        "output": str(out),
        "manifest": str(out / "manifest.csv"),
        "files": len(rows),
        "total_words": total_words,
        "warnings": result["warnings"],
        "units": rows,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"[extract] {input_path.name} → {out}")
    print(f"  后端：{result['backend']}")
    for row in rows:
        print(f"  {row['file']:38} {row['title'][:40]:40} "
              f"{int(row['words']):>7} 词  {int(row['footnotes']):>3} 注")
    for warning in result["warnings"]:
        print(f"  [注意] {warning}")
    print(f"完成：{len(rows)} 个文件，{total_words} 词单位；清单 {out / 'manifest.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
