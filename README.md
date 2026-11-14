# 翻译工作区 · Translation Toolkit

面向书籍与长文的英译中工作流：Markdown 管理原文，LaTeX（XeLaTeX）排版成书，术语表与脚本保证一致性，质量检查可自动运行。

> **内容边界**：本仓库只包含工具链、文档与空白项目模板，**不包含任何书籍原文、译文或电子书文件**。使用本工具翻译作品前，请自行确认你拥有该作品的翻译与分发授权。

## 它能做什么

- 从常见阅读文本格式抽取章节与清单：EPUB、PDF、TXT、Markdown、HTML、DOCX、ODT、RTF、FB2、MOBI/AZW3
- 以 `glossary/terms.csv` 为唯一权威，检查术语一致性与禁用译名
- 一个项目一本书：分章 `.tex`、自动生成目录与术语表、XeLaTeX 编译 PDF
- 自动核对脚注数、图数、节数、TODO 残留、标点与数字
- 把原文参考文献与索引转换为 LaTeX 并纳入成书
- 项目模板 + 脚手架，几分钟内开始一本新书
- **Agent native**：每个阶段都有 `--json` 命令、稳定退出码与机器契约（`AGENTS.md`、`agent/capabilities.json`）
- **思维阁**：可选择译者文风档位，作为可执行的约束而非模仿（`styles/`）

## 源文件格式

`scripts/extract.py` 是统一抽取入口，按扩展名自动选择后端，输出格式与 EPUB 抽取一致（`source/*.md` + `manifest.csv`）。

| 格式 | 后端 | 说明 |
|---|---|---|
| `.epub` | 内置 | 保留章节、脚注、图片、表格，效果最好 |
| `.pdf` | MarkItDown → pdftotext → PyMuPDF | 三者取其一；扫描版需先 OCR；不保留脚注编号与图片 |
| `.docx` | 内置 / MarkItDown | 内置保留标题样式与脚注位置 |
| `.txt` `.text` `.md` `.markdown` | 内置 | 按 Markdown 标题、`第一章 / Chapter N` 或空行切分 |
| `.html` `.htm` `.xhtml` | MarkItDown / 内置 | 保留标题与段落 |
| `.odt` `.rtf` `.fb2` | 内置 | 基础转换；复杂排版与图片可能丢失 |
| `.mobi` `.azw3` `.azw` | Calibre | 需 `ebook-convert`，先转 EPUB 再抽取 |

可选依赖：

```powershell
pip install "markitdown>=0.1.9"     # PDF/HTML 首选后端
# PDF 备选：安装 poppler（pdftotext）或 pip install pymupdf
# MOBI/AZW3：安装 Calibre
```

> MarkItDown 装在用户 site-packages 时，请用普通模式运行 `python scripts/extract.py`，不要加 `-I`（`-I` 会禁用用户 site-packages）。可用 `--engine native` 强制使用内置后端，或用 `--list-formats` 查看当前可用性。

## 面向 agent

仓库从一开始就按“直接给 agent 用”设计：

- `AGENTS.md`：agent 入口、命令契约、推荐工作循环、硬性规则。
- `agent/capabilities.json`：机器可读的命令索引、读写文件、JSON schema、退出码。
- `agent/schemas/`：`status`、`check`、`global_check` 的 JSON Schema。
- `.claude/skills/`：七个阶段技能，可直接被 Claude Code 调用。
- 所有检查命令支持 `--json`：stdout 只有一份 JSON，日志不混入；退出码 0/1 区分阻断。

一条命令看全书状态：

```powershell
python scripts/status.py --project projects/my-book --json
```

返回项目阶段、术语统计、章节 TODO、`check.py` 与 `global_check.py` 的完整结果，以及阻断项列表。

### 容量控制

长章节或长书容易撞上下文上限。工具默认输出已尽量收紧，仍不够时：

```powershell
python scripts/status.py --project . --json --summary          # 约 1–2 KB
python scripts/check.py --project . --unit ch03 --json         # 只查一章
python scripts/check.py --project . --unit ch03 --json `
  --max-issues 20 --offset 0 --compact                         # 分页取问题
python scripts/global_check.py --project . --json --summary    # 只看结构汇总
python scripts/chunk.py --project . --unit ch03 --out chunks/ch03 --json
```

- `chunk.py` 只在段落边界切分，不拆句子与脚注；`lossless=true` 表示按 `plan.json` 拼回与原文逐字一致。
- 降载只减少输出或单次输入，不摘要、不删减原文。

### 随机抽样复核

用于全书难免漏检时，用可复现的随机抽样估计残余错误率。

```powershell
python scripts/audit.py inventory --project .                 # 建立段落配对清单
python scripts/audit.py plan --project . --size 20 --seed 42 --round 1 --json
python scripts/audit.py record --project . --id ch03:p012 --result omission --note "漏了第二句"
python scripts/audit.py stats --project . --json               # 覆盖率、错误率、95% 区间
python scripts/audit.py report --project .                     # notes/audit/report.md
```

- 段落级配对，按单元分层抽样；默认不重复抽同一段，支持多轮。
- 每段附自动标记：数字缺失、占位、英文残留、术语缺失、译文缺失。
- `stats` 给出 Wilson 95% 区间与估计残余错误数；最近 N 轮无新增错误且覆盖率达标时才建议停止。
- 抽样记录与发现写在 `notes/audit/`，固定 `--seed` 可复现。
- 要独立重复实验而非扩大覆盖，可用 `--with-replacement`。

## 思维阁：选择译者文风

```powershell
python scripts/style.py --list
python scripts/style.py --show academic-faithful
python scripts/style.py --apply plain-modern --project projects/my-book
```

档位是“可执行的风格约束”，不是模仿某位译者：

| id | 名称 | 状态 | 适用 |
|---|---|---|---|
| `academic-faithful` | 学术忠实体 | stable | 学术专著、理论文本（默认） |
| `plain-modern` | 现代平实体 | stable | 普及读物、报告 |
| `literary-fluent` | 文学流畅体 | experimental | 随笔、小说、文学引文 |
| `classical-concise` | 古典凝练体 | experimental | 序跋、题词、史料引文 |

`--apply` 写入 `notes/style.selected.md` 与 `project.json` 的 `style_id`；项目特有的 `notes/style.md` 仍然优先。详见 `styles/README.md`。

> 思维阁目前为实验性功能，风格描述均为本项目自写，不复制任何受版权保护的译文。

## 快速开始

环境：Windows + PowerShell 5.1+、TeX Live（XeLaTeX + latexmk）、Python 3.10+。核心脚本仅用标准库；PDF/HTML 可选安装 MarkItDown。

本工具**不内置翻译模型**：原文抽取、术语、检查与排版由工具负责，译稿由人或 agent 写入 `chapters/*.tex`。agent 可从 `AGENTS.md` 与 `.claude/skills/` 进入。

```powershell
git clone https://github.com/TaikongWalker/translation-toolkit.git
cd translation-toolkit

# 新建项目；按扩展名自动抽取（EPUB/PDF/TXT/MD/HTML/DOCX/ODT/RTF/FB2/MOBI/AZW3）
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
├─ AGENTS.md                 agent 入口：命令契约与工作循环
├─ CLAUDE.md                 给 AI 助手的协作约定
├─ agent/
│  ├─ capabilities.json      机器可读的命令与输出索引
│  └─ schemas/               status / check / global_check 的 JSON Schema
├─ .claude/skills/           阶段技能：立项、初译、审校、润色、终检、选文风、抽样
├─ styles/                   思维阁：译者文风档位
├─ docs/                     工作流、翻译规范、质检清单、排版规范
├─ scripts/
│  ├─ new-project.ps1        新建项目脚手架
│  ├─ build.ps1              一键构建（-Json 输出单行 JSON）
│  ├─ status.py              项目总状态（agent 首选入口）
│  ├─ style.py               思维阁档位管理
│  ├─ chunk.py               长章无损分块
│  ├─ audit.py               随机抽样复核与残余错误估计
│  ├─ extract.py             统一原文抽取（多格式）
│  ├─ epub_extract.py        EPUB 抽取后端
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

## 与同类项目的区别

- **多数开源项目是自动翻译器**（TranslateBooksWithLLMs、wenyi、BabelDOC、docutranslate 等）：输入一本书，调用模型，输出译文。
- **本项目是工作区与工具链**：不调用模型，负责人机协作下的原文抽取、术语治理、审校门禁与 LaTeX 成书。
- **相对 LaTeX 学术工具**（LaTeXTrans、lesia、Joon515 的 book-translator skill）：本项目面向整本书的出版流程——双面排版、脚注、图注、参考文献、索引、术语表，而不只是论文或公式。
- **Agent native**：稳定的 JSON 命令契约、`status.py` 单入口与阶段 skills。
- **思维阁**：可选择的译者文风档位。

## 已知限制

- 构建脚本以 Windows PowerShell 为主；macOS/Linux 可手动执行 `prepare.py`、`backmatter.py`、`latexmk`，或自行改写 `build.ps1`。
- 字体默认使用 Windows 自带 SimSun/SimHei；其他系统需修改 `preamble.tex`。
- 索引保留原书页码，不重映射到译文分页。
- PDF / RTF / ODT 抽取不保留完整脚注与图片；扫描版 PDF 需先 OCR。
- MOBI/AZW3 依赖 Calibre 的 `ebook-convert`。

## 许可证

代码与文档以 MIT 许可证发布，见 [`LICENSE`](LICENSE)。通过本工具产生的译文，其版权归译者与原作者/权利人所有，不在本许可证覆盖范围内。
