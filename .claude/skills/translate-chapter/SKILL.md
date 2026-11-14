---
name: translate-chapter
description: 初译一个章节：对照 source/<stem>.md，产出 chapters/<stem>.tex，脚注/图/节与原文一致。Use when translating one chapter.
---

# 单章初译

输入：一个翻译单元（`source/chNN.md` 或 `source/conclusion.md`）及其目标 `chapters/chNN.tex`。

## 准备

1. 读 `notes/context.md` 对应章摘要、`notes/style.md`、`notes/style.selected.md`（若存在）、`glossary/terms.csv`。
2. 读 `check.py --project . --json` 的当前结果，确认此前没有遗留错误。
3. 确认目标章状态：`notes/progress.csv` 中为“未开始”或“初译”。
4. 若原文超过约 6000 字符，先切块再翻译：
   ```powershell
   python ..\..\scripts\chunk.py --project . --unit <stem> --out chunks/<stem> --json
   ```
   按 `c001.md`…逐块翻译，块间共享术语表与相邻段落，不摘要原文；最后按 `plan.json` 顺序合并为 `chapters/<stem>.tex`。

## 翻译

- 逐段对应：不合并、不拆分段落（确需调整时记录到 `notes/decisions.md`）。
- 原书脚注全部保留，编号与原文对应；译者注用 `\zhu{}`。
- 术语以 `glossary/terms.csv` 为准；新术语先入表，再写进译文。
- 图注、表注、来源行、题词、献词都要译；图号沿用原书。
- 风格遵循已选文风档位；`notes/style.md` 的项目特有规定优先。
- 不确定处写 `%% TODO: 原因` 或 `\todo{原因}`，不要硬译。

## 自检

```powershell
python ..\..\scripts\check.py --project . --json
python ..\..\scripts\global_check.py --project . --json
```

- `check.py` 的 ERROR 必须为 0。
- `global_check` 中该章的节/脚注/图数量必须与原章一致，TODO 为 0。
- 章内术语抽查 10 条，与术语表一致。

## 收尾

更新 `notes/progress.csv` 该章状态为“初译”或下一阶段；把取舍写入 `notes/decisions.md`。不要在本阶段润色。
