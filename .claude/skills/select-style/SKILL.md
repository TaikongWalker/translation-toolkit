---
name: select-style
description: 思维阁选档：列出译者文风档位、查看约束、应用到项目并写入 style_id。Use when choosing or changing the translation style.
---

# 思维阁 · 选择文风

## 列出档位

```powershell
python ..\..\scripts\style.py --list --json
```

字段：`id`、`name`、`status`（stable / experimental）、`tags`、`summary`。

## 查看档位

```powershell
python ..\..\scripts\style.py --show academic-faithful --json
```

返回结构化 `profile` 与完整 `markdown`。重点读：句法、词汇、标点、注释政策、禁止项、交稿前自检。

## 应用

```powershell
python ..\..\scripts\style.py --apply <id> --project . --json
```

写入：

- `notes/style.selected.md`：档位正文，翻译与润色时先读它；
- `project.json` 的 `style_id`。

不覆盖 `notes/style.md`。项目特有规则仍以 `notes/style.md` 为准；冲突时记录到 `notes/decisions.md`。

## 选择建议

- 学术专著、理论文本 → `academic-faithful`（默认）
- 普及读物、报告 → `plain-modern`
- 随笔、小说、文学引文 → `literary-fluent`（实验）
- 序跋、题词、史料引文 → `classical-concise`（实验）

实验档位用于整本书前，先做 1000—2000 字试译并由人工确认。

## 边界

风格是约束，不是模仿。不要复制任何具体译者的译文；不得为风格增删信息或改变原意。
