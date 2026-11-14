#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""随机抽样复核：把全书拆成段落对，分轮抽样，记录发现并估计残余错误率。

它不替你做判断，而是把“随机抽样 + 重复实验”变成可复现的流程：
- inventory：把每章切成源文段落与译文段落的配对清单；
- plan：按轮次随机抽样，默认不重复抽同一段；
- record：记录每段的复核结果（ok / 漏译 / 误译 / 术语 / 数字 / 脚注 / 风格）；
- stats：给出覆盖率、错误率、Wilson 95% 区间、每轮新增错误与停止建议；
- report：生成 Markdown 报告。

用法：
    python scripts/audit.py inventory --project .
    python scripts/audit.py plan --project . --size 20 --seed 42 --round 1 --json
    python scripts/audit.py record --project . --id ch03:p012 --result omission --note "漏了第二句"
    python scripts/audit.py stats --project . --json
    python scripts/audit.py report --project .

数据文件（均在项目 notes/audit/ 下）：
    segments.json      段落配对清单（可重建）
    sample-log.csv     每轮抽到的段落
    findings.csv       复核结果
    report.md          统计报告

退出码：0 = 成功；1 = 参数/数据错误。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check import chapter_pairs, load_terms, read_text, strip_latex  # noqa: E402

AUDIT_DIR = "notes/audit"
RESULTS = ["ok", "omission", "mistranslation", "terminology",
           "number", "footnote", "style", "other"]
ENGLISH_RUN = re.compile(r"(?:[A-Za-z][A-Za-z'’\-]*[ \t]+){7,}[A-Za-z][A-Za-z'’\-]*")
NUMBER = re.compile(r"\d{2,}")


# ----------------------------------------------------------------------
# 数据文件
# ----------------------------------------------------------------------
def audit_dir(project: Path) -> Path:
    path = project / AUDIT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(fh)]


def append_csv(path: Path, fields: list[str], row: dict) -> None:
    exists = path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# 段落配对
# ----------------------------------------------------------------------
def split_paragraphs(text: str, min_chars: int = 8) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [b for b in blocks
            if len(b) >= min_chars
            and not re.fullmatch(r"#{1,6}\s+.+", b)]


def clip(text: str, max_chars: int) -> str:
    return text if max_chars <= 0 else text[:max_chars]


def auto_flags(source: str, target: str, terms: list[dict]) -> list[str]:
    flags = []
    if not target.strip():
        flags.append("target_missing")
        return flags
    if "（待译）" in target or "\\todo{" in target:
        flags.append("placeholder")
    # 脚注引用会带来数字噪声，先剔除
    src_clean = re.sub(r"\[\^\d+\]|\\footnote\{[^}]*\}", "", source)
    tgt_clean = re.sub(r"\[\^\d+\]|〔原注〕|〔译注〕", "", target)
    src_nums = set(NUMBER.findall(src_clean))
    tgt_nums = set(NUMBER.findall(tgt_clean))
    if src_nums - tgt_nums:
        flags.append("numbers_missing:" + ",".join(sorted(src_nums - tgt_nums)[:5]))
    if ENGLISH_RUN.search(target):
        flags.append("english_residue")
    for term in terms:
        src = (term.get("source") or "").strip()
        tgt = (term.get("target") or "").strip()
        if not src or not tgt or (term.get("status") or "").lower() != "final":
            continue
        if src.lower() in source.lower() and tgt not in target:
            flags.append(f"term_missing:{tgt}")
            break
    return flags


PAIR_SECTION = re.compile(r"^=====\s*(.+?)\s*=====\s*$")
PAIR_SOURCE = re.compile(r"^---\s*源\s*(\d+)\s*---\s*$")
PAIR_TARGET = re.compile(r"^---\s*译\s*(\d+)\s*---\s*$")


def parse_pairs_file(path: Path) -> list[dict]:
    """解析双语审校生成的 _chNN_pairs.md。

    返回 [{title, pairs: {n: {source, target}}, aligned}]。
    """
    sections: list[dict] = []
    section = {"title": "", "pairs": {}, "aligned": True}
    number = None
    kind = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal number, kind, buf
        if number is not None and kind:
            section["pairs"].setdefault(number, {})[kind] = "\n".join(buf).strip()
        number, kind, buf = None, None, []

    for line in read_text(path).splitlines():
        match = PAIR_SECTION.match(line)
        if match:
            flush()
            if section["pairs"]:
                sections.append(section)
            section = {"title": match.group(1).strip(), "pairs": {}, "aligned": True}
            continue
        match = PAIR_SOURCE.match(line)
        if match:
            flush()
            number, kind = int(match.group(1)), "source"
            continue
        match = PAIR_TARGET.match(line)
        if match:
            flush()
            number, kind = int(match.group(1)), "target"
            continue
        if kind:
            buf.append(line)
    flush()
    if section["pairs"]:
        sections.append(section)

    for item in sections:
        sources = {n for n, pair in item["pairs"].items() if pair.get("source")}
        targets = {n for n, pair in item["pairs"].items() if pair.get("target")}
        item["aligned"] = sources == targets and bool(sources)
    return sections


def take_group(text: str, index: int) -> tuple[str, int]:
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


def remove_braced_macros(text: str, names: set[str]) -> str:
    """删除 \\name{...} 及其内容，支持嵌套花括号。"""
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\":
            j = i + 1
            while j < len(text) and (text[j].isalpha() or text[j] == "@"):
                j += 1
            name = text[i + 1:j]
            if name in names:
                k = j
                while k < len(text) and text[k] in " \t\n":
                    k += 1
                if k < len(text) and text[k] == "[":
                    close = text.find("]", k)
                    k = close + 1 if close >= 0 else k
                if k < len(text) and text[k] == "{":
                    _, k = take_group(text, k)
                    i = k
                    continue
            out.append(text[i:j])
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def normalize_match(text: str) -> str:
    """用于判断对照文件是否仍与正文一致。"""
    text = re.sub(r"〔原注〕|〔译注〕|〔章〕", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def strip_footnotes(text: str) -> str:
    return remove_braced_macros(text, {"footnote", "zhu"})


def chapter_norm(tex_path: Path) -> str:
    text = strip_footnotes(read_text(tex_path))
    return normalize_match(strip_latex(text))


def chapter_blocks(tex_path: Path) -> list[tuple[str, str]]:
    """当前正文的段落列表：[(可读文本, 归一化文本)]。"""
    text = strip_footnotes(read_text(tex_path))
    text = strip_latex(text)
    blocks = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        norm = normalize_match(block)
        if norm:
            blocks.append((block, norm))
    return blocks


def bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def best_block(target_norm: str, blocks: list[tuple[str, str]]) -> tuple[str, float]:
    target_set = bigrams(target_norm)
    best_text, best_score = "", 0.0
    for text, norm in blocks:
        score = jaccard(target_set, bigrams(norm))
        if score > best_score:
            best_text, best_score = text, score
    return best_text, best_score


def build_inventory_from_pairs(project: Path, stem: str, pairs_path: Path,
                               terms: list[dict], max_chars: int,
                               current_norm: str = "",
                               current_blocks: list[tuple[str, str]] | None = None) -> dict:
    current_blocks = current_blocks or []
    sections = parse_pairs_file(pairs_path)
    segments = []
    seq = 0
    for section in sections:
        for n in sorted(section["pairs"]):
            pair = section["pairs"][n]
            source = pair.get("source", "")
            target = pair.get("target", "")
            if not source and not target:
                continue
            seq += 1
            target_norm = normalize_match(target)
            refreshed = False
            match_score = 0.0
            stale = False
            if current_norm and target_norm:
                if target_norm in current_norm:
                    match_score = 1.0
                else:
                    candidate, score = best_block(target_norm, current_blocks)
                    match_score = round(score, 4)
                    if score >= 0.5:
                        target = candidate
                        refreshed = True
                    else:
                        stale = True
            segments.append({
                "id": f"{stem}:p{seq:03d}",
                "unit": stem,
                "index": seq,
                "section": section["title"],
                "source": clip(source, max_chars),
                "target": clip(target, max_chars),
                "source_chars": len(source),
                "target_chars": len(target),
                "aligned": section["aligned"],
                "target_stale": stale,
                "target_refreshed": refreshed,
                "target_match": match_score,
                "auto_flags": auto_flags(source, target, terms),
            })
    return {
        "unit": stem,
        "source_paragraphs": sum(1 for s in sections for p in s["pairs"].values()
                                 if p.get("source")),
        "target_paragraphs": sum(1 for s in sections for p in s["pairs"].values()
                                 if p.get("target")),
        "aligned": all(s["aligned"] for s in sections) if sections else False,
        "source": "pairs",
        "stale_targets": sum(1 for s in segments if s["target_stale"]),
        "refreshed_targets": sum(1 for s in segments if s.get("target_refreshed")),
        "segments": segments,
    }


def build_inventory(project: Path, max_chars: int) -> dict:
    terms = load_terms(project / "glossary" / "terms.csv")
    units = []
    total = 0
    for stem, src_path, tex_path in chapter_pairs(project):
        if src_path is None or tex_path is None:
            continue
        pairs_file = project / "notes" / f"_{stem}_pairs.md"
        if pairs_file.exists():
            unit = build_inventory_from_pairs(
                project, stem, pairs_file, terms, max_chars,
                current_norm=chapter_norm(tex_path),
                current_blocks=chapter_blocks(tex_path))
            total += len(unit["segments"])
            units.append(unit)
            continue
        source_paras = split_paragraphs(read_text(src_path))
        target_paras = split_paragraphs(strip_latex(read_text(tex_path)))
        aligned = len(source_paras) == len(target_paras)
        segments = []
        for idx, source in enumerate(source_paras):
            target = target_paras[idx] if idx < len(target_paras) else ""
            segments.append({
                "id": f"{stem}:p{idx + 1:03d}",
                "unit": stem,
                "index": idx + 1,
                "source": clip(source, max_chars),
                "target": clip(target, max_chars),
                "source_chars": len(source),
                "target_chars": len(target),
                "aligned": aligned,
                "auto_flags": auto_flags(source, target, terms),
            })
        total += len(segments)
        units.append({
            "unit": stem,
            "source_paragraphs": len(source_paras),
            "target_paragraphs": len(target_paras),
            "aligned": aligned,
            "segments": segments,
        })
    return {
        "generated_at": now(),
        "max_chars": max_chars,
        "total_segments": total,
        "stale_targets": sum(u.get("stale_targets", 0) for u in units),
        "refreshed_targets": sum(u.get("refreshed_targets", 0) for u in units),
        "units": units,
    }


def load_inventory(project: Path, refresh: bool = False,
                   max_chars: int = 0) -> dict:
    path = audit_dir(project) / "segments.json"
    if refresh or not path.exists():
        inventory = build_inventory(project, max_chars)
        write_json(path, inventory)
        return inventory
    return read_json(path, {})


def segment_index(inventory: dict) -> dict[str, dict]:
    return {seg["id"]: seg for unit in inventory.get("units", [])
            for seg in unit.get("segments", [])}


# ----------------------------------------------------------------------
# 抽样
# ----------------------------------------------------------------------
def allocate(pools: dict[str, list[dict]], size: int) -> dict[str, int]:
    """按各单元剩余段落数比例分配，最大余数法，且尽量每单元至少 1。"""
    total = sum(len(pool) for pool in pools.values())
    if total == 0:
        return {}
    quotas = {unit: size * len(pool) / total for unit, pool in pools.items()}
    allocation = {unit: int(math.floor(q)) for unit, q in quotas.items()}
    remainder = size - sum(allocation.values())
    order = sorted(quotas, key=lambda u: (quotas[u] - allocation[u], len(pools[u])),
                   reverse=True)
    for unit in order[:remainder]:
        allocation[unit] += 1
    # 不给空池分配
    for unit in list(allocation):
        if not pools[unit]:
            allocation[unit] = 0
    while sum(allocation.values()) > size:
        unit = max(allocation, key=lambda u: allocation[u])
        allocation[unit] -= 1
    for unit, count in allocation.items():
        allocation[unit] = min(count, len(pools[unit]))
    return allocation


def plan_round(project: Path, size: int, seed: int, round_no: int,
               unit_filter: str = "", with_replacement: bool = False,
               refresh: bool = False, max_chars: int = 0,
               aligned_only: bool = True) -> dict:
    inventory = load_inventory(project, refresh=refresh, max_chars=max_chars)
    segments = segment_index(inventory)
    log_path = audit_dir(project) / "sample-log.csv"
    sampled_before = {row["id"] for row in read_csv(log_path)}

    pools: dict[str, list[dict]] = {}
    for unit in inventory.get("units", []):
        if unit_filter and unit["unit"] != unit_filter:
            continue
        pool = [s for s in unit["segments"]
                if (not aligned_only or s.get("aligned", True))
                and not s.get("target_stale", False)
                and (with_replacement or s["id"] not in sampled_before)]
        if pool:
            pools[unit["unit"]] = pool

    eligible = sum(1 for s in segments.values()
                   if (not aligned_only or s.get("aligned", True))
                   and not s.get("target_stale", False))

    available = sum(len(pool) for pool in pools.values())
    if available == 0:
        return {"ok": False, "exit_code": 1,
                "error": "没有可抽样的段落；若要重复抽样，请加 --with-replacement"}
    target_size = min(size, available)
    allocation = allocate(pools, target_size)

    rng = random.Random(f"{seed}:{round_no}:{unit_filter}")
    tasks = []
    for unit in sorted(allocation):
        count = allocation[unit]
        if count <= 0:
            continue
        for seg in rng.sample(pools[unit], count):
            tasks.append({
                "id": seg["id"],
                "unit": seg["unit"],
                "index": seg["index"],
                "source": seg["source"],
                "target": seg["target"],
                "aligned": seg["aligned"],
                "auto_flags": seg["auto_flags"],
            })

    for task in tasks:
        append_csv(log_path,
                   ["round", "id", "unit", "parameter", "sampled_at"],
                   {"round": round_no, "id": task["id"], "unit": task["unit"],
                    "parameter": f"seed={seed};size={size}", "sampled_at": now()})

    result = {
        "ok": True,
        "exit_code": 0,
        "round": round_no,
        "seed": seed,
        "requested": size,
        "sampled": len(tasks),
        "available_before": available,
        "with_replacement": with_replacement,
        "coverage": {
            "total_segments": len(segments),
            "eligible_segments": eligible,
            "sampled_unique": len(sampled_before) + len({t['id'] for t in tasks
                                                         if t['id'] not in sampled_before}),
            "ratio": round((len(sampled_before)
                            + len({t['id'] for t in tasks if t['id'] not in sampled_before}))
                           / max(1, eligible), 4),
        },
        "tasks": tasks,
    }
    out = audit_dir(project) / f"round-{round_no}.json"
    write_json(out, result)
    result["plan_file"] = str(out)
    return result


# ----------------------------------------------------------------------
# 统计
# ----------------------------------------------------------------------
def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def compute_stats(project: Path, min_coverage: float, quiet_rounds: int) -> dict:
    inventory = load_inventory(project)
    segments = segment_index(inventory)
    log = read_csv(audit_dir(project) / "sample-log.csv")
    findings = read_csv(audit_dir(project) / "findings.csv")

    latest: dict[str, dict] = {}
    for row in findings:
        prev = latest.get(row["id"])
        if prev is None or prev.get("result") == "ok" or row.get("result") != "ok":
            latest[row["id"]] = row  # 错误优先保留，不被后来的 ok 覆盖
    logged_ids = {row["id"] for row in log}
    reviewers = sorted({row.get("reviewer") or "default" for row in findings})

    units = []
    for unit in inventory.get("units", []):
        active_ids = [s["id"] for s in unit["segments"]
                      if not s.get("target_stale")]
        sampled = [i for i in active_ids if i in logged_ids]
        reviewed = [i for i in active_ids if i in latest]
        errors = [i for i in reviewed if latest[i]["result"] != "ok"]
        units.append({
            "unit": unit["unit"],
            "segments": len(active_ids),
            "eligible": sum(1 for s in unit["segments"]
                            if s.get("aligned", True)
                            and not s.get("target_stale")),
            "stale": sum(1 for s in unit["segments"] if s.get("target_stale")),
            "sampled": len(sampled),
            "reviewed": len(reviewed),
            "errors": len(errors),
            "aligned": unit["aligned"],
            "source_paragraphs": unit["source_paragraphs"],
            "target_paragraphs": unit["target_paragraphs"],
        })

    reviewed_ids = [i for i in latest if not segments[i].get("target_stale")]
    error_ids = [i for i in reviewed_ids if latest[i]["result"] != "ok"]
    n, k = len(reviewed_ids), len(error_ids)
    ci = wilson(k, n)
    total_all = len(segments)
    total = sum(1 for s in segments.values()
                if s.get("aligned", True) and not s.get("target_stale"))

    rounds = sorted({int(r["round"]) for r in log if r.get("round", "").isdigit()})
    by_round = []
    seen_errors: set[str] = set()
    for round_no in rounds:
        round_ids = {r["id"] for r in log if r.get("round") == str(round_no)}
        round_reviewed = [i for i in round_ids if i in latest]
        round_errors = {i for i in round_reviewed if latest[i]["result"] != "ok"}
        new_errors = round_errors - seen_errors
        seen_errors |= round_errors
        by_round.append({
            "round": round_no,
            "sampled": len(round_ids),
            "reviewed": len(round_reviewed),
            "errors_found": len(round_errors),
            "error_rate": round(len(round_errors) / len(round_reviewed), 4)
            if round_reviewed else 0.0,
            "new_errors": len(new_errors),
        })

    last_quiet = (len(by_round) >= quiet_rounds
                  and all(r["new_errors"] == 0 for r in by_round[-quiet_rounds:]))
    coverage = round(len({r["id"] for r in log}) / max(1, total), 4)
    stop = bool(last_quiet and coverage >= min_coverage)
    rate = round(k / n, 4) if n else 0.0
    estimated = {
        "point": round(rate * total, 1),
        "low": round(ci[0] * total, 1),
        "high": round(ci[1] * total, 1),
    }
    if stop:
        reason = (f"最近 {quiet_rounds} 轮无新增错误，"
                  f"覆盖率 {coverage:.1%} ≥ {min_coverage:.0%}")
    elif len(by_round) < quiet_rounds:
        reason = f"继续抽样：已完成 {len(by_round)} 轮，少于 {quiet_rounds} 轮"
    elif coverage < min_coverage:
        reason = f"继续抽样：覆盖率 {coverage:.1%} 低于 {min_coverage:.0%}"
    else:
        reason = f"继续抽样：最近 {quiet_rounds} 轮仍有新增错误"
    return {
        "ok": True,
        "exit_code": 0,
        "total_segments": total,
        "total_segments_all": total_all,
        "sampled": len({r["id"] for r in log}),
        "reviewed": n,
        "reviewers": reviewers,
        "coverage": coverage,
        "errors": k,
        "error_rate": rate,
        "error_rate_ci95": ci,
        "estimated_residual_errors": estimated,
        "small_sample": n < 5,
        "rounds": by_round,
        "units": units,
        "stop_recommended": stop,
        "stop_reason": reason,
    }


def markdown_report(stats: dict) -> str:
    lines = [
        "# 随机抽样复核报告",
        "",
        f"- 段落总数：{stats['total_segments']}",
        f"- 已抽样：{stats['sampled']}（覆盖率 {stats['coverage']:.1%}）",
        f"- 已复核：{stats['reviewed']}；发现错误：{stats['errors']}",
        f"- 复核者：{', '.join(stats.get('reviewers') or ['default'])}",
        f"- 错误率：{stats['error_rate']:.1%}（95% CI "
        f"{stats['error_rate_ci95'][0]:.1%}–{stats['error_rate_ci95'][1]:.1%}）",
        f"- 估计残余错误：{stats['estimated_residual_errors']['point']} 段"
        f"（区间 {stats['estimated_residual_errors']['low']}–"
        f"{stats['estimated_residual_errors']['high']}）",
        "",
    ]
    if stats.get("small_sample"):
        lines += ["> 样本量小于 5，区间很宽，仅作方向参考；继续抽样后再看结论。", ""]
    lines += [
        "## 每轮",
        "",
        "| 轮次 | 抽样 | 复核 | 错误 | 错误率 | 新增错误 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in stats["rounds"]:
        lines.append(f"| {row['round']} | {row['sampled']} | {row.get('reviewed', 0)} | "
                     f"{row['errors_found']} | {row.get('error_rate', 0):.1%} | "
                     f"{row['new_errors']} |")
    lines += ["", "## 分单元", "",
              "| 单元 | 段落 | 可抽 | 抽样 | 复核 | 错误 | 对齐 |",
              "|---|---:|---:|---:|---:|---:|---|"]
    for row in stats["units"]:
        lines.append(f"| {row['unit']} | {row['segments']} | {row.get('eligible', row['segments'])} | "
                     f"{row['sampled']} | {row['reviewed']} | {row['errors']} | "
                     f"{'是' if row['aligned'] else '否'} |")
    lines += ["", "## 结论", "", stats["stop_reason"], ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="随机抽样复核")
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="重建段落配对清单")
    inv.add_argument("--project", default=".")
    inv.add_argument("--refresh", action="store_true")
    inv.add_argument("--max-chars", type=int, default=0)
    inv.add_argument("--json", action="store_true")

    verify = sub.add_parser("verify", help="校验对照文件是否仍与正文一致")
    verify.add_argument("--project", default=".")
    verify.add_argument("--strict", action="store_true",
                        help="存在 stale 时返回退出码 1")
    verify.add_argument("--json", action="store_true")

    plan = sub.add_parser("plan", help="生成一轮抽样")
    plan.add_argument("--project", default=".")
    plan.add_argument("--size", type=int, default=20)
    plan.add_argument("--seed", type=int, default=20261114)
    plan.add_argument("--round", type=int, default=1)
    plan.add_argument("--unit", default="")
    plan.add_argument("--with-replacement", action="store_true")
    plan.add_argument("--refresh", action="store_true")
    plan.add_argument("--max-chars", type=int, default=0)
    plan.add_argument("--include-unaligned", action="store_true",
                      help="连段落数不匹配的段落一起抽样（默认跳过）")
    plan.add_argument("--json", action="store_true")

    rec = sub.add_parser("record", help="记录一条复核结果")
    rec.add_argument("--project", default=".")
    rec.add_argument("--id", required=True)
    rec.add_argument("--result", required=True, choices=RESULTS)
    rec.add_argument("--note", default="")
    rec.add_argument("--round", type=int, default=0)
    rec.add_argument("--reviewer", default="default",
                     help="复核者标识；多人复核时用于区分记录")
    rec.add_argument("--json", action="store_true")

    stats = sub.add_parser("stats", help="统计与停止建议")
    stats.add_argument("--project", default=".")
    stats.add_argument("--min-coverage", type=float, default=0.1)
    stats.add_argument("--quiet-rounds", type=int, default=3)
    stats.add_argument("--json", action="store_true")

    rep = sub.add_parser("report", help="生成 Markdown 报告")
    rep.add_argument("--project", default=".")
    rep.add_argument("--out", default="")
    rep.add_argument("--min-coverage", type=float, default=0.1)
    rep.add_argument("--quiet-rounds", type=int, default=3)

    args = parser.parse_args()
    project = Path(args.project).resolve()

    if not (project / "project.json").exists():
        print(f"[错误] {project} 不是项目目录（缺 project.json）")
        return 1

    if args.command == "inventory":
        inventory = load_inventory(project, refresh=True, max_chars=args.max_chars)
        summary = {"ok": True, "exit_code": 0,
                   "total_segments": inventory["total_segments"],
                   "stale_targets": inventory.get("stale_targets", 0),
                   "refreshed_targets": inventory.get("refreshed_targets", 0),
                   "units": [{"unit": u["unit"], "segments": len(u["segments"]),
                              "stale": u.get("stale_targets", 0),
                              "refreshed": u.get("refreshed_targets", 0),
                              "aligned": u["aligned"]} for u in inventory["units"]]}
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(f"段落配对：{summary['total_segments']} 段；"
                  f"对照文件过时：{summary['stale_targets']} 段")
            for row in summary["units"]:
                print(f"  {row['unit']:<12} {row['segments']:>5} 段  "
                      f"过时 {row['stale']:>3}  对齐：{'是' if row['aligned'] else '否'}")
        return 0

    if args.command == "verify":
        inventory = load_inventory(project, refresh=True)
        stale = []
        for unit in inventory.get("units", []):
            for seg in unit.get("segments", []):
                if seg.get("target_stale"):
                    stale.append({"id": seg["id"], "unit": seg["unit"],
                                  "section": seg.get("section", ""),
                                  "target": seg["target"][:120]})
        result = {"ok": bool(not stale or not args.strict),
                  "exit_code": 1 if (stale and args.strict) else 0,
                  "total_segments": inventory["total_segments"],
                  "stale": len(stale),
                  "refreshed": inventory.get("refreshed_targets", 0),
                  "stale_targets": stale}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"对照文件：{inventory['total_segments']} 段，"
                  f"与正文不一致 {len(stale)} 段，"
                  f"已按正文刷新 {result['refreshed']} 段")
            for row in stale[:20]:
                print(f"  {row['id']:<14} {row['section'][:30]}  {row['target'][:50]}")
            if len(stale) > 20:
                print(f"  … 其余 {len(stale) - 20} 段")
        return result["exit_code"]

    if args.command == "plan":
        result = plan_round(project, args.size, args.seed, args.round,
                            args.unit, args.with_replacement, args.refresh,
                            args.max_chars,
                            aligned_only=not args.include_unaligned)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result["ok"]:
            print(f"[audit] 第 {result['round']} 轮：抽 {result['sampled']} 段"
                  f"（覆盖率 {result['coverage']['ratio']:.1%}）")
            for task in result["tasks"][:10]:
                flags = ";".join(task["auto_flags"]) or "-"
                print(f"  {task['id']:<14} 自动标记：{flags}")
            if len(result["tasks"]) > 10:
                print(f"  … 其余 {len(result['tasks']) - 10} 段见 {result['plan_file']}")
        else:
            print(f"[错误] {result['error']}")
        return result["exit_code"]

    if args.command == "record":
        inventory = load_inventory(project)
        if args.id not in segment_index(inventory):
            print(f"[错误] 未知段落 ID：{args.id}（先运行 inventory）")
            return 1
        append_csv(audit_dir(project) / "findings.csv",
                   ["id", "round", "result", "note", "reviewer", "recorded_at"],
                   {"id": args.id, "round": args.round, "result": args.result,
                    "note": args.note, "reviewer": args.reviewer,
                    "recorded_at": now()})
        result = {"ok": True, "exit_code": 0, "id": args.id,
                  "result": args.result}
        print(json.dumps(result, ensure_ascii=False) if args.json
              else f"[audit] 已记录 {args.id}：{args.result}")
        return 0

    if args.command == "stats":
        result = compute_stats(project, args.min_coverage, args.quiet_rounds)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"覆盖率 {result['coverage']:.1%}（{result['sampled']}/"
                  f"{result['total_segments']}）；复核 {result['reviewed']} 段，"
                  f"错误 {result['errors']} 段")
            print(f"错误率 {result['error_rate']:.1%}，95% CI "
                  f"{result['error_rate_ci95'][0]:.1%}–"
                  f"{result['error_rate_ci95'][1]:.1%}")
            print(result["stop_reason"])
        return 0

    if args.command == "report":
        result = compute_stats(project, args.min_coverage, args.quiet_rounds)
        out = Path(args.out).resolve() if args.out else audit_dir(project) / "report.md"
        out.write_text(markdown_report(result), encoding="utf-8")
        print(f"[audit] 报告已写入 {out}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
