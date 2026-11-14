# 思维阁 · 译者文风档库

「思维阁」是一组可选择的译者文风档位。每个档位不是“模仿某位译者”，而是把某种文风的**可执行特征**写成约束：句法、词汇、标点、注释与禁忌。译者或 agent 在动笔前选定一个档位，译文与审校都以它为准。

## 使用

```powershell
python scripts/style.py --list
python scripts/style.py --show academic-faithful
python scripts/style.py --apply literary-fluent --project projects/my-book
```

`--apply` 会：

1. 把该档位的 `STYLE.md` 写入项目的 `notes/style.selected.md`；
2. 在 `project.json` 中写入 `style_id`；
3. 不覆盖项目原有的 `notes/style.md`（项目特有规则仍然优先）。

翻译与润色时，先读 `notes/style.selected.md`，再读 `notes/style.md`；两者冲突时，以 `notes/style.md` 中项目特有的规定为准，并在 `notes/decisions.md` 记录取舍。

## 档位

| id | 名称 | 状态 | 适用 |
|---|---|---|---|
| `academic-faithful` | 学术忠实体 | stable | 学术专著、理论文本（默认） |
| `plain-modern` | 现代平实体 | stable | 普及读物、报告、长文 |
| `literary-fluent` | 文学流畅体 | experimental | 随笔、小说、散文 |
| `classical-concise` | 古典凝练体 | experimental | 序跋、题词、史料引文 |

## 边界

- 档位描述文风，不复制任何具体译者的译文；示例句均为本项目自写。
- 历史译者只作为风格参照，不声称“还原”或“模仿”其个人风格。
- 风格不能覆盖事实：任何档位都不得增写、删减或改写原意。
- 实验档位（experimental）用于整本书前，应先做 1000—2000 字试译并由人工确认。

新增档位：复制任一目录，改 `profile.json` 与 `STYLE.md`，再把条目登记到 `index.json`。
