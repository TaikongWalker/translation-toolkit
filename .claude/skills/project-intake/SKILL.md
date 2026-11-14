---
name: project-intake
description: 新书立项：从 EPUB 抽取原文、建立 project.json、背景卷宗与术语候选。Use when starting a new translation project.
---

# 立项与原文抽取

前置：确认译者拥有该作品的翻译与使用授权。不要把原文或译文提交到本仓库。

## 步骤

1. 建项目：
   ```powershell
   .\scripts\new-project.ps1 -Name <slug> -Title "中文书名" -Source "D:\books\book.epub"
   ```
   非 EPUB：先按 `docs/01-工作流.md` 阶段 0 处理，再放入 `source/`。

2. 核对抽取完整性：读 `source/manifest.csv`，确认章节数、图数、脚注数与原书一致。不一致时停止，不要开始翻译。

3. 填 `project.json`：书名、副题、作者、原书信息、版权状态。译者名可留空。

4. 写 `notes/context.md`：书目信息、一句话主旨、全书结构、核心概念、风险清单（至少覆盖每章摘要）。

5. 提术语候选并人工定名：
   ```powershell
   python ..\..\scripts\term_candidates.py --project . --json
   ```
   从 `glossary/candidates.csv` 筛选核心概念，查证后写入 `glossary/terms.csv`（`status=final` 或 `draft`）。

6. 选文风（可选）：
   ```powershell
   python ..\..\scripts\style.py --list
   python ..\..\scripts\style.py --apply academic-faithful --project . --json
   ```

7. 状态确认：
   ```powershell
   python ..\..\scripts\status.py --project . --json
   ```

## 完成标准

- `source/manifest.csv` 与建立的项目一致，无缺章、无乱码。
- `project.json` 可解析，`main.tex` 存在。
- `notes/context.md` 每章有摘要与风险点。
- 核心术语 100% 定名，禁用变体已登记。
