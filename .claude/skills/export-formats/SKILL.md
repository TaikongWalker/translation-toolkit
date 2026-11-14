---
name: export-formats
description: 导出 PDF 之外的格式：Markdown、HTML、EPUB、DOCX（Pandoc）。Use when the user asks for ebook, Word, HTML or Markdown output.
---

# 多格式导出

PDF 由 `build.ps1` 生成；其他格式由 `export.py` 通过 Pandoc 从同一份 LaTeX 稿导出。

## 检查依赖

```powershell
python ..\..\scripts\export.py --check --json
```

没有 Pandoc 时提示安装：`winget install JohnMacFarlane.Pandoc`。

## 导出

```powershell
python ..\..\scripts\export.py --project . --format md --json
python ..\..\scripts\export.py --project . --format html --json
python ..\..\scripts\export.py --project . --format epub --json
python ..\..\scripts\export.py --project . --format docx --json
python ..\..\scripts\export.py --project . --format all --json
```

- 输出到 `dist/<slug>.<ext>`
- `--include-backmatter` 连同术语表、参考文献、索引一起导出
- EPUB/DOCX 嵌入图片；HTML 使用 `--embed-resources`
- 章节自动编号“第一章 …”，脚注、译者注、图注保留

## 质量边界

- 版式会简化：精确分页、双栏索引、字体排印只在 PDF 中保留。
- 导出后应目视检查 EPUB/DOCX 的目录、图片与脚注。
- 不要把导出格式当作排版终稿；终稿仍以 PDF 为准。
