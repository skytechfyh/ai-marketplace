# 时效性复查（按需执行，非日常转换流程的一部分）

对**已有笔记**（不限于哪种源格式生成）核验其技术内容是否仍与官方最新文档一致。完全独立于
Step 0 起的转换流程，可对任意时间生成的笔记执行。

## 触发方式

用户对已有笔记发起检查时触发，关键词示例：
- "检查这篇笔记还适不适用：/path/to/note.md"
- "对比官方文档看看有没有过期内容"
- "这个笔记的 API 还对吗，帮我核验一下"
- "freshness check / 时效性检查"

## F1 — 提取笔记技术声明

```bash
source ~/.zprofile && python3 __SKILL_DIR__/scripts/extract_note_claims.py \
  "<笔记.md 绝对路径>"
```

读取输出 JSON，记录以下字段供后续步骤使用：
- `tech`：技术名（docx/pdf 笔记从 `current_version` frontmatter 推断；mhtml 笔记从
  `tags` / `course` / 标题推断）
- `note_version`：笔记中的版本号（来自 frontmatter `current_version` 字段，docx/pdf 笔记通常有）
- `note_date`：笔记写入日期（来自 frontmatter `date` 字段，mhtml 笔记通常有）
- `classes` / `methods` / `configs`：从代码块机械提取的 API 声明
- `deprecated_warnings`：笔记中 `[!WARNING]` callout 里已标注的废弃 API
- `source_note_path`：笔记绝对路径

> **conceptual 类判断**：若 `classes` 和 `configs` 均为空列表，说明这是概念类笔记（无可提炼的代码）。此时跳转至 **F2-conceptual** 路径，不做 API 级核验。

## F2 — 搜索最新官方版本（technical 路径）

```
WebSearch: "<tech> latest stable release site:官方域名 OR release notes"
```

记录 `latest_version`。若与 `note_version` 相同，在报告中注明"版本未变，仍做 API 核验"；若笔记
只有 `note_date` 而无 `note_version`，且 `note_date` 与当前日期差距 ≤6 个月，报告中注明
"写入时间较近，API 整体应仍有效，本次做快速扫描"。

**F2-conceptual（概念类路径）**：

```
WebSearch: "<文章主题/技术领域> 方法论/最佳实践 最新发展 2026"
```

简要了解该领域是否有重大观念演变，直接跳至 F6 生成简短概念时效报告。

## F3 — 拉取官方文档（≤3 页，覆盖提取到的关键 API/配置章节）

```
WebFetch: 官方 API 文档页（按 classes 列表中的关键类名定位章节）
WebFetch: 官方配置参考页（按 configs 列表定位）
```

打印所用 URL（写入报告 frontmatter）。每次 WebFetch 后立即记录核验结论，不积压。

## F4 — 逐一核验（technical 路径）

对 `classes + methods + configs` 中每条，与官方文档比对，得出结论之一：

| 结论 | 含义 | 报告分区 |
|---|---|---|
| ✅ 仍有效 | 官方文档中仍存在且语义一致 | `## ✅ 仍然有效` |
| ⚠️ 有变化需核验 | 仍存在但签名/行为/推荐做法有变动 | `## ⚠️ 有变化，需核验` |
| ❌ 已废弃/移除 | 官方明确标记 deprecated 或已从文档移除 | `## ❌ 已废弃 / 移除` |
| 🆕 官方新增 | 当前官方文档中存在、笔记未提及的重要 API | `## 🆕 官方新增` |

`deprecated_warnings` 中已有的项优先标记为 ❌，但仍需官方文档核实。

## F5 — 准备临时目录

```bash
NOTE_STEM=$(basename "<笔记.md>" .md)
mkdir -p "/tmp/freshness_check_${NOTE_STEM}/"
```

记录临时目录路径 `TEMP_DIR=/tmp/freshness_check_${NOTE_STEM}/`。

## F6 — 写报告到临时目录

将核验结论写入 `${TEMP_DIR}/report.md`，格式如下（`note_version`/`note_date` 二选一，取笔记
实际拥有的字段）：

````markdown
---
note: "<笔记文件名>"
note_path: "<笔记绝对路径>"
note_version: "<note_version，若无则省略>"
note_date: "<note_date，若无则省略>"
latest_version: "<latest_version>"
check_date: "<YYYY-MM-DD>"
official_docs:
  - <WebFetch URL 1>
  - <WebFetch URL 2>
---

# <笔记标题> · 时效性检查

> [!ABSTRACT] 检查结论
> 笔记版本 <note_version> → 官方最新 <latest_version>（或：笔记写于 <note_date> | 官方最新 <latest_version>） | ❌ N 处已废弃 · ⚠️ M 处需核验 · ✅ K 处有效

## ❌ 已废弃 / 移除

| 笔记中的内容 | 当前官方说明 | 所在章节 |
|---|---|---|
| `废弃类名` | 官方说明（版本 X.Y 起废弃/移除，推荐改用 ZZZ） | ## 章节名 |

## ⚠️ 有变化，需核验

| 笔记中的内容 | 官方变化说明 | 所在章节 |
|---|---|---|

## ✅ 仍然有效（已核验）

- `ClassName` ✅
- 配置项 `config.key` ✅

## 🆕 官方新增（笔记未覆盖，可考虑补充）

- 新特性描述（版本 A.B 新增）

## 📋 检查说明

- 技术栈：<tech>
- 核验范围：N 个类名 · M 个配置项 · K 个方法名
- 官方文档来源：<URL 列表>
- 生成时间：<YYYY-MM-DD>
````

报告写完后，**在对话中完整展示报告内容**，然后询问：

> "以上是时效性检查结果。是否需要将报告中标注的内容更新到原笔记？
> - 回复 **'更新全部'** → 按 ❌ + ⚠️ 全部应用到原笔记
> - 回复 **'只更新 ❌ 项'** → 仅将已废弃内容替换
> - 回复 **'不更新'** → 跳过，直接清理临时文件"

## F7 — （仅当用户确认后）编辑原笔记

按报告结论逐处 Edit 原笔记（遵循"一次一个 `##`/`###` 节"原则，不批量写入）：
- 将废弃 API 替换为当前版本推荐写法
- 新增 `[!WARNING]- 版本迁移` callout 说明旧写法被替换的原因
- 🆕 项按用户意愿追加

## F8 — 清理临时目录

```bash
rm -rf "${TEMP_DIR}"
echo "临时目录已清理：${TEMP_DIR}"
```

无论用户是否选择更新原笔记，最终都执行此步。
