# 翻译工作区 · AI 协作约定

本仓库是书籍/长文翻译工作区（工具链与模板）。每次会话开始，先读本文件与 `AGENTS.md`（agent 命令契约），再按任务读 `docs/` 对应文档。

> 仓库不包含任何书籍原文或译文。项目目录 `projects/` 已被 `.gitignore` 忽略；不要把受版权保护的作品内容提交到公开仓库。

## 语言与角色

- 所有解释、审校记录、提交说明用**中文**；术语、代码、LaTeX 命令保留原文。
- 默认翻译方向：英文 → 简体中文；项目可在 `project.json` 覆盖。
- 你是译者/审校，不是作者：不增写、不删减、不替作者补充观点。

## 开始任何翻译任务前

1. 读项目 `notes/context.md`（背景卷宗）与 `notes/style.md`（风格表）。
2. 读 `glossary/terms.csv`；**术语表是唯一权威**。
3. 读 `docs/01-工作流.md` 的对应阶段与质量门。
4. 确认当前章节状态（`notes/progress.csv`），不要跳过审校直接润色。

## 硬性规则

- **不得修改 `source/`**：原文档案只读。需要清洗时复制到别处。
- **新术语先入表**：任何原文概念、人名、地名、机构、作品，先在 `glossary/terms.csv` 定名（`status=final` 或至少 `draft`），再写进译文。
- **已定名术语不得临时改译**；确需改，按 `notes/decisions.md` 的流程：改表 → 旧译入 `forbidden` → 全局替换 → 记录。
- **原书脚注全部保留**，每章从 1 重新编号，与原文对应；译者注用 `\zhu{}`（独立“译注”编号），不要用 `\footnote{译者注：…}`。
- **图注、表注、图内文字说明、来源行都要译**；图号沿用原书。
- **不合并、不删除脚注**；不把长引文改成转述。
- 未确定处写 `%% TODO: 原因` 或 `\todo{…}`，不要硬译；终检前清零。
- 不把英文长句一律拆成短句；保留限定语、逻辑层级、反讽的延迟效果。
- 中文标点全角；引号“”；破折号——；省略号……；不手打中英文间空格。

## 文件约定

- 一章一个文件：`chapters/chNN.tex`，只写正文，不写导言区。
- 章节文件按文件名自然排序，由 `prepare.py` 生成 `generated/chapters.tex`，不要手改该文件。
- 结论用 `\chapter*{结论}` + `\addcontentsline`，不参与编号。
- `generated/` 下所有文件由脚本生成，不要手改。
- 元数据只改 `project.json`；术语只改 `glossary/terms.csv`；决策只记 `notes/decisions.md`。
- 图片放 `figures/`；可直接引用 `source/images/`。

## 常用命令

```powershell
# 在项目目录
..\..\scripts\build.ps1                  # 生成 + 编译 + 检查
..\..\scripts\build.ps1 -Clean -Open     # 完整重编并打开
python ..\..\scripts\check.py --project . --summary
python ..\..\scripts\check.py --project . --json
python ..\..\scripts\status.py --project . --json
python ..\..\scripts\style.py --list
python ..\..\scripts\style.py --apply academic-faithful --project .
python ..\..\scripts\global_check.py --project .
python ..\..\scripts\term_candidates.py --project .
python ..\..\scripts\prepare.py --project .
python ..\..\scripts\backmatter.py --project .
```

- 构建成功看 `dist/<slug>.pdf`；PDF 被占用时会写时间戳副本。
- 质量检查退出码：0 无错误，1 有阻断性错误（A2/A4/A5/A6/A11/A12）。

## 质量门（简化版）

| 阶段 | 必须做到 |
|---|---|
| 通读 | 每章摘要、核心概念、风险清单写进 `context.md` |
| 术语 | 核心词 100% 定名；禁用变体登记 |
| 初译 | 段落/脚注/图数量与原文一致；无未处理 TODO |
| 审校 | 漏译、反义、数字/事实错误为零 |
| 润色 | 朗读通过；无翻译腔；风格与 `style.md` 一致 |
| 终检 | `check.py` 无错误；PDF 目视检查通过 |

## 环境注意

- PowerShell 5.1 读取无 BOM 的 UTF-8 脚本会按 GBK 解码，导致中文注释破坏语法。**修改 `scripts/*.ps1` 后必须保存为 UTF-8 with BOM**。
- Python 脚本以标准库为主；PDF/HTML 抽取可选 MarkItDown、PyMuPDF，需用非隔离模式（不要加 `-I`）。
- 编译必须 XeLaTeX；不要用 pdfLaTeX。
- 系统 Noto SC 是可变字体，xdvipdfmx 无法嵌入；正文用 SimSun/SimHei。
