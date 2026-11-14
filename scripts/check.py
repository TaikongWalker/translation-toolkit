#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""翻译质量检查：术语一致性、标点、脚注/图数量、漏译、TODO。

用法：
    python scripts/check.py --project projects/my-book
    python scripts/check.py --project . --summary
    python scripts/check.py --project . --max-details 5

退出码：0 = 无错误；1 = 有错误（A2/A4/A5/A6/A11/A12）。
警告与提示不影响退出码。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

CJK = r"\u3400-\u4dbf\u4e00-\u9fff"
ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

# 检查项编号 → 级别（与 docs/03-质检清单.md 对应）
SEVERITY = {
    "A1": INFO,
    "A2": ERROR,
    "A3": INFO,
    "A4": ERROR,
    "A5": ERROR,
    "A6": ERROR,
    "A7": WARN,
    "A8": WARN,
    "A9": WARN,
    "A10": INFO,
    "A11": ERROR,
    "A12": ERROR,
}

CATEGORIES = {"人名", "地名", "机构", "作品", "术语", "其他"}


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def strip_comments(tex: str) -> str:
    return re.sub(r"(?<!\\)%.*$", "", tex, flags=re.M)


def strip_latex(tex: str) -> str:
    """尽量只保留正文可见文字，用于标点、术语、漏译检查。"""
    text = strip_comments(tex)
    # 重绘图中的 TikZ 代码不是正文，标点检查时整体剔除
    text = re.sub(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", "", text, flags=re.S)
    text = re.sub(r"\\verb\*?\|[^|]*\|", "", text)
    text = re.sub(r"\\verb\*?\{[^}]*\}", "", text)
    text = re.sub(r"\\url\{[^}]*\}", "", text)
    text = re.sub(r"\\texttt\{[^{}]*\}", "", text)
    # 只删除命令名，保留参数内容（脚注、引文文字仍需检查）
    text = re.sub(
        r"\\(?:label|ref|eqref|pageref|cite|citep|citet|index|input|include"
        r"|includegraphics|bibliography|bibliographystyle|addcontentsline"
        r"|captionsetup|graphicspath|setlength|renewcommand|newcommand)\*?"
        r"(?:\[[^\]]*\])?(?:\{[^{}]*\})*",
        "",
        text,
    )
    text = re.sub(r"\\begin\{[^}]*\}(?:\[[^\]]*\])?", "", text)
    text = re.sub(r"\\end\{[^}]*\}", "", text)
    text = re.sub(r"\$[^$]*\$", "", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?", "", text)
    text = text.replace("{", "").replace("}", "")
    return text


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def snippet(text: str, index: int, width: int = 45) -> str:
    start = max(0, index - width)
    end = min(len(text), index + width)
    frag = text[start:end].replace("\n", " ")
    return ("…" if start else "") + frag + ("…" if end < len(text) else "")


def latin_word_count(fragment: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'’\-]*", fragment))


# ----------------------------------------------------------------------
# 加载
# ----------------------------------------------------------------------
def load_terms(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(fh)
                if any((v or "").strip() for v in row.values())]


def chapter_pairs(project: Path) -> list[tuple[str, Path, Path | None]]:
    """source/*.md ↔ chapters/<stem>.tex。只返回可能有正文的章。"""
    source_dir = project / "source"
    chapters_dir = project / "chapters"
    pairs = []
    if not source_dir.exists():
        return pairs
    for src in sorted(source_dir.glob("*.md")):
        if src.name.lower() == "readme.md":
            continue
        stem = src.stem
        target = chapters_dir / f"{stem}.tex"
        if target.exists():
            pairs.append((stem, src, target))
    # 反向：有 tex 但无 md（排除示例章/试译章）
    for tex in sorted(chapters_dir.glob("*.tex")) if chapters_dir.exists() else []:
        if re.match(r"ch\d+$", tex.stem) and not (source_dir / f"{tex.stem}.md").exists():
            pairs.append((tex.stem, None, tex))
    return pairs


# ----------------------------------------------------------------------
# 检查
# ----------------------------------------------------------------------
class Checker:
    def __init__(self, project: Path, summary: bool, max_details: int):
        self.project = project
        self.summary = summary
        self.max_details = max_details
        self.issues: list[tuple[str, str, str, str]] = []  # code, severity, where, message
        self.counts = {code: 0 for code in SEVERITY}

    def add(self, code: str, where: str, message: str) -> None:
        severity = SEVERITY[code]
        self.counts[code] += 1
        self.issues.append((code, severity, where, message))

    # ---------------- 术语表结构 ----------------
    def check_glossary(self, terms: list[dict]) -> None:
        seen = {}
        for i, row in enumerate(terms, start=2):
            source = row.get("source", "")
            target = row.get("target", "")
            where = f"glossary/terms.csv:{i}"
            if not source and not target:
                continue
            if not source or not target:
                self.add("A12", where, "source 或 target 为空")
                continue
            key = source.casefold()
            if key in seen:
                self.add("A12", where, f"重复词条：{source}（首次见第 {seen[key]} 行）")
            else:
                seen[key] = i
            if row.get("category") not in CATEGORIES:
                self.add("A12", where, f"未知类别：{row.get('category')!r}")
            if row.get("status", "").lower() not in {"draft", "final", "deprecated"}:
                self.add("A12", where, f"未知状态：{row.get('status')!r}")

    # ---------------- 单章 ----------------
    def check_chapter(self, stem: str, src: Path | None, tex: Path,
                      terms: list[dict]) -> None:
        raw = read_text(tex)
        if not raw.strip():
            self.add("A11", str(tex.relative_to(self.project)), "章节文件为空")
            return
        # 尚未开译的骨架（scaffold.py 生成）跳过内容检查
        if "（待译）" in raw and "TODO" in raw:
            return
        visible = strip_latex(raw)
        where = str(tex.relative_to(self.project))

        todo = len(re.findall(r"%%\s*TODO|\\todo\{", raw))
        if todo:
            self.add("A10", where, f"遗留 TODO {todo} 处")

        # A4 半角标点
        patterns = [
            (rf"[{CJK}]\s*[,;:!?]", "中文后使用半角标点"),
            (rf"[,;:!?]\s*[{CJK}]", "半角标点后接中文"),
            (rf"[{CJK}]\s*\.(?!\d)", "中文后使用半角句点"),
        ]
        for pattern, label in patterns:
            for m in re.finditer(pattern, visible):
                self.add("A4", f"{where}:{line_of(visible, m.start())}",
                         f"{label}：{snippet(visible, m.start())}")

        # A5 英文引号
        for m in re.finditer(r'"', visible):
            self.add("A5", f"{where}:{line_of(visible, m.start())}",
                     f"中文文本中出现英文双引号：{snippet(visible, m.start())}")
        for m in re.finditer(rf"'[{CJK}]|[{CJK}]'", visible):
            self.add("A5", f"{where}:{line_of(visible, m.start())}",
                     f"中文文本中出现英文单引号：{snippet(visible, m.start())}")

        # A6 省略号/破折号
        for m in re.finditer(rf"\.{{3,}}|[{CJK}]\s*\.\.\.", visible):
            self.add("A6", f"{where}:{line_of(visible, m.start())}",
                     f"请用……代替 ...：{snippet(visible, m.start())}")
        for m in re.finditer(rf"[{CJK}]\s*--|[CJK]*--\s*[{CJK}]", visible):
            self.add("A6", f"{where}:{line_of(visible, m.start())}",
                     f"请用——代替 --：{snippet(visible, m.start())}")

        # A1/A2/A3 术语
        term_free = re.sub(r"\\term\{[^{}]*\}\{[^{}]*\}", "", raw)
        term_free = re.sub(r"\\orig\{[^{}]*\}", "", term_free)
        term_visible = strip_latex(term_free)
        for row in terms:
            source = row.get("source", "")
            target = row.get("target", "")
            if not source:
                continue
            flags = re.IGNORECASE if re.fullmatch(r"[\x00-\x7f]+", source) else 0
            found = list(re.finditer(re.escape(source), term_visible, flags))
            if found:
                sample = "；".join(snippet(term_visible, m.start(), 25) for m in found[:2])
                self.add("A1", where,
                         f"原文术语「{source}」在译文中残留 {len(found)} 次：{sample}")
            first_seen = row.get("first_seen", "").lower()
            introduced_here = (not first_seen) or first_seen in stem.lower() or stem.lower() in first_seen
            if target and introduced_here and target not in visible:
                self.add("A3", where, f"术语「{source} → {target}」未在本章出现")
            # 先遮掉正确译名，避免「同时代人」命中「我们的同时代人」这类子串误报
            scan = visible.replace(target, "〔正确译名〕") if target else visible
            for variant in re.split(r"[|｜]", row.get("forbidden", "")):
                variant = variant.strip()
                if not variant:
                    continue
                for m in re.finditer(re.escape(variant), scan):
                    self.add("A2", f"{where}:{line_of(scan, m.start())}",
                             f"使用禁用变体「{variant}」（应为「{target}」）："
                             f"{snippet(scan, m.start())}")

        # A7/A8 与原文字数/图数对照
        if src is not None:
            source_text = read_text(src)
            src_notes = len(re.findall(r"(?m)^\[\^[^\]]+\]:", source_text))
            # \zhu 使用独立编号与 \footnotetext，不占用原注计数
            tex_notes = len(re.findall(r"\\footnote\s*\{", raw))
            tex_zhu = len(re.findall(r"\\zhu\s*\{", raw))
            if src_notes != tex_notes:
                self.add("A7", where,
                         f"脚注数不一致：原文 {src_notes}，译文原注 {tex_notes}"
                         f"（另有译者注 {tex_zhu}）")
            src_figs = len(re.findall(r"!\[[^\]]*\]\(", source_text))
            tex_figs = len(re.findall(r"\\begin\{figure\}", raw))
            if src_figs != tex_figs:
                self.add("A8", where, f"图片数不一致：原文 {src_figs}，译文 {tex_figs}")

        # A9 漏译：连续 8 个以上英文单词（而不是段落内英文词总数）
        for para in re.split(r"\n\s*\n", visible):
            for run in re.findall(
                r"(?:[A-Za-z][A-Za-z'’\-]*[ \t]+){7,}[A-Za-z][A-Za-z'’\-]*",
                para,
            ):
                words = latin_word_count(run)
                if words >= 8:
                    self.add("A9", where,
                             f"疑似未翻译的英文（连续 {words} 词）："
                             f"{' '.join(run.split())[:90]}…")

    # ---------------- 汇总 ----------------
    def report(self) -> int:
        by_sev = {sev: 0 for sev in (ERROR, WARN, INFO)}
        for code, severity, where, message in self.issues:
            by_sev[severity] += 1

        if not self.summary:
            current = None
            for code, severity, where, message in self.issues:
                if severity != current:
                    print(f"\n【{severity}】")
                    current = severity
                print(f"  {code} {where}  {message}")

        print("\n" + "=" * 60)
        print("检查汇总")
        print("=" * 60)
        for code in sorted(self.counts):
            if self.counts[code]:
                print(f"  {code} [{SEVERITY[code]:5}] {self.counts[code]} 处")
        print(f"\n  错误 {by_sev[ERROR]} / 警告 {by_sev[WARN]} / 提示 {by_sev[INFO]}")
        if by_sev[ERROR] == 0:
            print("  结论：没有发现阻断性错误。")
        else:
            print("  结论：存在阻断性错误，请逐条处理（见 docs/03-质检清单.md）。")
        return 1 if by_sev[ERROR] else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="翻译质量检查")
    parser.add_argument("--project", default=".", help="项目目录")
    parser.add_argument("--summary", action="store_true", help="只输出汇总")
    parser.add_argument("--max-details", type=int, default=0,
                        help="每类最多显示条数（0 = 全部）")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not (project / "project.json").exists():
        print(f"[错误] 在 {project} 找不到 project.json")
        return 1

    try:
        meta = json.loads(read_text(project / "project.json"))
    except json.JSONDecodeError as exc:
        print(f"[错误] project.json 无法解析：{exc}")
        return 1

    print(f"项目：{meta.get('title', project.name)}")
    print(f"目录：{project}")
    print("-" * 60)

    checker = Checker(project, args.summary, args.max_details)
    terms = load_terms(project / "glossary" / "terms.csv")
    print(f"术语表：{len(terms)} 条")
    checker.check_glossary(terms)

    pairs = chapter_pairs(project)
    if not pairs:
        print("[提示] 未找到 source/*.md 与 chapters/*.tex 的对应关系，跳过章节检查。")
    for stem, src, tex in pairs:
        if tex is None:
            continue
        print(f"检查 {stem} …", end="\r")
        checker.check_chapter(stem, src, tex, terms)
    print(" " * 40, end="\r")

    if args.max_details and not args.summary:
        # 按类别截断，避免刷屏
        limited = []
        seen = {}
        for issue in checker.issues:
            code = issue[0]
            seen[code] = seen.get(code, 0) + 1
            if seen[code] <= args.max_details:
                limited.append(issue)
        checker.issues = limited

    return checker.report()


if __name__ == "__main__":
    raise SystemExit(main())
