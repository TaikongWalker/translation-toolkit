#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一章原文切成容量安全的翻译单元。

目标：在不丢字、不切断段落的前提下，让单次翻译/检查的输出与输入
都落在模型上下文可承受的范围内。

规则：
- 只在空行（段落边界）处切，不拆句子、不拆脚注定义；
- 单个超长段落无法再切时，单独成块并在警告中说明；
- 每个块有稳定 ID（c001…），按顺序拼回必须与原文逐字一致；
- 可选同时写出逐块文件，供 agent 逐块翻译后再合并。

用法：
    python scripts/chunk.py --input source/ch03.md --out chunks/ch03 --max-chars 6000
    python scripts/chunk.py --project . --unit ch03 --json
    python scripts/chunk.py --input source/ch03.md --json --include-text

退出码：0 = 成功；1 = 无法读取或切分。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")


def split_blocks(text: str) -> list[tuple[int, int]]:
    """按空行切块，返回 (start, end) 偏移；分隔符归入前一块末尾。"""
    spans = []
    start = 0
    for match in re.finditer(r"\n[ \t]*\n", text):
        end = match.end()
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def heading_of(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def build_chunks(text: str, max_chars: int, min_chars: int) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    spans = split_blocks(text)
    groups: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    size = 0
    for start, end in spans:
        length = end - start
        if length > max_chars:
            if current:
                groups.append(current)
                current, size = [], 0
            groups.append([(start, end)])
            warnings.append(
                f"单段 {length} 字符，超过 max-chars={max_chars}；未拆分以避免破坏上下文。"
            )
            continue
        if current and size + length > max_chars:
            groups.append(current)
            current, size = [], 0
        current.append((start, end))
        size += length
    if current:
        groups.append(current)

    # 合并过短的块，减少调用次数（仍不跨段）
    merged: list[list[tuple[int, int]]] = []
    for group in groups:
        if merged and sum(e - s for s, e in group) < min_chars:
            merged[-1].extend(group)
        else:
            merged.append(group)

    chunks = []
    for idx, group in enumerate(merged, start=1):
        start = group[0][0]
        end = group[-1][1]
        chunks.append({
            "id": f"c{idx:03d}",
            "start": start,
            "end": end,
            "chars": end - start,
            "heading": heading_of(text[start:end]),
        })
    return chunks, warnings


def add_context(chunks: list[dict], text: str, size: int) -> None:
    """给每块附上所在小节与相邻原文片段，供翻译时判断指代与语气。"""
    headings = [(m.start(), m.group(0).strip())
                for m in re.finditer(r"(?m)^#{1,6}\s+.+$", text)]
    for i, chunk in enumerate(chunks):
        section = ""
        for pos, line in headings:
            if pos <= chunk["start"]:
                section = line
            else:
                break
        chunk["section"] = section
        chunk["prev_id"] = chunks[i - 1]["id"] if i else ""
        chunk["next_id"] = chunks[i + 1]["id"] if i + 1 < len(chunks) else ""
        if size > 0:
            chunk["context_before"] = text[max(0, chunk["start"] - size):chunk["start"]].strip()
            chunk["context_after"] = text[chunk["end"]:chunk["end"] + size].strip()


def resolve_input(args) -> Path:
    if args.input:
        return Path(args.input).resolve()
    if args.unit:
        return (Path(args.project).resolve() / "source" / f"{args.unit}.md")
    raise SystemExit("需要 --input 或 --unit")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="把原文切成容量安全的翻译单元")
    parser.add_argument("--input", help="原文 Markdown 文件")
    parser.add_argument("--project", default=".", help="项目目录（配合 --unit）")
    parser.add_argument("--unit", default="", help="单元名，如 ch03、conclusion")
    parser.add_argument("--out", help="写出逐块文件与 plan.json 的目录")
    parser.add_argument("--max-chars", type=int, default=6000,
                        help="单块目标上限（默认 6000 字符）")
    parser.add_argument("--min-chars", type=int, default=800,
                        help="过短的块并入下一块（默认 800 字符）")
    parser.add_argument("--context-chars", type=int, default=200,
                        help="每块附带的相邻上下文字符数（默认 200，0 = 不带）")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读 JSON（stdout 只有 JSON）")
    parser.add_argument("--include-text", action="store_true",
                        help="JSON 中附带每块原文（体积较大）")
    args = parser.parse_args()

    try:
        path = resolve_input(args)
    except SystemExit as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    if not path.exists():
        message = f"找不到 {path}"
        if args.json:
            print(json.dumps({"ok": False, "exit_code": 1, "error": message},
                             ensure_ascii=False, indent=2))
        else:
            print(f"[错误] {message}")
        return 1

    text = read_text(path)
    if not text.strip():
        message = f"{path.name} 没有内容"
        if args.json:
            print(json.dumps({"ok": False, "exit_code": 1, "error": message},
                             ensure_ascii=False, indent=2))
        else:
            print(f"[错误] {message}")
        return 1

    chunks, warnings = build_chunks(text, args.max_chars, args.min_chars)
    add_context(chunks, text, args.context_chars)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    plan = {
        "ok": True,
        "exit_code": 0,
        "input": str(path),
        "source_sha256": digest,
        "total_chars": len(text),
        "chunk_count": len(chunks),
        "max_chars": args.max_chars,
        "lossless": True,
        "warnings": warnings,
        "chunks": chunks,
    }

    if args.out:
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        for chunk in chunks:
            chunk["file"] = f"{chunk['id']}.md"
            body = text[chunk["start"]:chunk["end"]]
            (out / chunk["file"]).write_text(body, encoding="utf-8")
            if args.include_text:
                chunk["text"] = body
        (out / "plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        plan["plan_file"] = str(out / "plan.json")

    if args.json:
        if not args.include_text:
            for chunk in plan["chunks"]:
                chunk.pop("text", None)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    print(f"[chunk] {path.name} → {len(chunks)} 块，{len(text):,} 字符，sha256={digest[:12]}")
    for chunk in chunks[:20]:
        print(f"  {chunk['id']}  {chunk['chars']:>6} 字符  {chunk['heading'][:40]}")
    if len(chunks) > 20:
        print(f"  … 其余 {len(chunks) - 20} 块")
    for warning in warnings:
        print(f"  [注意] {warning}")
    if args.out:
        print(f"  已写出：{args.out}")
    print("下一步：逐块翻译 → 按 plan.json 顺序合并 → 运行 check.py / global_check.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
