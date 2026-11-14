# 翻译工作区 · Translation Toolkit

面向书籍与长文的英译中工作流：Markdown 管理原文，LaTeX（XeLaTeX）排版成书，术语表与脚本保证一致性，质量检查可自动运行。

> **内容边界**：本仓库只包含工具链、文档与空白项目模板，**不包含任何书籍原文、译文或电子书文件**。使用本工具翻译作品前，请自行确认你拥有该作品的翻译与分发授权。

## 它能做什么

- 从 EPUB / PDF / DOCX 抽取章节、图片与脚注为 Markdown，生成完整性清单
- 以 `glossary/terms.csv` 为唯一权威，检查术语一致性与禁用译名
- 一个项目一本书：分章 `.tex`、自动生成目录与术语表、XeLaTeX 编译 PDF
- 自动核对脚注数、图数、节数、TODO 残留、标点与数字
- 把原文参考文献与索引转换为 LaTeX 并纳入成书
- 项目模板 + 脚手架，几分钟内开始一本新书

## 快速开始

环境：Windows + PowerShell 5.1+、TeX Live（XeLaTeX + latexmk）、Python 3.10+。Python 脚本仅用标准库。

```powershell
git clone <this-repo> translation-toolkit
cd translation-toolkit

# 新建项目；若提供 -Source，会尝试自动抽取 EPUB
.\scripts\new-project.ps1 -Name my-book -Title "书名" -Source "D:\books\book.epub"

cd projects\my-book
# 编辑 glossary/terms.csv、notes/context.md、notes/style.md，然后逐章翻译
..\..\scripts\build.ps1          # 生成元数据/参考文献/索引 → 编译 → 质量检查
..\..\scripts\build.ps1 -Clean -Open
```

产物在 `projects/<slug>/dist/<slug>.pdf`。

## 目录结构

```
translation-toolkit/
├─ CLAUDE.md                 给 AI 助手的协作约定
├─ docs/                     工作流、翻译规范、质检清单、排版规范
├─ scripts/
│  ├─ new-project.ps1        新建项目脚手架
│  ├─ build.ps1              一键构建
│  ├─ epub_extract.py        EPUB 抽取
│  ├─ scaffold.py            生成逐章 LaTeX 骨架
│  ├─ prepare.py             元信息、章序、术语表
│  ├─ backmatter.py          参考文献与索引
│  ├─ check.py               项目级质量检查
│  ├─ global_check.py        全书结构核对
│  ├─ term_candidates.py     术语候选提取
│  └─ init_project.py        写入元数据
├─ _template/                项目模板（不要直接在这里翻译）
└─ projects/                 你的项目（.gitignore 已忽略）
```

每个项目内部：

```
project/
├─ main.tex / preamble.tex   总装与版式
├─ project.json              书目元数据（唯一来源）
├─ frontmatter/              封面、版权页、献词、译者说明、致谢
├─ chapters/                 译文分章
├─ backmatter/               术语表、参考文献、索引、译后记
├─ glossary/terms.csv        术语库（唯一权威）
├─ notes/                    背景卷宗、风格表、决策、进度、审校记录
├─ source/                   原文抽取结果（只读）
├─ generated/                脚本生成，勿手改
├─ build/                    编译中间文件
└─ dist/                     最终 PDF
```

## 标准流程

| 阶段 | 名称 | 产出 | 质量门 |
|---|---|---|---|
| 0 | 立项与原文抽取 | `project.json`、`source/` | 章节/图/脚注数量核对 |
| 1 | 通读与背景卷宗 | `notes/context.md`、逐章摘要 | G1 全局理解 |
| 2 | 术语提取与定名 | `glossary/terms.csv` v1 | G2 术语冻结 |
| 3 | 试译校准 | 1000–2000 字样章、风格表 | G3 风格确认 |
| 4 | 分章初译 | `chapters/*.tex` | 每章自检 |
| 5 | 双语审校 | 审校记录、修订稿 | G4 准确性 |
| 6 | 单语润色 | 定稿 | G5 可读性 |
| 7 | 排版与终检 | PDF 校样 | G6 交付 |

三条铁律：

1. **术语表是法律。** 已定名术语不得临时发挥；新术语先入表再使用。
2. **原文是唯一依据。** 不遗漏、不增写、不“顺”掉信息；歧义保留并在译者注中说明。
3. **注释和配图是正文的一部分。** 原文脚注、图注、表格、题词、献词都必须落地，数量可自动核对。

详见 [`docs/01-工作流.md`](docs/01-工作流.md)、[`docs/02-翻译规范.md`](docs/02-翻译规范.md)、[`docs/03-质检清单.md`](docs/03-质检清单.md)、[`docs/04-排版规范.md`](docs/04-排版规范.md)。

## 已知限制

- 构建脚本以 Windows PowerShell 为主；macOS/Linux 可手动执行 `prepare.py`、`backmatter.py`、`latexmk`，或自行改写 `build.ps1`。
- 字体默认使用 Windows 自带 SimSun/SimHei；其他系统需修改 `preamble.tex`。
- 索引保留原书页码，不重映射到译文分页。

## 许可证

代码与文档以 MIT 许可证发布，见 [`LICENSE`](LICENSE)。通过本工具产生的译文，其版权归译者与原作者/权利人所有，不在本许可证覆盖范围内。
