#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新新项目的 project.json 元数据（供 new-project.ps1 调用）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--slug", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--author", default="")
    parser.add_argument("--translator", default="")
    parser.add_argument("--source-lang", default="")
    parser.add_argument("--year", default="")
    args = parser.parse_args()

    path = Path(args.dir) / "project.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    mapping = {
        "slug": args.slug,
        "title": args.title,
        "subtitle": args.subtitle,
        "author": args.author,
        "translator": args.translator,
        "source_lang": args.source_lang,
        "year": args.year,
    }
    for key, value in mapping.items():
        if value:
            data[key] = value
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[init] 已更新 {path}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
