# AGENTS.md · 给 AI agent 的入口

本仓库是**面向 agent 的翻译工作区**：每个阶段都有确定的命令、稳定的 JSON 输出和明确的退出码。人读文档在 `docs/`，agent 的机器契约在 `agent/capabilities.json`。

> 内容边界：仓库只含工具链、文档与空白模板。不得把任何书籍原文、译文或电子书提交到本仓库；翻译项目应位于 `projects/`（已被 `.gitignore` 忽略）并另行确认授权。

## 先读什么

1. 本文件。
2. `agent/capabilities.json`：命令、参数、输出契约、退出码。
3. `docs/01-工作流.md`：阶段与质量门。
4. 项目的 `notes/context.md`、`notes/style.md`、`notes/style.selected.md`（若存在）、`glossary/terms.csv`。

## 一条命令看状态

```powershell
python scripts/status.py --project projects/my-book --json
```

返回项目阶段、术语统计、章节 TODO、`check.py` 与 `global_check.py` 的完整结果、阻断项列表。**任何阶段开始前先跑它**，不要凭记忆判断进度。

## 命令契约

所有检查类命令都支持 `--json`，此时 stdout 只有 JSON，进度与日志不得混入。

| 命令 | 作用 | JSON 关键字段 |
|---|---|---|
| `status.py --project <p> --json` | 项目总状态 | `ok` `project` `units` `terms` `chapters` `blocking` `check` `global` |
| `check.py --project <p> --json` | 项目级质量检查 | `ok` `summary{error,warn,info}` `counts` `issues[]` |
| `global_check.py --project <p> --json` | 全书结构核对 | `ok` `total_chars` `problem_units` `units[]` |
| `prepare.py --project <p> --json` | 生成元信息/章序/术语表 | `chapters` `terms{total,final,draft}` `style_id` |
| `backmatter.py --project <p> --json` | 生成参考文献/索引 | `generated[]` `bibliography` `index` |
| `term_candidates.py --project <p> --json` | 提取术语候选 | `candidate_count` `candidates[]` |
| `style.py --list\|--show\|--apply --json` | 思维阁文风档位 | `profiles[]` / `profile` / `style_id` |
| `chunk.py --project <p> --unit <u> --out <d> --json` | 把长章切成无损块 | `chunks[]` `source_sha256` `lossless` |
| `audit.py inventory\|plan\|record\|stats\|report` | 随机抽样复核 | `tasks[]` `coverage` `error_rate_ci95` `stop_recommended` |
| `sample_size.py --project <p> --json` | 计算所需样本量与轮次 | `required_samples` `additional_samples` `per_round` |
| `qa.py --project <p> --mode full\|sample\|structural` | 统一质检入口 | `structural` `semantic` `estimate` |
| `export.py --project <p> --format all` | 导出 EPUB/DOCX/HTML/MD | `results[]` |
| `extract.py --input <f> --out <p>/source --json` | 多格式原文抽取 | `format` `backend` `files` `units[]` `warnings[]` |
| `extract.py --list-formats --json` | 后端可用性 | `engines` `formats[]` |
| `build.ps1 -Project <p> -Json` | 构建 PDF | `ok` `pdf` `pages` `check{ok,error,warn,info}` |

退出码：`0` 成功/无阻断；`1` 有阻断项、参数错误或文件不可读。不要把警告当成功，也不要把提示当错误。

## 容量控制

长章节或长书容易撞上上下文上限。默认输出已尽量收紧；仍不够时按以下顺序降载：

1. **状态**：`status.py --json --summary`（约 1–2 KB）；需要细节时再 `--deep`。
2. **检查单章**：`check.py --unit ch03 --json`。
3. **分页取问题**：`check.py --unit ch03 --json --max-issues 20 --offset 0 --compact`，看 `issue_page.has_more` 继续翻页。
4. **结构汇总**：`global_check.py --json --summary`；单章用 `--unit`。
5. **翻译长章**：先 `chunk.py --project . --unit ch03 --out chunks/ch03`，按 `c001.md`…逐块翻译，再按 `plan.json` 顺序合并。块只在段落边界切，`lossless=true` 表示拼回与原文逐字一致。
6. **抽取大书**：`extract.py ... --summary` 省略 `units` 明细。

不要用“摘要原文再翻译”的方式降载——那会损失信息。降载只应减少**输出**和**单次输入**，不减少原文。

## 抽样复核

结构检查抓不到语义错误时，用 `audit.py` 做可复现的随机抽样：

```powershell
python scripts/audit.py inventory --project . --json
python scripts/audit.py plan --project . --size 20 --seed 42 --round 1 --json
python scripts/audit.py record --project . --id ch03:p012 --result omission --note "漏了第二句"
python scripts/audit.py stats --project . --json
```

- `plan` 默认不重复抽样；多轮推进覆盖率，`--with-replacement` 用于独立重复实验。
- 每个 task 带 `auto_flags`（数字缺失、占位、英文残留、术语缺失、译文缺失），先处理标记项。
- `stats` 的 `stop_recommended` 只有在最近 N 轮无新增错误且覆盖率达到阈值时才为真；不要只看错误率为 0。
- 结果写入 `notes/audit/`，固定 seed 可复现。

需要回答“到底要抽多少段”时，用 `sample_size.py`：

```powershell
python scripts/sample_size.py --project . --margin 0.01 --confidence 0.95 --json
```

给出 `required_samples`、`additional_samples` 与 `per_round`。它的结论是**错误率上界**，不是绝对无遗漏；不要向用户表述成“已证明零错误”。

## 全量还是抽样

统一入口 `qa.py`，两种模式都先跑全量自动结构检查：

```powershell
python scripts/qa.py --project . --mode full --json
python scripts/qa.py --project . --mode sample --margin 0.01 --confidence 0.95 --json
python scripts/qa.py --project . --mode structural --json
```

- `full`：为全书每段生成复核任务，写到 `notes/qa/full-plan.json`；适合高价值书稿或终版。
- `sample`：按样本量分轮抽样，写到 `notes/audit/round-*.json`；适合长书、迭代期或 token 预算有限。
- `structural`：只跑自动检查，不生成语义复核任务。
- `--save` 把 `qa_mode` 写入 `project.json`；之后 `qa.py --project .` 沿用。
- 不要对用户承诺“抽样=完整检查”；抽样只给残余错误率上界。

## 输出格式

PDF 由 `build.ps1` / XeLaTeX 生成；其他格式由 Pandoc 从同一份 LaTeX 稿导出：

```powershell
python scripts/export.py --project . --format all --json
```

- 支持 `md`、`html`、`epub`、`docx`；`--check` 检查 Pandoc。
- 章节自动编号，脚注/译者注/图注保留；版式会比 PDF 简化。
- 需要精确分页、双栏索引、字体排印时，以 PDF 为准。

## 原文格式

`extract.py` 统一处理 EPUB、PDF、TXT、Markdown、HTML、DOCX、ODT、RTF、FB2、MOBI/AZW3：

- EPUB 用内置后端，保留脚注、图片与章节结构；
- PDF/HTML 在 MarkItDown 可用时优先使用，否则回退 pdftotext/PyMuPDF 或内置解析；
- DOCX/ODT/RTF/FB2 用内置后端，保留标题与脚注位置；
- MOBI/AZW3 需要 Calibre 的 `ebook-convert`；
- `--engine auto|markitdown|native` 可强制后端，`--list-formats --json` 查看可用性。

MarkItDown 若装在用户 site-packages，运行 `extract.py` 时**不要加 `-I`**。

## 推荐工作循环

```
status → 读取候选与上下文 → 翻译/审校单章 → check → 修复 → status → 下一章
```

- 每次只处理一个翻译单元（一章或一节），改完立即跑 `check.py --json`。
- `check.py` 的错误（A2/A4/A5/A6/A11/A12）必须清零；警告与提示逐条判断，不要机械忽略。
- 编译用 `build.ps1 -Json`，只读返回的 `pdf` 与 `check`；失败时读 `log_tail`。
- 任何取舍写入 `notes/decisions.md`；术语变更走“改表 → forbidden → 全局替换 → 记录”。

## 文风：思维阁

动笔前确定 `project.json.style_id`，并读取 `notes/style.selected.md`。档位是约束，不是模仿：

- `academic-faithful`（默认）：保留限定语、论证层级与反讽延迟。
- `plain-modern`：适度拆句，降低门槛但不改结构。
- `literary-fluent`：重节奏，用于文学与引文。
- `classical-concise`：浅近文言，用于序跋题词。

项目 `notes/style.md` 的特别规定优先于档位；冲突时记录到 `notes/decisions.md`。

## Agent skills

`.claude/skills/` 提供可直接调用的阶段技能：

- `project-intake` — 抽取原文、建元数据、写背景卷宗、提术语候选
- `translate-chapter` — 单章初译
- `review-chapter` — 双语审校
- `polish-chapter` — 单语润色（含文风档位）
- `final-check` — 全书终检与 PDF 核验
- `select-style` — 思维阁选档与应用
- `audit-sample` — 随机抽样复核与残余错误估计
- `sample-size` — 所需样本量与轮次计算
- `qa-mode` — 在全量检查与抽样检查之间选择
- `export-formats` — 导出 EPUB/DOCX/HTML/Markdown

## 硬性规则（不可协商）

- `source/` 只读；不改写、不删减原文。
- `glossary/terms.csv` 是唯一术语权威；新术语先入表再使用。
- 原书脚注全部保留，每章从 1 重编号；译者注只用 `\zhu{}`。
- 不增写、不删减、不替作者补充观点；不确定写 `\todo{原因}`。
- 不把受版权保护的原文、译文或电子书提交到本仓库。
- 修改 `scripts/*.ps1` 后保存为 UTF-8 with BOM。
