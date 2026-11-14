---
name: polish-chapter
description: 单语润色一个章节：不看原文，按中文阅读习惯与所选文风修正翻译腔。Use after review, before final check.
---

# 单语润色

前提：该章已完成双语审校，事实与结构已锁定。润色只改中文表达，不改信息。

## 准备

1. 读 `notes/style.md`、`notes/style.selected.md`（若存在）、`notes/style.md` 的禁用词表。
2. 读该章审校记录，知道哪些地方是刻意保留的“硬”译法。

## 润色规则

- 只读译文，不逐句对照原文；遇到疑似漏译/矛盾，停下来回查原文，不要自行补写。
- 修正翻译腔：欧化长定语、连续“的”、滥用被动、代词冗余、连接词堆叠。
- 按文风档位调整句长与节奏；不得改变命题强度、限定语与反讽。
- 保持术语不变；润色中若发现术语问题，回到术语表流程，不在正文临时改。
- 每个改动都要能回答“为什么”；批量改动写入 `notes/polish-log.md`。

## 验证

```powershell
python ..\..\scripts\check.py --project . --json
```

ERROR 仍为 0；若润色引入术语变体，`check.py` 的 A2 会报错，必须改回。

## 收尾

更新 `notes/polish-log.md` 与 `notes/progress.csv`。不要在本阶段增删脚注或改结构。
