#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目状态汇总：一本书当前处在哪一阶段、还有哪些阻断项。

面向 agent 的一站式入口。默认输出人读摘要；--json 输出稳定结构，
其中 check/global 字段直接内嵌 check.py 与 global_check.py 的结果。

用法：
    python scripts/status.py --project projects/my-book
    python scripts/status.py --project . --json
    python scripts/status.py --project . --json --no-check

退出码：0 = 无阻断项；1 = 有阻断项或无法读取项目。
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def read_progress(project: Path) -> list[dict]:
    path = project / "notes" / "progress.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(fh)]


def count_terms(project: Path) -> dict:
    path = project / "glossary" / "terms.csv"
    if not path.exists():
        return {"total": 0, "final": 0, "draft": 0, "other": 0}
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if any((v or "").strip() for v in row.values()):
                rows.append(row)
    final = sum(1 for r in rows if (r.get("status") or "").strip().lower() == "final")
    draft = sum(1 for r in rows if (r.get("status") or "").strip().lower() == "draft")
    return {"total": len(rows), "final": final, "draft": draft,
            "other": len(rows) - final - draft}


def chapter_files(project: Path) -> list[dict]:
    out = []
    chapters = project / "chapters"
    for path in sorted(chapters.glob("*.tex")) if chapters.exists() else []:
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        out.append({
            "file": str(path.relative_to(project).as_posix()),
            "todos": text.count("\\todo{") + text.count("%% TODO"),
            "chars": len([c for c in text if "一" <= c <= "鿿"]),
        })
    return out


def run_json(script: str, project: Path) -> dict | None:
    cmd = [sys.executable, "-I", str(SCRIPT_DIR / script),
           "--project", str(project), "--json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False,
                "error": f"{script} 未返回 JSON",
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:]}


def build_status(project: Path, run_checks: bool = True,
                 deep: bool = False, summary: bool = False) -> dict:
    meta = read_json(project / "project.json", {})
    if not meta:
        return {"ok": False, "exit_code": 1,
                "error": f"找不到或无法解析 {project / 'project.json'}"}

    units = read_progress(project)
    terms = count_terms(project)
    chapters = chapter_files(project)
    todos = sum(c["todos"] for c in chapters)

    check = run_json("check.py", project) if run_checks else None
    global_result = run_json("global_check.py", project) if run_checks else None

    blocking = []
    if todos:
        blocking.append(f"章节内仍有 {todos} 处 TODO")
    if check and not check.get("ok", False) and not check.get("summary", {}).get("error", 0):
        blocking.append(f"check.py 未能完成：{check.get('error', '未知错误')}")
    if check and check.get("summary", {}).get("error", 0):
        blocking.append(f"check.py 报错 {check['summary']['error']} 处")
    if global_result and global_result.get("error"):
        blocking.append(f"global_check 未能完成：{global_result['error']}")
    if global_result and global_result.get("problem_units", 0):
        blocking.append(f"global_check 问题章节 {global_result['problem_units']} 个")
    for unit in units:
        if unit.get("status") in {"未开始", "初译", "自校"}:
            blocking.append(f"{unit.get('unit')} 尚未完成审校")

    exit_code = 1 if blocking else 0
    check_out = check
    if check_out and not deep:
        check_out = {k: v for k, v in check_out.items() if k != "issues"}
        check_out["detail"] = "summary"
    global_out = global_result
    if global_out and not deep:
        global_out = {k: v for k, v in global_out.items() if k != "units"}
        global_out["detail"] = "summary"
    chapters_payload = {"count": len(chapters), "todos": todos}
    if not summary:
        chapters_payload["files"] = chapters
    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "project": {
            "slug": meta.get("slug", ""),
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "translator": meta.get("translator", ""),
            "style_id": meta.get("style_id", ""),
            "qa_mode": meta.get("qa_mode", ""),
            "version": meta.get("version", ""),
            "rights": meta.get("rights", ""),
            "publisher": meta.get("publisher", ""),
        },
        "unit_count": len(units),
        "units": [] if summary else units,
        "terms": terms,
        "chapters": chapters_payload,
        "blocking": blocking,
        "check": check_out,
        "global": global_out,
    }


def print_summary(status: dict) -> None:
    proj = status["project"]
    print(f"项目：{proj['title'] or proj['slug']}")
    print(f"文风：{proj['style_id'] or '（未选择）'}")
    print(f"术语：{status['terms']['total']} 条"
          f"（final {status['terms']['final']} / draft {status['terms']['draft']}）")
    print(f"章节：{status['chapters']['count']} 个，TODO {status['chapters']['todos']} 处")
    print("-" * 60)
    for unit in status["units"]:
        print(f"  {unit.get('unit', ''):<16} {unit.get('status', ''):<8}"
              f" {unit.get('zh_chars', ''):>8} 字  {unit.get('notes', '')[:40]}")
    print("-" * 60)
    if status.get("check"):
        s = status["check"].get("summary", {})
        print(f"check.py：错误 {s.get('error', '?')} / 警告 {s.get('warn', '?')}"
              f" / 提示 {s.get('info', '?')}")
    if status.get("global"):
        print(f"global_check：问题章节 {status['global'].get('problem_units', '?')}，"
              f"合计 {status['global'].get('total_chars', 0):,} 字")
    if status["blocking"]:
        print("\n阻断项：")
        for item in status["blocking"]:
            print(f"  - {item}")
    else:
        print("\n无阻断项。")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="项目状态汇总")
    parser.add_argument("--project", default=".", help="项目目录")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读的 JSON（stdout 只有 JSON）")
    parser.add_argument("--no-check", action="store_true",
                        help="跳过 check.py / global_check.py，只读静态信息")
    parser.add_argument("--deep", action="store_true",
                        help="连同 check 的 issues 与 global 的逐章明细一起输出（体积较大）")
    parser.add_argument("--summary", action="store_true",
                        help="省略 units 与 chapters.files，仅保留计数与阻断项")
    args = parser.parse_args()

    status = build_status(Path(args.project).resolve(),
                          run_checks=not args.no_check,
                          deep=args.deep, summary=args.summary)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        if "error" in status:
            print(f"[错误] {status['error']}")
        else:
            print_summary(status)
    return int(status.get("exit_code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
