---
name: qa-mode
description: 在“全量检查”和“抽样检查”之间选择，生成对应的语义复核计划。Use when deciding QA coverage or token budget.
---

# 质检覆盖：全量还是抽样

两种模式都先执行全量自动结构检查；区别只在语义复核覆盖多少段。

## 全量

```powershell
python ..\..\scripts\qa.py --project . --mode full --json
```

- 为全书每段生成复核任务，写入 `notes/qa/full-plan.json`
- 适合终版、高价值书稿、需要逐段确认的场合
- 代价最高，但覆盖面最大；仍不保证复核者不漏判

## 抽样

```powershell
python ..\..\scripts\qa.py --project . --mode sample --margin 0.01 --confidence 0.95 --json
```

- 自动用 `sample_size.py` 计算样本量并分轮
- 写入 `notes/audit/round-*.json`
- 适合长书、迭代期、token 预算有限
- 结论是残余错误率上界，不是零缺陷证明

## 仅自动检查

```powershell
python ..\..\scripts\qa.py --project . --mode structural --json
```

只跑术语、标点、脚注/图数量、数字、TODO 等自动检查。

## 记住选择

```powershell
python ..\..\scripts\qa.py --project . --mode sample --save
```

之后 `qa.py --project .` 直接沿用 `project.json` 的 `qa_mode`。

## 决策建议

| 场景 | 建议 |
|---|---|
| 初译迭代、章节多、预算紧 | `sample` |
| 终版、合同交付、高价值 | `full` |
| 只改了几处、结构已稳定 | `structural` + 针对性抽样 |
| 抽检发现错误率高于目标 | 回到逐章修正，再重新抽样；不要直接放宽 margin |

## 成本说明

抽样节省的是**语义复核**的 token，不是翻译本身；全量自动结构检查仍然覆盖每一章。`qa.py` 会给出粗略 token 估算，只作方向参考。
