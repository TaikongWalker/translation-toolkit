#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 EPUB 抽取为按章拆分的 Markdown 原文档案。

保留：章节标题、正文段落、斜体/粗体、脚注（章末 [^n]）、插图（images/）、
图注、表格（简单表格转 Markdown）、章节目录标题。
不保留：分页锚点、纯装饰元素、原始 CSS。

用法：
    python scripts/epub_extract.py --epub book.epub --out projects/my-book/source
    python scripts/epub_extract.py --epub book.epub --out source --clean
"""

from __future__ import annotations

import argparse
import csv
import html.entities
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


# ----------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------
def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_entities(xml: str) -> str:
    """把 HTML 命名实体改为数字实体，保留 XML 五个预定义实体。"""
    keep = {"amp", "lt", "gt", "quot", "apos"}

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name in keep:
            return match.group(0)
        codepoint = html.entities.name2codepoint.get(name)
        return f"&#{codepoint};" if codepoint else match.group(0)

    return re.sub(r"&([A-Za-z][A-Za-z0-9]+);", repl, xml)


def normalize_space(text: str | None) -> str:
    """折叠空白但保留 <br/> 产生的换行，避免吃掉词与词之间的空格。"""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text


def clean_text(text: str | None) -> str:
    return normalize_space(text).strip()


def plain_text(el: ET.Element) -> str:
    return clean_text("".join(el.itertext()))


def digits(value: str) -> str:
    found = re.search(r"(\d+|[A-Za-z]+)", value or "")
    return found.group(1) if found else ""


# ----------------------------------------------------------------------
# XHTML → Markdown
# ----------------------------------------------------------------------
class ChapterConverter:
    def __init__(self, image_names: set[str]):
        self.blocks: list[str] = []
        self.footnotes: dict[str, str] = {}
        self.figures = 0
        self.tables = 0
        self.paragraphs = 0
        self.image_names = image_names
        self.pending_image: tuple[str, str] | None = None
        self.blockquote: list[str] = []
        self.chapter_label = ""
        self.body_text: list[str] = []

    # ---------- 行内 ----------
    def inline(self, el: ET.Element) -> str:
        parts = [normalize_space(el.text)]
        for child in el:
            tag = local(child.tag)
            if tag == "a":
                href = child.get("href", "")
                text = clean_text("".join(child.itertext()))
                if href.startswith("#fn") or child.get("id", "").startswith("fns"):
                    parts.append(f"[^{digits(text) or digits(href)}]")
                elif href.startswith("#page_") or child.get("id", "").startswith("page_"):
                    pass
                elif href.startswith("#"):
                    parts.append(text)
                elif href:
                    parts.append(f"[{text}]({href})")
                else:
                    parts.append(text)
            elif tag in {"i", "em"}:
                parts.append(f"*{clean_text(''.join(child.itertext()))}*")
            elif tag in {"b", "strong"}:
                parts.append(f"**{clean_text(''.join(child.itertext()))}**")
            elif tag == "br":
                parts.append("\n")
            elif tag == "sup":
                parts.append(self.inline(child))
            elif tag == "img":
                src = child.get("src", "")
                if src:
                    parts.append(f"![]({self.image_path(src)})")
            elif tag in {"small", "span", "code", "tt"}:
                parts.append(normalize_space("".join(child.itertext())))
            else:
                parts.append(self.inline(child))
            parts.append(normalize_space(child.tail))
        return "".join(parts).strip()

    # ---------- 图片 ----------
    @staticmethod
    def image_path(src: str) -> str:
        return f"images/{Path(src).name}"

    def flush_image(self) -> None:
        if not self.pending_image:
            return
        src, fig_id = self.pending_image
        alt = fig_id or Path(src).stem
        self.blocks.append(f"![{alt}]({self.image_path(src)})")
        self.figures += 1
        self.pending_image = None

    def flush_quote(self) -> None:
        if not self.blockquote:
            return
        self.blocks.append("\n>\n".join(f"> {q}" for q in self.blockquote))
        self.blockquote = []

    # ---------- 块级 ----------
    def add_block(self, text: str) -> None:
        self.flush_quote()
        self.flush_image()
        if text.strip():
            self.blocks.append(text.strip())
            self.body_text.append(text.strip())
            self.paragraphs += 1

    def process(self, el: ET.Element) -> None:
        tag = local(el.tag)
        cls = (el.get("class") or "").lower()

        if tag in {"head", "style", "script"}:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = plain_text(el)
            if text:
                level = int(tag[1])
                self.add_block("#" * level + " " + text)
            return
        if tag == "table":
            self.flush_quote()
            self.flush_image()
            table = self.convert_table(el)
            if table:
                self.blocks.append(table)
                self.tables += 1
            return
        if tag == "img":
            self.flush_quote()
            self.flush_image()
            src = el.get("src", "")
            if src:
                self.pending_image = (src, el.get("id", ""))
            return
        if tag == "p":
            self.handle_paragraph(el, cls)
            return
        if tag == "blockquote":
            self.flush_quote()
            for child in el:
                if local(child.tag) == "p":
                    text = self.inline(child)
                    if text:
                        self.blockquote.append(text)
                else:
                    self.process(child)
            self.flush_quote()
            return
        if tag in {"div", "section", "article", "body", "main", "figure"}:
            for child in el:
                self.process(child)
            return
        # 其他未知块：尝试按段落处理
        if len(el):
            for child in el:
                self.process(child)
        else:
            text = plain_text(el)
            if text:
                self.add_block(text)

    def handle_paragraph(self, el: ET.Element, cls: str) -> None:
        # 脚注定义
        if "fn" in cls or cls in {"notes", "footnote"}:
            text = self.inline(el)
            match = re.match(r"^\[\^([^\]]+)\]\s*(.*)$", text, re.S)
            if match:
                label, body = match.group(1), match.group(2).strip()
                self.footnotes[label] = body
                return
            if text:
                self.footnotes[str(len(self.footnotes) + 1)] = text
            return

        if cls in {"border", "pagebreak"}:
            return

        # 图片：延后到图注出现
        if cls == "image" or el.find(".//img") is not None:
            imgs = [x for x in el.iter() if local(x.tag) == "img"]
            if imgs:
                self.flush_quote()
                self.flush_image()
                src = imgs[0].get("src", "")
                fig_id = el.get("id", "") or Path(src).stem
                if src:
                    self.pending_image = (src, fig_id)
                return

        text = self.inline(el)
        if not text:
            return

        # 图注
        if "fcaption" in cls or cls in {"caption", "figcaption"}:
            if self.pending_image:
                src, fig_id = self.pending_image
                self.blocks.append(f"![{fig_id}]({self.image_path(src)})")
                self.blocks.append(text)
                self.body_text.append(text)
                self.figures += 1
                self.pending_image = None
            else:
                self.add_block(text)
            return

        # 章号 / 章题
        if cls == "chpnor":
            self.chapter_label = plain_text(el)
            return
        if cls == "chphr":
            title = clean_text(self.inline(el).replace("\n", " "))
            heading = f"{self.chapter_label}: {title}" if self.chapter_label else title
            self.add_block("# " + heading)
            return

        # 题词
        if cls == "chpinfoc":
            self.flush_quote()
            self.blockquote.append(text)
            return
        if cls == "chpinfoc1":
            self.blockquote.append(text)
            self.flush_quote()
            return

        # 节标题
        if cls in {"sect1c", "sect2c", "sect3c"}:
            level = {"sect1c": 2, "sect2c": 3, "sect3c": 4}[cls]
            self.add_block("#" * level + " " + plain_text(el))
            return

        # 引文
        if cls in {"blockq", "blockquote", "extract"}:
            self.flush_image()
            self.blockquote.append(text)
            return

        # 普通正文
        self.add_block(text)

    # ---------- 表格 ----------
    def convert_table(self, el: ET.Element) -> str:
        rows: list[list[str]] = []
        for tr in el.iter():
            if local(tr.tag) != "tr":
                continue
            cells = []
            for cell in tr:
                if local(cell.tag) not in {"td", "th"}:
                    continue
                value = clean_text("".join(cell.itertext())).replace("|", r"\|")
                cells.append(value)
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |"]
        lines.append("| " + " | ".join(["---"] * width) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    # ---------- 输出 ----------
    def render(self) -> str:
        self.flush_quote()
        self.flush_image()
        body = "\n\n".join(self.blocks).rstrip() + "\n"
        if self.footnotes:
            notes = "\n".join(f"[^{k}]: {v}" for k, v in self.footnotes.items())
            body += "\n## 注释\n\n" + notes + "\n"
        return body

    def word_count(self) -> int:
        text = "\n".join(self.body_text)
        latin = len(re.findall(r"[A-Za-z][A-Za-z'’\-]*", text))
        cjk = len(re.findall(r"[㐀-䶿一-鿿]", text))
        return latin + cjk


# ----------------------------------------------------------------------
# EPUB 结构
# ----------------------------------------------------------------------
def read_container(zf: zipfile.ZipFile) -> str:
    data = ET.fromstring(zf.read("META-INF/container.xml"))
    for el in data.iter():
        if local(el.tag) == "rootfile":
            path = el.get("full-path")
            if path:
                return path
    raise SystemExit("[错误] container.xml 中找不到 rootfile")


def read_opf(zf: zipfile.ZipFile, opf_path: str):
    root = ET.fromstring(zf.read(opf_path))
    base = Path(opf_path).parent
    manifest: dict[str, str] = {}
    media: dict[str, str] = {}
    for el in root.iter():
        if local(el.tag) == "item":
            item_id = el.get("id")
            href = el.get("href")
            if item_id and href:
                manifest[item_id] = href
                media[item_id] = el.get("media-type", "")
    spine: list[str] = []
    for el in root.iter():
        if local(el.tag) == "itemref":
            idref = el.get("idref")
            if idref and idref in manifest:
                spine.append(manifest[idref])
    title = ""
    for el in root.iter():
        if local(el.tag) == "title" and el.text:
            title = el.text.strip()
            break
    ncx_id = next((i for i, m in media.items() if "ncx" in m.lower()), None)
    ncx = manifest.get(ncx_id, "") if ncx_id else ""
    return base, spine, ncx, title


def read_nav_labels(zf: zipfile.ZipFile, ncx_path: str | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not ncx_path or ncx_path not in zf.namelist():
        return labels
    try:
        root = ET.fromstring(zf.read(ncx_path))
    except ET.ParseError:
        return labels
    for point in root.iter():
        if local(point.tag) != "navPoint":
            continue
        label = ""
        src = ""
        for child in point.iter():
            if local(child.tag) == "text" and not label and child.text:
                label = child.text.strip()
            elif local(child.tag) == "content":
                src = child.get("src", "").split("#")[0]
        if src and label:
            labels[src] = label
    return labels


def output_name(href: str, label: str) -> str | None:
    stem = Path(href).stem
    chapter = re.search(r"ch(\d+)", stem)
    if chapter:
        return f"ch{int(chapter.group(1)):02d}.md"
    if stem.endswith("con"):
        return "conclusion.md"
    if stem.endswith("bib"):
        return "backmatter/bibliography.md"
    if stem.endswith("ind"):
        return "backmatter/index.md"
    if "ack" in stem:
        return "frontmatter/acknowledgments.md"
    if "copy" in stem:
        return "frontmatter/copyright.md"
    if "dedi" in stem:
        return "frontmatter/dedication.md"
    if "tit" in stem:
        return "frontmatter/title.md"
    if "toc" in stem:
        return "frontmatter/contents.md"
    if any(x in stem.lower() for x in ("cover", "half", "bm", "fm")):
        return None
    return f"frontmatter/{re.sub(r'^[0-9]+_', '', stem)}.md"


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="从 EPUB 抽取 Markdown 原文")
    parser.add_argument("--epub", required=True, help="EPUB 文件")
    parser.add_argument("--out", required=True, help="输出目录（通常是项目/source）")
    parser.add_argument("--clean", action="store_true", help="先清空输出目录中的 md 与 images")
    args = parser.parse_args()

    epub = Path(args.epub).resolve()
    out = Path(args.out).resolve()
    if not epub.exists():
        print(f"[错误] 找不到 {epub}")
        return 1

    out.mkdir(parents=True, exist_ok=True)
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    if args.clean:
        for pattern in ("*.md", "frontmatter/*.md", "backmatter/*.md"):
            for path in out.glob(pattern):
                path.unlink()
        if images_dir.exists():
            shutil.rmtree(images_dir)
        images_dir.mkdir(parents=True)

    with zipfile.ZipFile(epub) as zf:
        opf_path = read_container(zf)
        base, spine, ncx, book_title = read_opf(zf, opf_path)
        ncx_path = (base / ncx).as_posix() if ncx else None
        labels = read_nav_labels(zf, ncx_path)

        # 复制全部图片
        all_images = set()
        for name in zf.namelist():
            if "/Images/" in name or name.lower().startswith("oebps/images/"):
                dest = images_dir / Path(name).name
                with zf.open(name) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                all_images.add(Path(name).name)

        manifest_rows = []
        for href in spine:
            full = (base / href).as_posix() if base != Path(".") else href
            if full not in zf.namelist():
                continue
            label = labels.get(href, Path(href).stem)
            rel = output_name(href, label)
            if rel is None:
                continue
            try:
                root = ET.fromstring(normalize_entities(zf.read(full).decode("utf-8", "replace")))
            except ET.ParseError as exc:
                print(f"[警告] 解析失败，跳过 {href}: {exc}")
                continue
            converter = ChapterConverter(all_images)
            converter.process(root)
            text = converter.render()
            if not text.strip():
                continue
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            manifest_rows.append({
                "file": rel.replace("\\", "/"),
                "title": label,
                "words": converter.word_count(),
                "paragraphs": converter.paragraphs,
                "figures": converter.figures,
                "footnotes": len(converter.footnotes),
                "tables": converter.tables,
                "source_file": href,
            })
            print(f"  {rel:38} {label[:44]:44} "
                  f"{converter.word_count():>6} 词 {len(converter.footnotes):>3} 注 "
                  f"{converter.figures:>2} 图")

    manifest = out / "manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["file", "title", "words", "paragraphs",
                        "figures", "footnotes", "tables", "source_file"],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    total_words = sum(r["words"] for r in manifest_rows)
    total_notes = sum(r["footnotes"] for r in manifest_rows)
    total_figs = sum(r["figures"] for r in manifest_rows)
    print("-" * 70)
    print(f"完成：{len(manifest_rows)} 个文件，{total_words} 词，"
          f"{total_notes} 条脚注，{total_figs} 幅图")
    print(f"输出：{out}")
    print(f"清单：{manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
