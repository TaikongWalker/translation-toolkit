---
name: audit-sample
description: 随机抽样复核：按段落配对分层抽样、记录漏译/误译、估计残余错误率与停止条件。Use for semantic QA after structural checks pass.
---

# 随机抽样复核

适用时机：`check.py` 与 `global_check.py` 已通过，但担心语义层面的漏译、误译、数字或术语错误。不要用抽样替代全量结构检查。

## 1. 建清单并校验对照文件

```powershell
python ..\..\scripts\audit.py verify --project . --json
python ..\..\scripts\audit.py inventory --project . --json
```

- `verify` 检查 `notes/_<unit>_pairs.md` 是否仍与当前 `chapters/*.tex` 一致。
- 内容相近的 target 会按正文刷新；无法匹配的标记为 `target_stale`，不进入抽样。
- 正文润色后必须先跑 `verify`，否则旧快照会产生误报。
- 检查每个单元 `aligned` 是否为 `true`。若为 `false`，先看 `source_paragraphs` 与 `target_paragraphs` 的差异，必要时在 `notes/decisions.md` 记录段落合并/拆分。

## 2. 抽样

```powershell
python ..\..\scripts\audit.py plan --project . --size 20 --seed 42 --round 1 --json
```

- 默认不重复抽同一段；多轮推进覆盖率。
- 需要独立重复实验时加 `--with-replacement`。
- 每个 task 带 `auto_flags`：`numbers_missing`、`placeholder`、`english_residue`、`term_missing`、`target_missing`。

## 3. 复核与记录

逐条对照 `source` 与 `target`，记录：

```powershell
python ..\..\scripts\audit.py record --project . --id ch03:p012 --result omission --note "漏了第二句"
```

结果枚举：`ok`、`omission`、`mistranslation`、`terminology`、`number`、`footnote`、`style`、`other`。
同一条目重复记录时，以最后一次为准。

## 4. 统计与停止

```powershell
python ..\..\scripts\audit.py stats --project . --json
python ..\..\scripts\audit.py report --project .
```

- 看 `coverage`、`error_rate_ci95`、`estimated_residual_errors`。
- `stop_recommended=true` 需要同时满足：最近 `--quiet-rounds`（默认 3）轮无新增错误，且覆盖率达到 `--min-coverage`（默认 0.1）。
- 样本量小于 5 时不要下结论，继续抽样。
- 报告写入 `notes/audit/report.md`。

## 边界

- 抽样只估计错误率，不证明“没有错误”；停止不等于零缺陷。
- 固定 `--seed` 与 `--size`，保持实验可复现。
- 发现的问题要回到正文修正，并在下一轮抽样中验证，不要只记录。
