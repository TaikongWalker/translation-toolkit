---
name: final-check
description: 全书终检：清零 TODO 与阻断错误，核对结构、术语与 PDF，确认可交付。Use for the final QA pass before delivery.
---

# 全书终检

## 自动检查

```powershell
python ..\..\scripts\status.py --project . --json
python ..\..\scripts\check.py --project . --json
python ..\..\scripts\global_check.py --project . --json
```

通过标准：

- `status.blocking` 为空。
- `check.summary.error == 0`；警告逐条确认为有意保留（俄语转写、诗歌原文、文献标题等）。
- `global.problem_units == 0`；每章节/脚注/图数量一致；无占位、无 `TODO`。

## 构建与目视

```powershell
..\..\scripts\build.ps1 -Clean -Json
```

- 读返回的 `pdf`、`pages`、`check`；失败时读 `log_tail`。
- 打开 PDF 目视检查：封面、版权页、目录、章节起始页、图注、脚注编号、术语表、参考文献、索引、译后记。
- 确认目录页码与正文一致；插图目录条目数等于图数。

## 交付清单

- [ ] `check.py` 错误 0，TODO 0
- [ ] 结构数量与原文一致
- [ ] 术语表核心词 100% final
- [ ] 版权状态与出版社信息已确认
- [ ] 译者署名/译后记已定稿
- [ ] PDF 目视通过，`dist/<slug>.pdf` 为最新构建

## 记录

把终检结果写入 `notes/QA-final.md`（日期、范围、方法、阻断项、结论）。仍待确认的事项单独列出，不要用“已通过”掩盖。
