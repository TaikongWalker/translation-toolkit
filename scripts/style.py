#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""思维阁：列出、查看、应用译者文风档位。

用法：
    python scripts/style.py --list
    python scripts/style.py --show academic-faithful
    python scripts/style.py --apply literary-fluent --project projects/my-book
    python scripts/style.py --list --json

--apply 只写入项目，不修改全局档位库：
    notes/style.selected.md   ← 档位正文
    project.json              ← style_id

退出码：0 = 成功；1 = 档位不存在或项目无法写入。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"


def load_index() -> dict:
    path = STYLES_DIR / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def find_profile(style_id: str) -> dict:
    path = STYLES_DIR / style_id / "profile.json"
    if not path.exists():
        raise FileNotFoundError(f"没有名为 {style_id} 的文风档位")
    return json.loads(path.read_text(encoding="utf-8"))


def style_markdown(style_id: str) -> str:
    path = STYLES_DIR / style_id / "STYLE.md"
    if not path.exists():
        raise FileNotFoundError(f"{style_id} 缺少 STYLE.md")
    return path.read_text(encoding="utf-8")


def apply_style(style_id: str, project: Path) -> dict:
    profile = find_profile(style_id)
    body = style_markdown(style_id)
    notes = project / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    selected = notes / "style.selected.md"
    header = (
        f"<!-- 由 scripts/style.py 生成；档位：{style_id}。"
        "项目特有规则仍以 notes/style.md 为准。 -->\n\n"
    )
    selected.write_text(header + body, encoding="utf-8")

    meta_path = project / "project.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    meta["style_id"] = style_id
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "ok": True,
        "exit_code": 0,
        "style_id": style_id,
        "name": profile.get("name", style_id),
        "selected": str(selected.relative_to(project).as_posix()),
        "project": str(project),
        "warning": "实验档位，建议先试译 1000—2000 字再全书应用。"
        if profile.get("status") == "experimental" else "",
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="思维阁 · 译者文风档位")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="列出全部档位")
    group.add_argument("--show", metavar="ID", help="查看档位详情")
    group.add_argument("--apply", metavar="ID", help="应用到项目")
    parser.add_argument("--project", default=".", help="项目目录（配合 --apply）")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读的 JSON（stdout 只有 JSON）")
    args = parser.parse_args()

    try:
        index = load_index()
        if args.list:
            profiles = index.get("profiles", [])
            if args.json:
                print(json.dumps({
                    "ok": True, "exit_code": 0,
                    "name": index.get("name", "思维阁"),
                    "status": index.get("status", ""),
                    "profiles": profiles,
                }, ensure_ascii=False, indent=2))
            else:
                print(f"{index.get('name', '思维阁')}（{index.get('status', '')}）")
                for p in profiles:
                    print(f"  {p['id']:<20} {p['name']:<10} {p['status']:<12} "
                          f"{p.get('summary', '')}")
            return 0

        if args.show:
            profile = find_profile(args.show)
            body = style_markdown(args.show)
            if args.json:
                print(json.dumps({
                    "ok": True, "exit_code": 0,
                    "profile": profile, "markdown": body,
                }, ensure_ascii=False, indent=2))
            else:
                print(body)
            return 0

        project = Path(args.project).resolve()
        if not (project / "project.json").exists():
            raise FileNotFoundError(f"{project} 不是项目目录（缺 project.json）")
        result = apply_style(args.apply, project)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"[思维阁] 已应用：{result['name']}（{result['style_id']}）")
            print(f"  写入 {result['selected']}，并更新 project.json 的 style_id")
            if result["warning"]:
                print(f"  注意：{result['warning']}")
        return 0
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "exit_code": 1, "error": str(exc)},
                             ensure_ascii=False, indent=2))
        else:
            print(f"[错误] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
