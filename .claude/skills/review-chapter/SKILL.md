---
name: review-chapter
description: 双语审校一个章节：逐句对照原文与译文，查漏译、反义、数字/事实错误，记录修订。Use when reviewing a translated chapter against the source.
---

# 双语审校

原则：初译与审校必须是两个独立的“脑子”。只拿原文与译文对照，不沿用初译时的推理。

## 准备

1. 读原文 `source/<stem>.md` 与译文 `chapters/<stem>.tex`。
2. 读 `glossary/terms.csv`、`notes/style.md`、`notes/style.selected.md`。
3. 读该章的历史审校记录（`notes/review-*.md`），避免重复已解决的问题。

## 检查顺序

1. **结构**：段落、节、脚注、图、表格数量与原文一一对应。
2. **意义**：漏译、误译、反义、主语/时态/限定语丢失。
3. **事实**：年份、数字、人名、地名、机构名、引文页码。
4. **术语**：与术语表完全一致；新术语是否已入表。
5. **注释**：原注齐全；译注只用于背景、双关、译名理由，独立编号。
6. **风格**：是否符合所选文风档位，不把反讽改成直陈。

## 输出

- 直接修改 `chapters/<stem>.tex`，或在审校记录中列出问题与理由。
- 写 `notes/review-<stem>.md`：问题数、修正数、存疑项、未解决项。
- 所有事实性存疑不改正文，记录到 `notes/decisions.md`，必要时加译者注。

## 验证

```powershell
python ..\..\scripts\check.py --project . --json
python ..\..\scripts\global_check.py --project . --json
```

ERROR 清零；该章数量核对通过。更新 `notes/progress.csv` 为“审校”完成。
