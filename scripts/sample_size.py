#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""样本量计算：要抽多少段，才能在统计上把“残余错误率”压到某个上界以下。

回答的是有限的问题，而不是“证明绝对无遗漏”：
在随机抽样、独立复核、复核者不漏判的前提下，若 n 个随机段落中 0 个错误，
则在给定置信度下，残余错误率的上界不超过 margin。

零错误样本的经典结论（rule of three）：95% 置信、残余率 ≤ 1% 需要约 299 段；
给出总段落数时，用超几何分布做有限总体校正，所需样本略少。

用法：
    python scripts/sample_size.py --population 4000 --margin 0.01 --confidence 0.95
    python scripts/sample_size.py --project . --margin 0.01 --confidence 0.95 --json
    python scripts/sample_size.py --project . --margin 0.01 --reviewed 300 --observed 0
    python scripts/sample_size.py --table

退出码：0 = 成功；1 = 参数或数据错误。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

AUDIT_DIR = "notes/audit"


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k)，X ~ Binomial(n, p)。"""
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0 if k < n else 1.0
    k = min(k, n)
    total = 0.0
    log_p, log_q = math.log(p), math.log1p(-p)
    for i in range(k + 1):
        log_c = (math.lgamma(n + 1) - math.lgamma(i + 1)
                 - math.lgamma(n - i + 1))
        total += math.exp(log_c + i * log_p + (n - i) * log_q)
    return min(1.0, total)


def hypergeom_zero(n: int, population: int, defects: int) -> float:
    """不放回抽 n 个，一个缺陷都没抽到的概率。"""
    if n <= 0:
        return 1.0
    if defects <= 0:
        return 1.0
    if n > population - defects:
        return 0.0
    log_p = 0.0
    for i in range(n):
        log_p += math.log(population - defects - i) - math.log(population - i)
    return math.exp(log_p)


def required_zero_errors(margin: float, confidence: float,
                         population: int = 0) -> int:
    """0 错误时，使残余率上界 ≤ margin 所需样本量。"""
    if not 0 < margin < 1 or not 0 < confidence < 1:
        raise ValueError("margin 与 confidence 必须在 (0,1) 内")
    target = 1 - confidence
    if population > 0:
        defects = int(margin * population)
        if defects <= 0:
            return population  # 只能全查；见 note
        lo, hi = 1, population - defects
        while lo < hi:
            mid = (lo + hi) // 2
            if hypergeom_zero(mid, population, defects) <= target:
                hi = mid
            else:
                lo = mid + 1
        return lo
    return math.ceil(math.log(target) / math.log(1 - margin))


def upper_bound(k: int, n: int, confidence: float) -> float:
    """Clopper-Pearson 单侧上界：P(X<=k | p=upper) = 1-confidence。"""
    if n <= 0:
        return 1.0
    if k >= n:
        return 1.0
    target = 1 - confidence
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if binom_cdf(k, n, mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def required_with_observed(k: int, margin: float, confidence: float) -> int:
    """若已有 k 个错误，后续仍 0 错误，需要多少样本才能把上界压到 margin。"""
    if k == 0:
        return required_zero_errors(margin, confidence)
    target = 1 - confidence
    n = k + 1
    while binom_cdf(k, n, margin) > target:
        n = max(n + 1, int(n * 1.2))
        if n > 10_000_000:
            raise ValueError("所需样本量超过上限；请放宽 margin 或提高置信度")
    lo, hi = k + 1, n
    while lo < hi:
        mid = (lo + hi) // 2
        if binom_cdf(k, mid, margin) <= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def read_inventory(project: Path) -> dict:
    path = project / AUDIT_DIR / "segments.json"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_sampled(project: Path) -> int:
    path = project / AUDIT_DIR / "sample-log.csv"
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return len({row.get("id", "") for row in csv.DictReader(fh)
                    if row.get("id")})


def interpret(margin: float, confidence: float, n: int,
              population: int, observed: int, reviewed: int) -> str:
    pct = f"{margin:.2%}"
    conf = f"{confidence:.0%}"
    if reviewed > 0:
        ub = upper_bound(observed, reviewed, confidence)
        if ub <= margin:
            return (f"已复核 {reviewed} 段、发现 {observed} 个错误；单侧 {conf} "
                    f"置信上界约 {ub:.2%}，已不高于目标 {pct}。")
        return (f"已复核 {reviewed} 段、发现 {observed} 个错误；单侧 {conf} "
                f"置信上界约 {ub:.2%}，仍高于目标 {pct}。")
    if population > 0:
        return (f"若从 {population} 段中随机抽 {n} 段且复核结果为 0 错误，"
                f"则可在 {conf} 置信下认为残余错误率不高于 {pct}"
                f"（有限总体校正）。")
    return (f"若随机抽 {n} 段且复核结果为 0 错误，则可在 {conf} 置信下"
            f"认为残余错误率不高于 {pct}。")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="抽样样本量计算")
    parser.add_argument("--project", default=".", help="项目目录（读取段落总数）")
    parser.add_argument("--population", type=int, default=0,
                        help="总段落数；0 = 从项目清单读取")
    parser.add_argument("--margin", type=float, default=0.01,
                        help="可接受的残余错误率上界（默认 0.01）")
    parser.add_argument("--confidence", type=float, default=0.95,
                        help="置信度（默认 0.95）")
    parser.add_argument("--rounds", type=int, default=3,
                        help="建议拆成几轮（默认 3）")
    parser.add_argument("--reviewed", type=int, default=0,
                        help="已复核的段数（用于计算当前上界）")
    parser.add_argument("--observed", type=int, default=0,
                        help="已发现的错误段数（默认 0）")
    parser.add_argument("--table", action="store_true",
                        help="输出常用 margin/confidence 的样本量表")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读 JSON（stdout 只有 JSON）")
    args = parser.parse_args()

    if args.table:
        rows = []
        for confidence in (0.90, 0.95, 0.99):
            for margin in (0.05, 0.02, 0.01, 0.005, 0.001):
                rows.append({
                    "confidence": confidence,
                    "margin": margin,
                    "required_samples": required_zero_errors(margin, confidence),
                })
        if args.json:
            print(json.dumps({"ok": True, "exit_code": 0, "table": rows},
                             ensure_ascii=False, indent=2))
        else:
            print(f"{'置信度':<8}{'残余率上界':<12}{'0 错误所需样本':>14}")
            for row in rows:
                print(f"{row['confidence']:<8.0%}{row['margin']:<12.2%}"
                      f"{row['required_samples']:>14}")
        return 0

    project = Path(args.project).resolve()
    population = args.population
    sampled = 0
    if project and (project / "project.json").exists():
        inventory = read_inventory(project)
        if not population and inventory:
            population = int(inventory.get("total_segments", 0))
        sampled = read_sampled(project)

    if population < 0:
        print("[错误] population 不能为负")
        return 1
    if args.observed > args.reviewed and args.reviewed:
        print("[错误] observed 不能大于 reviewed")
        return 1

    try:
        required = required_with_observed(args.observed, args.margin,
                                          args.confidence)
    except ValueError as exc:
        print(f"[错误] {exc}")
        return 1

    # 零错误规划可用有限总体校正；已有错误时用二项上界。
    if population > 0 and args.observed == 0:
        required = required_zero_errors(args.margin, args.confidence, population)

    already = args.reviewed if args.reviewed else sampled
    additional = max(0, required - already)
    rounds = max(1, args.rounds)
    per_round = math.ceil(additional / rounds) if additional else 0

    result = {
        "ok": True,
        "exit_code": 0,
        "population": population,
        "sampled": sampled,
        "reviewed": args.reviewed,
        "observed": args.observed,
        "margin": args.margin,
        "confidence": args.confidence,
        "method": "zero-error upper bound" if args.observed == 0
        else "observed-error upper bound",
        "required_samples": required,
        "already_counted": already,
        "additional_samples": additional,
        "rounds": rounds,
        "per_round": per_round,
        "current_upper_bound": (
            round(upper_bound(args.observed, args.reviewed, args.confidence), 4)
            if args.reviewed else None
        ),
        "interpretation": interpret(args.margin, args.confidence, required,
                                    population, args.observed, args.reviewed),
        "assumptions": [
            "抽样是随机的，且覆盖全书每个段落的机会均等",
            "复核独立于翻译过程，且复核者能发现被抽段落的错误",
            "段落配对正确；aligned=false 的单元需先处理",
            "已有错误时，所需样本量假设后续复核不再发现新错误",
            "“0 错误”只给出错误率上界，不是绝对无遗漏的证明",
        ],
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"目标：残余错误率 ≤ {args.margin:.2%}，置信度 {args.confidence:.0%}")
    if population:
        print(f"总体：{population} 段；已抽样：{sampled} 段")
    print(f"0 错误所需样本：{required} 段")
    if already:
        print(f"已计入：{already} 段；还需：{additional} 段")
    if rounds and additional:
        print(f"建议 {rounds} 轮，每轮约 {per_round} 段")
    if result["current_upper_bound"] is not None:
        print(f"当前单侧上界：{result['current_upper_bound']:.2%}")
    print(result["interpretation"])
    print("\n前提：")
    for item in result["assumptions"]:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
