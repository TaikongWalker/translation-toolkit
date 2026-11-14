#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一的质检入口：在“全部检查”和“抽样检查”之间选择。

两种模式都先做**全量自动结构检查**（术语、标点、脚注/图数量、数字、TODO），
差别在语义复核的覆盖范围：

- full：为全书每一段生成复核任务（默认仍不打印到 stdout，写入文件）；
- sample：按目标残余率与置信度计算样本量，分轮抽样；
- structural：只做自动检查，不生成语义复核任务。

用法：
    python scripts/qa.py --project . --mode full --json
    python scripts/qa.py --project . --mode sample --margin 0.01 --confidence 0.95
    python scripts/qa.py --project . --mode sample --save   # 记住选择

退出码：0 = 结构检查无阻断错误；1 = 有错误或无法读取。
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audit  # noqa: E402
import sample_size  # noqa: E402

MODES = ("full", "sample", "structural")


def run_json(script: str, project: Path, extra: list[str]) -> dict:
    cmd = [sys.executable, "-I", str(SCRIPT_DIR / script),
           "--project", str(project), "--json", *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"{script} 未返回 JSON",
                "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:]}


def structural(project: Path, detail: bool, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if detail:
        check = run_json("check.py", project, ["--compact"])
        (out_dir / "check-full.json").write_text(
            json.dumps(check, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        check = run_json("check.py", project, ["--omit-issues"])
    global_result = run_json("global_check.py", project, ["--summary"])
    ok = bool(check.get("ok")) and bool(global_result.get("ok"))
    return {"ok": ok, "check": check, "global": global_result}


def full_semantic(project: Path, out_dir: Path,
                  refresh: bool) -> dict:
    inventory = audit.load_inventory(project, refresh=refresh)
    segments = audit.segment_index(inventory)
    tasks = []
    chars = 0
    for seg in segments.values():
        tasks.append(seg)
        chars += seg.get("source_chars", 0) + seg.get("target_chars", 0)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = out_dir / "full-plan.json"
    plan.write_text(json.dumps({
        "mode": "full",
        "total_segments": len(tasks),
        "tasks": tasks,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"kind": "full", "total_segments": len(tasks),
            "tasks": len(tasks), "review_chars": chars,
            "plan_file": str(plan)}


def sampled(project: Path, out_dir: Path, margin: float, confidence: float,
            rounds: int, seed: int, refresh: bool,
            with_replacement: bool, size_override: int = 0) -> dict:
    inventory = audit.load_inventory(project, refresh=refresh)
    total = int(inventory.get("total_segments", 0))
    if total <= 0:
        return {"kind": "sample", "total_segments": 0, "tasks": 0,
                "review_chars": 0, "error": "段落清单为空，先运行 audit.py inventory"}
    required = sample_size.required_zero_errors(margin, confidence, total)
    log_path = project / audit.AUDIT_DIR / "sample-log.csv"
    already = len({r.get("id") for r in audit.read_csv(log_path) if r.get("id")})
    additional = max(0, required - already)
    per_round = math.ceil(additional / max(1, rounds)) if additional else 0
    if size_override > 0:
        per_round = size_override
        required = already + per_round * rounds
        additional = per_round * rounds

    tasks: list[dict] = []
    plan_files: list[str] = []
    if per_round:
        for round_no in range(1, rounds + 1):
            result = audit.plan_round(
                project, per_round, seed, round_no,
                with_replacement=with_replacement, refresh=refresh)
            if not result.get("ok"):
                break
            tasks.extend(result.get("tasks", []))
            plan_files.append(result.get("plan_file", ""))
    review_chars = sum(len(t.get("source", "")) + len(t.get("target", ""))
                       for t in tasks)
    return {"kind": "sample", "total_segments": total,
            "required_samples": required, "already_sampled": already,
            "additional_samples": additional, "rounds": rounds,
            "per_round": per_round, "tasks": len(tasks),
            "review_chars": review_chars, "plan_files": plan_files,
            "margin": margin, "confidence": confidence}


def rough_tokens(chars: int) -> int:
    return int(round(chars / 2.5))


def save_mode(project: Path, mode: str, margin: float, confidence: float) -> None:
    path = project / "project.json"
    meta = json.loads(path.read_text(encoding="utf-8-sig"))
    meta["qa_mode"] = mode
    meta["qa_margin"] = margin
    meta["qa_confidence"] = confidence
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="统一质检入口：全量或抽样")
    parser.add_argument("--project", default=".")
    parser.add_argument("--mode", choices=MODES,
                        help="full（全量语义复核）/ sample（抽样）/ structural（仅自动检查）")
    parser.add_argument("--margin", type=float, default=0.01)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--size", type=int, default=0,
                        help="sample 模式每轮段数；0 = 按统计样本量自动计算")
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--with-replacement", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--save", action="store_true",
                        help="把 mode/margin/confidence 写入 project.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not (project / "project.json").exists():
        print(f"[错误] {project} 不是项目目录（缺 project.json）")
        return 1
    meta = json.loads((project / "project.json").read_text(encoding="utf-8-sig"))
    mode = args.mode or meta.get("qa_mode") or "full"
    margin = args.margin if args.mode else float(meta.get("qa_margin", args.margin))
    confidence = (args.confidence if args.mode
                  else float(meta.get("qa_confidence", args.confidence)))

    out_dir = project / "notes" / "qa"
    structural_result = structural(project, detail=(mode == "full"), out_dir=out_dir)
    semantic: dict = {"kind": "none", "tasks": 0, "review_chars": 0}
    full_chars = 0

    if mode == "full":
        semantic = full_semantic(project, out_dir, args.refresh)
        full_chars = semantic.get("review_chars", 0)
    elif mode == "sample":
        semantic = sampled(project, out_dir, margin, confidence, args.rounds,
                           args.seed, args.refresh, args.with_replacement,
                           args.size)
        inventory = audit.load_inventory(project)
        full_chars = sum(s.get("source_chars", 0) + s.get("target_chars", 0)
                         for s in audit.segment_index(inventory).values())

    saved_ratio = (round(1 - semantic.get("review_chars", 0) / full_chars, 4)
                   if full_chars else 0.0)
    estimate = {
        "full_review_tokens_rough": rough_tokens(full_chars),
        "this_run_tokens_rough": rough_tokens(semantic.get("review_chars", 0)),
        "saved_ratio": saved_ratio,
        "note": "按字符数 / 2.5 粗估；实际取决于模型、语言与提示长度。",
    }

    if args.save:
        save_mode(project, mode, margin, confidence)

    result = {
        "ok": bool(structural_result["ok"]),
        "exit_code": 0 if structural_result["ok"] else 1,
        "mode": mode,
        "project": str(project),
        "structural": {
            "ok": structural_result["ok"],
            "check": structural_result["check"].get("summary", {}),
            "check_ok": structural_result["check"].get("ok"),
            "global": structural_result["global"],
        },
        "semantic": semantic,
        "estimate": estimate,
        "saved_mode": bool(args.save),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result["exit_code"]

    print(f"质检模式：{mode}")
    check = result["structural"]["check"]
    print(f"结构检查：错误 {check.get('error', '?')} / 警告 {check.get('warn', '?')}"
          f" / 提示 {check.get('info', '?')}")
    glob = result["structural"]["global"]
    print(f"全书结构：问题章节 {glob.get('problem_units', '?')}，"
          f"合计 {glob.get('total_chars', 0):,} 字")
    if mode == "full":
        print(f"语义复核任务：{semantic.get('tasks', 0)} 段（全书）")
        print(f"  计划文件：{semantic.get('plan_file', '')}")
    elif mode == "sample":
        print(f"语义复核任务：{semantic.get('tasks', 0)} 段；"
              f"目标残余率 ≤ {margin:.2%}（{confidence:.0%} 置信）")
        print(f"  所需样本 {semantic.get('required_samples', 0)}，"
              f"已抽 {semantic.get('already_sampled', 0)}，"
              f"本轮 {semantic.get('tasks', 0)}")
        for path in semantic.get("plan_files", []):
            if path:
                print(f"  计划文件：{path}")
    else:
        print("语义复核任务：未生成（structural 模式）")
    print(f"粗略 token：本次复核约 {estimate['this_run_tokens_rough']:,}，"
          f"全书约 {estimate['full_review_tokens_rough']:,}，"
          f"节省 {estimate['saved_ratio']:.1%}")
    if args.save:
        print(f"已记住：qa_mode={mode}, margin={margin}, confidence={confidence}")
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
