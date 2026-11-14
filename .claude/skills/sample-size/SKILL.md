---
name: sample-size
description: 计算随机抽样需要多少段/多少轮，才能在给定置信度下把残余错误率压到目标上界。Use when planning sample-based QA.
---

# 抽样样本量

回答“抽多少段才够”，不是“证明绝对无遗漏”。

## 计算

```powershell
python ..\..\scripts\sample_size.py --project . --margin 0.01 --confidence 0.95 --json
```

关键字段：

- `required_samples`：零错误时需要的总样本量
- `already_counted` / `additional_samples`：已复核多少、还差多少
- `rounds` / `per_round`：建议拆成几轮、每轮多少段
- `current_upper_bound`：已有复核记录时的单侧上界

## 常用结论（0 错误）

| 目标残余率上界 | 90% | 95% | 99% |
|---:|---:|---:|---:|
| 5% | 45 | 59 | 90 |
| 2% | 114 | 149 | 228 |
| 1% | 230 | 299 | 459 |
| 0.5% | 460 | 598 | 919 |
| 0.1% | 2302 | 2995 | 4603 |

给出总段落数时用超几何分布做有限总体校正，所需样本略少。

## 已发现问题时

```powershell
python ..\..\scripts\sample_size.py --reviewed 300 --observed 2 --margin 0.01 --json
```

- `current_upper_bound` 是当前样本的单侧置信上界
- `additional_samples` 假设后续复核不再发现新错误；这只是规划值，不是保证
- 若已发现错误，先修正，再重新抽样验证；不要用“再抽到 0 个”掩盖已知错误

## 边界

- 统计结论依赖随机抽样、独立复核、复核者能发现错误；任何一条不成立，上界就不成立。
- 段落对齐 `aligned=false` 时先处理配对，否则抽样单位不可比。
- 停止抽样只说明错误率低于设定上界，不等于零缺陷。
