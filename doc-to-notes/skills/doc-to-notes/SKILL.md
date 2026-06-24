---
name: doc-to-notes
description: Convert .docx / .doc / .pdf training or learning documents into structured, up-to-date Obsidian Markdown notes. Scripts parse headings/code/lists/tables/images and split the doc into per-chapter JSON; images upload to Aliyun OSS; oversized screenshots are auto-resized, OCR'd (Apple Vision) and visually analyzed (architecture→Mermaid, code screenshot→code block, data screenshot→table, math formula→LaTeX); content is re-baselined to the latest stable version against official docs for technical docs (concepts/API/config/terminology taught in the new version's voice, old version kept only as migration notes; conceptual/history docs skip re-baselining); output is one Markdown file per chapter, or a single combined file with --no-split (auto-split only if it exceeds 5MB); verify_content.py checks no prose/numbers/enumerations were dropped; check_mermaid.py checks all Mermaid blocks for syntax errors (edge label <br/>, unclosed fences, invalid diagram types, etc.). Big-data tech (Flink/Hadoop/Spark/Kafka) routes to 214_Big_Data. Use when user provides a .docx/.doc/.pdf path to turn into knowledge base notes, mentions 资料转换 / 培训文档整理 / 学习笔记, or processes training materials (e.g. 多易大数据, Flink/Spark/Kafka internal docs).
---

# Doc to Notes

Convert a large `.docx` / `.doc` / `.pdf` learning document into multiple structured
Obsidian Markdown notes — one per chapter — with code blocks, Mermaid diagrams,
OSS-hosted images, and content refreshed to the latest official version.

## 🚨 The #1 rule: chunk everything (120s timeout)

The Cloudflare timeout is **120s**. A single large Write/Edit will time out and corrupt
state. Therefore:
- **Scripts do the heavy lifting** (extraction, image upload) in one fast batch each.
- The model **processes one chapter file at a time** (`chapter_NN.json`), never the whole manifest.
- Each chapter Markdown file is written as **skeleton first, then one `###` section per Edit**.
- Image visual analysis reads **≤4 images per batch**, summarizing before reading more.

Never batch multiple chapters, never write a full chapter body in one call.

## 🚨 全局换行规则：统一用 `<br/>`，禁止用 `\n`

写入任何 Markdown 文件时（正文段落、callout 块、表格单元格、Mermaid 节点标签等所有位置），
**禁止使用 `\n` 作为换行**，统一改用 `<br/>`。

| 位置 | 正确写法 | 错误写法 |
|---|---|---|
| Mermaid 节点标签 | `A["第一行<br/>第二行"]` | `A["第一行\n第二行"]` |
| **Mermaid 边标签（edge label）** | `-->\|"第一行<br/>第二行"\|`（**必须加双引号**） | `-->\|第一行<br/>第二行\|`（无引号→解析失败） |
| **Mermaid timeline 图** | `1956 : 事件一 : 事件二`（**冒号分隔多事件**） | `1956 : 事件一<br/>事件二`（Obsidian 不渲染→显示字面 `<br/>`） |
| 表格单元格 | `内容A<br/>内容B` | `内容A\n内容B` |
| callout / 正文段落内联换行 | `说明第一句。<br/>说明第二句。` | `说明第一句。\n说明第二句。` |

> `\n` 在 Markdown 中不会渲染为换行，只会产生乱码或意外空行；`<br/>` 是唯一可靠的内联换行方式。
>
> ⚠️ **不同图表类型的 `<br/>` 规则不一样**（这是最容易踩错的点）：
> - **节点标签** `["...<br/>..."]`（方括号）：直接支持 ✓
> - **边标签** `|...|`：**必须加双引号** `|"...<br/>..."|`，否则 `< > /` 致解析失败、整图报红框
> - **timeline**：**不支持** `<br/>`（Obsidian 下显示字面文本），改用冒号 ` : ` 分隔为多个事件
> - 任何位置都只认 `<br/>` 或 `<br>`，**不要写 `<br />`（带空格）**

## 🚨 内容守恒规则：提炼重组，绝不删减

整理 = **提炼 + 重组 + 图解**，不是摘要。源文档里的每一个事实点（定义、步骤、参数、
案例、数据、结论、举的每一个例子）都必须在笔记中保留——可以合并同类、改写得更清晰、
配图解释，但**不能丢信息**。

- ✅ 允许：把零散段落按主题合并；口语化表述改写得更准确；长流程配 Mermaid；枚举配表格。
- ❌ 禁止：跳过某个小节；把"讲了 5 点"概括成"讲了几点"；删掉案例只留结论；漏掉某张图承载的信息。
- **单文件模式（`--no-split`）尤其要警惕**：一个文件里有所有章节，必须**逐章节**搭骨架、
  逐节填充，写完后用 `grep '^## ' file.md` 核对 H2 数量与 `chapter_01.json` 里的 H2 heading
  数一致——确认每个章节都落到成稿里，绝不能写到一半就收尾。

## Prerequisites

`pip install python-docx oss2 pymupdf pillow ocrmac`
- pillow optional — image resize falls back to macOS `sips`
- ocrmac optional — code/UI screenshot OCR (Apple Vision); falls back to pytesseract

## Workflow

### Step 0 — Extract structure

**推荐默认（单文件模式，适用所有文档类型）：**
```bash
source ~/.zprofile && python3 __SKILL_DIR__/scripts/extract_docx.py \
  "/path/to/document.docx" --no-split
```

写完 MD 后用 `wc -c` 检查**成稿 MD 大小**；**超过 5 MB** 时再按 H2 手动拆分（见 Step 6d）。适用于 `.docx` / `.doc` / `.pdf` 所有格式。

**多文件模式（不加 `--no-split`，仅超大型参考手册按需使用）：**
```bash
source ~/.zprofile && python3 __SKILL_DIR__/scripts/extract_docx.py \
  "/path/to/document.docx"
```

Handles `.docx`, `.doc` (auto-converts via `textutil`), and `.pdf`. Outputs to
`/tmp/doc_notes_<name>/`:
- `manifest.json` — full structure (headings, code, lists, tables, images w/ dimensions)
- `chapter_NN.json` — `--no-split` 时全部内容写入单个 `chapter_01.json`；默认模式按 H2 拆分每章一文件
- `images/` — extracted images, resized to ≤2000px

Read the printed summary: title, chapter list, section-type counts. **Note the chapter
count** — you'll process exactly that many files.

### Step 1 — Decide output location

| Doc topic | Target |
|---|---|
| **Big data (Flink, Hadoop, Spark, Kafka, Hive, HBase, Zookeeper)** | `210_Dev_Stack/214_Big_Data/<Tech>/` |
| Middleware (Redis, RabbitMQ, Nginx, Dubbo, ES) | `210_Dev_Stack/213_Middleware/<Tech>/` |
| Language-specific (Java, Python) | `210_Dev_Stack/212_Java_Expert/` or `211_Python_Expert/` |
| Infra / ops (K8s, Docker, Linux) | `230_Infra_Ops/` |
| Platform course series (GeekTime etc.) | `260_Courses/` |
| Ambiguous | **ask the user** |

> **Big data lives in its own `214_Big_Data/`**, a sibling of `213_Middleware/` — not
> inside Middleware. Each technology gets its own sub-dir: `214_Big_Data/Flink/`,
> `214_Big_Data/Hadoop/`, `214_Big_Data/Spark/`, … New tech dirs are created as needed.

Output structure — 两种模式：

**单文件模式（`--no-split`，推荐默认）：** 全部内容写入一个 `.md`，写完用 `wc -c` 检查**成稿 MD 大小**，**超过 5 MB** 才按 H2 手动拆分：
```
240_AI/AI大模型基础/
└── 01-AI大模型基础认知.md      # 全部章节合并在一个文件里（成稿 ≤ 5 MB 时保持单文件）
```

**多文件模式（超大型参考手册按需使用）：** one sub-dir per source doc, one `.md` per **top-level chapter**, plus an index:
```
214_Big_Data/Flink/01_Flink基础/
├── 00-索引.md                 # MOC: links every chapter in order
├── 01-快速认识Flink.md         # = H2 "1.快速认识flink"
├── 02-环境准备与编程入门.md      # = H2 "2.Flink环境准备和编程入门"
└── 03-DataStream编程基础.md    # = H2 "3.DataStream编程基础" (large → fill ### by ###)
```

### Step 1b — 判定文档类型（technical / conceptual），决定后续策略

提炼/配图/核查的力度因文档类型而异，**先判定并记下类型**，供 Step 4 / 5 / 7 复用：

| 类型 | 特征 | 典型 | 第一优先级 | 版本重对齐 | 核查阈值 |
|---|---|---|---|---|---|
| **technical** | 含代码/架构/配置/命令/API | Flink/Java/分布式/中间件 | 还原代码·图表·参数零失真 | 做（Step 4） | 散文 60% |
| **conceptual** | 通篇说理/概念/历史/数学原理，几乎无代码 | AI 发展史、Transformer 原理、设计模式、软技能 | 保叙述细节·论证链·公式·类比 | **跳过**（≈`--no-version-update`） | 散文 80% |

> 判定信号：有可提炼的代码/可跑的 API → technical；通篇"是什么/为什么/发展历程/数学推导" →
> conceptual；拿不准就按"原文是否存在可提炼的代码"二选一。该类型决定 Step 7
> `verify_content.py --type` 的取值，以及是否执行 Step 4 的版本重对齐。

### Step 2 — Upload images

```bash
source ~/.zprofile && python3 __SKILL_DIR__/scripts/upload_oss.py \
  /tmp/doc_notes_<name>/images/
```

Outputs `url_mapping.json` → `{filename: oss_url}`. Keyed by content md5 (idempotent —
safe to re-run, no duplicate uploads).

### Step 3 — Visually analyze images (OCR baseline + vision, batched ≤4)

**3a — OCR baseline (script, one pass).** Run OCR over all images to get a text baseline
and a code-likelihood score per image:

```bash
source ~/.zprofile && python3 __SKILL_DIR__/scripts/ocr_image.py \
  /tmp/doc_notes_<name>/images/ --json
```

Outputs `ocr_text.json` → `{file: {text, code_score, code_like}}`. `code_like:true` (high
symbol density) flags likely **code / UI** screenshots vs diagrams.

**3b — Vision + correction.** Images are NOT blindly embedded. For each image, Read it
(vision) AND consult its `ocr_text.json` entry, then decide:

| Image content | Action |
|---|---|
| Architecture / topology diagram | **Redraw as Mermaid** (don't embed) |
| Flow / sequence diagram | **Redraw as Mermaid** |
| **数学公式截图**（attention / softmax / 位置编码 / 求和符号等） | **转写为 LaTeX**：行内 `$...$`、独立成式 `$$...$$`（见 REFERENCE → 数学公式规范）。**不要当图片嵌入、也不要塞进代码块** |
| Code screenshot | **Transcribe into a code block** — use OCR text as the baseline, then **fix indentation/symbols against the image** (OCR alone mangles `{} ; →` and indent) |
| Data / table screenshot | **Rebuild as a Markdown table** |
| 多分区陈列 / 总览信息图（≥3 并列彩色面板，无方向连接） | **重建为 HTML/CSS 卡片**（见 REFERENCE → HTML 卡片），别用 Mermaid 硬画 |
| UI / config screenshot (operation demo) | **Embed OSS URL** + `[!INFO]` caption ≥3 sentences |
| Decorative / logo | Skip |

> Why both: Apple Vision OCR is fast and gives a text baseline, but errs on dense code;
> your vision Read corrects it. Two signals beat one, and you avoid re-typing long code.

> **`small_inline` 标注**：`manifest.json` 里 `small_inline:true` 的图（尺寸很小，
> 如 ≤700×150），多为**数学公式截图**或架构图的**局部组件标签**（如放大的 "Add & Norm"）。
> 优先：① 是公式 → 转 LaTeX；② 是组件标签 → 并入所属架构图的 Mermaid 节点，不要当独立图嵌入。
> Step 0 末尾会打印这类小图的数量。

⚠️ **Context control**: Read at most **4 images**, write a compact summary table
(filename · type · key info · decision), then read the next batch. This clears image
base64 from context and prevents request-body overflow.

### Step 4 — Re-baseline content to the latest version (unless `--no-version-update`)

> **先判断该不该做版本重对齐。** 本步骤只对**有明确技术版本的框架/工具类文档**有意义
> （Flink/Spark/K8s/中间件 等）。对**概念、理论、历史、方法论类**文档（如 AI 发展史、
> 设计模式、软技能、数学原理），没有"版本"可言，强行重对齐反而会改写原意、塞进文档没讲
> 的内容——这类文档应**跳过本步**（等价于 `--no-version-update`），忠实保留原文的概念与
> 表述，把精力放在结构化、配图、提炼上。判断不准时问用户。

**The latest stable version is the PRIMARY teaching baseline — not the doc's old version.**
The notes explain every concept, term, API, config, and recommended practice as it works in
the *current* stable release. The source doc's version survives only as **migration hints**
for a reader who might still meet old code. This is a re-write to the new version, not a set
of warnings bolted onto the old narrative.

1. **Find the doc's version** in the manifest text (e.g. "Flink 1.15", "flink-1.15.3").
2. **Pin the latest stable version**: `WebSearch` it, then `WebFetch` the **official current
   docs** (the actual feature pages, not just release notes) for the features each chapter
   covers. You are rewriting *to* this version, so you must read how today's docs actually
   present these features — never rely on memory, never invent APIs/behavior/defaults.
3. **Build a re-baseline map** per feature: old → current for API names, class/method names,
   config keys, **terminology**, changed defaults, removed/added mechanisms — plus the
   current *recommended* approach (which may differ from both the old way and the minimal new
   API). If the new version deprecated a mechanism and recommends a different one, the
   recommended one is what the chapter teaches as its main line.
4. This map drives Step 6: the body is written in the latest version's voice; the old version
   appears only as `[!WARNING]`-flagged migration notes. Genuinely new features the doc never
   covered may be added as brief `[!INFO]` notes where relevant.

> Skip this entire re-baseline only when invoked with `--no-version-update`, which keeps the
> notes faithful to the doc's original version.

### Step 5 — Find where diagrams help

```bash
python3 __SKILL_DIR__/scripts/suggest_diagrams.py \
  /tmp/doc_notes_<name>/chapter_NN.json
```

Prints per-chapter suggestions: which sections describe architecture / flow / state /
comparison / hierarchy, and the matching diagram type + scaffold. Use as hints — you
draw one diagram per concept (see [REFERENCE.md](REFERENCE.md) for rules & templates).

> **配图密度**：每个**一级章节（H2）至少配 1 张图**（Mermaid 优先）。凡是描述"关系"的
> 地方都该有图——流程、架构、分层、对比、时间线、决策。**单文件模式不要因为是一个文件就
> 只画一两张图**：按 H2 章节数来保证覆盖。源文档里的示意图（决策树、结构图、流程图、关系图）
> 一律**重绘为 Mermaid**（见 Step 3 决策表），只有坐标图/散点图/真实截图这类 Mermaid 画不出
> 的才上传 OSS 嵌入。

> **可视化选型（核心判断：有方向→Mermaid，无方向陈列→HTML 卡片，精确查找→表格，公式→LaTeX）**：
> - 流程 / 架构 / 时序 / 状态 / 决策 / 层级（节点间有方向连接）→ **Mermaid**
> - 课程总览 / 多模块陈列 / 方法论矩阵（≥3 并列面板、无方向）→ **HTML/CSS 卡片**（见 REFERENCE）
> - 属性 / 参数对比 → **Markdown 表格**；数学公式 → **LaTeX `$$...$$`**
> - ❌ 别用 Mermaid 画"N 大模块"的彩色分区图——dagre 自动布局会画成丑陋的树，那是 HTML 卡片的活。

### Step 6 — Write each chapter file (skeleton → fill, ONE chapter at a time)

> **写前先登记"关键内容元素"（防节内细粒度流失）。** 章节不漏 ≠ 内容不漏——叙述型文档
> 的丢失常发生在节内。开写前快速扫一遍该 chapter 的 sections，登记这几类高价值元素，
> 写作时逐一落实、Step 7 用脚本机械复验：
> - **数据 / 数字**：所有具体数值及语境（如"768 维""12 层""6 个 Encoder 堆叠"）。
> - **"N 个 X"结构**：作者归纳的"三大要素 / 四个步骤"——每项都要**单独展开**，不能只点名。
> - **并列长枚举**（≥5 项）：以列表 / 表格**逐项保留**，不得压成一句概述。
> - **关键类比 / 桥接逻辑**：解释抽象概念的类比、连接论点的因果句，**不得省略**。

Loop over `chapter_01.json … chapter_NN.json`. For each:

**6a — Skeleton** (single Write, fast): frontmatter + version callout + `###` headings
with `<!-- FILL -->` placeholders. Use the chapter's `parent` field for the breadcrumb.

> **单文件模式（`--no-split`）的骨架**：整个文档只产出一个 `.md`，所以骨架是
> **一份 frontmatter + 所有 H2 章节（`##`）+ 每个章节下的 `###` 小节**，每个小节一个
> `<!-- FILL -->` 占位。骨架可能很长（如 25 个 H2），这没问题——随后仍是**逐个 `###`
> 一次 Edit 填充**，绝不一次写完整篇。`chapter_01.json` 的 `sections` 里所有 `heading`
> 都要在骨架中出现，一个不漏。

```markdown
---
title: "[chapter heading]"
source_doc: "[original filename]"
source_version: "Flink 1.15"
current_version: "Flink 1.20"
tags: [flink, big-data, streaming]
date: <date +%Y-%m-%d>
---

> 所属章节：[[00-索引]] · 上级：[parent]

> [!INFO] 版本说明
> 本笔记已按**当前最新稳定版 A.B** 重新梳理讲解（概念、API、配置、术语、推荐做法均为新版）；原文档基于 X.Y。旧版差异以 [!WARNING] 迁移提示标注。

## [subsection] 
<!-- FILL -->
```

**6b — Fill** (one Edit per `###` section): replace each `<!-- FILL -->` with structured
content written **in the latest version's voice** (per Step 4's re-baseline map). The old
version is never the main subject — the current stable release is.

- **Concepts, terminology, recommended practice** follow today's official docs. If the new
  version deprecated a mechanism and recommends another, teach the **new mechanism as the
  main line** — don't explain the old mechanism then bolt on a warning.
- **Code / config / class & method names** are the current version's. Write the current API
  as the primary example; do **not** paste the doc's old API verbatim and merely warn after.
- **Old version → migration note only**: where a reader might still meet old code, add a
  short, ideally collapsible `[!WARNING]- 旧版（X.Y）写法` note saying what it was and why it
  changed. Keep it secondary to the main narrative.
- Merge paragraphs by theme, insert Mermaid/code/tables/callouts, embed image URLs from
  `url_mapping.json`. **One section per Edit**, in order.
- **换行**：全文任何位置（Mermaid 节点、表格单元格、callout、正文）一律用 `<br/>` 换行，绝不使用 `\n`（见顶部全局换行规则）。

**代码语言转换规则（Scala → Java）**

源文档代码块语言为 `scala`（或 `scala/java`）时，**Java 为主线，Scala 降级为折叠注**：

```markdown
```java
// ① 主代码块：Java 等价实现（Java 8+ Stream/lambda/Flink Java API，不保留 Scala 语法）
```

> [!NOTE]- Scala 原版
> ```scala
> // ② 折叠：保留原文档的 Scala 代码
> ```
```

> 若源文档语言标注为 `scala/java`、或同时提供两版，以 Java 版为主，Scala 版折叠。
> Kotlin 代码同理：Java 为主（若存在等价写法），Kotlin 降级折叠。

> ⚠️ **版本对齐（与 Step 4 联动）**：转换后的 Java 代码必须使用 **Step 4 re-baseline map 中的最新 API**，
> 不是原 Scala 代码对应的旧版 API 的简单翻译。例如 Flink Scala 旧版用 `ExecutionEnvironment`，
> 转 Java 时要直接写当前版推荐的 `StreamExecutionEnvironment` + DataStream API，而不是翻译出
> 同样已废弃的 Java 旧写法。**先 re-baseline，再转语言**。

**Python 补充规则（Java / Scala / Kotlin → Python）**

每个实质性 `java` / `scala` / `kotlin` 代码块（含 Scala→Java 转换后的块）之后紧跟：

```markdown
> [!TIP]- Python 等价实现
> ```python
> # 使用官方 SDK（pyflink / pyspark / kafka-python 等），优先标准库
> ```
```

> ⚠️ **版本对齐（与 Step 4 联动）**：Python 代码同样基于**最新稳定版**的 Python SDK
> （如 PyFlink 当前版、PySpark 当前版）——不是对旧 Java 代码的逐行翻译，而是最新 Python 推荐写法。
> 需要时用 `WebSearch` 确认 Python SDK 的当前 API，不要凭记忆写旧接口。

**跳过条件**（不加 Python 块）：
- 单行 CLI 命令或环境检查（如 `ollama -v`、`mvn --version`）
- 纯配置片段（YAML / Properties / JSON / XML）
- 代码语言为 `bash` / `shell` / `sql` / `text`
- 不足 3 行的简短片段

> Python 块**不替换**主代码块，只是补充；主线叙述仍以原语言（Java）为准。

> Verify every re-baselined API/behavior against Step 4's fetched official docs before
> writing it. When unsure whether the new version changed something, fetch and confirm —
> never guess a "modern" API into existence.

**6c — Chapter-end exercise WITH answers (mandatory).** End each chapter with a
`[!QUESTION]` callout (2–4 thinking questions) **immediately followed by a collapsible
`[!SUCCESS]- 参考答案` callout that answers every single question**. A question without a
reference answer is an incomplete chapter — never ship one.

The answers are the highest-value part of the note: they must be **complete, correct, and
current** (matching the latest version from Step 4), not one-line hand-waves. For each
question give the direct conclusion first, then the *why* (mechanism / principle), and
where useful a code snippet, a comparison, or a `file:line`-style pointer to the relevant
section above. Verify any version-specific API in the answer against Step 4's findings —
do **not** invent APIs. Match the questions to the chapter's actual content (don't ask
about something the chapter never covered). See REFERENCE.md → "Chapter-End Exercise +
Answer" for the exact format and a worked example.

> **Large chapter (the script prints a heads-up, e.g. 256 sections):** this is normal and
> safe — the file is big but each Edit is small. Build the skeleton from its `###` (H3)
> headings, then fill **one `###` at a time**. If a single `###` is itself huge (many H4
> items, e.g. 50+ operators), fill it in **several Edits** (a few H4 items each) rather
> than one. Never write the whole chapter body in one call.

**6d — 单文件模式：写完后检查大小（`--no-split` 专用步骤）**

```bash
wc -c "<out_dir>/01-文件名.md"   # 输出字节数
```

| 大小 | 处理方式 |
|---|---|
| ≤ 5,242,880 字节（5 MB） | 保持单文件，直接进 Step 7 |
| > 5 MB | 按 H2 标题拆分为多文件（参见下方说明） |

**超过 5 MB 时的拆分做法：**
1. 将当前单一 MD 文件重命名为 `_draft.md` 备份。
2. 在同一目录下新建多个章节文件（`01-xxx.md` `02-xxx.md` …），每个对应一个 H2 章节，沿用相同的 frontmatter 和 `[!QUESTION]/[!SUCCESS]` 结构。
3. 删除 `_draft.md`，补写 `00-索引.md` 链接所有章节文件。
4. 不重新运行 extract —— 内容已在草稿里，直接拆分复制即可。

### Step 7 — Index + 内容核验 + report

**7a — 写索引**：Write `00-索引.md` — a MOC linking every chapter `[[NN-title]]` in order,
with a 1-line summary each, and a top-level Mermaid overview of the whole doc's structure.
（单文件模式可省略独立索引，改在文件顶部放一个目录式 Mermaid 总览。）

**7b — 内容守恒机械核验（必做，直击"整理后内容会不会丢失"）**：
```bash
python3 __SKILL_DIR__/scripts/verify_content.py \
  /tmp/doc_notes_<name>/manifest.json  <笔记.md 或笔记目录>  --type <technical|conceptual>
```
- `RATIO` 行必须 **PASS**（剥离 Mermaid/HTML/LaTeX 标记后的纯散文 ≥ 原文 × 阈值；type 取
  Step 1b 判定值）。FAIL 说明叙述被过度压缩，回去把缺的内容补回，**不要靠堆图凑字数**。
- "关键数字核查"出现 `[MISSING]`、"长枚举核查"出现 `[FLAG]` 时，回原文确认是否确属遗漏，
  是则补回后重新运行，直至无告警。脚本只抓离散 token 丢失，"提到但没展开"仍需人工对照。

**7c — Mermaid 语法检查（必做）**：

```bash
python3 __SKILL_DIR__/scripts/check_mermaid.py <笔记.md 或笔记目录>
```

- 有 `[ERROR]` 输出时，Obsidian 中对应 mermaid 块会显示红色报错，**必须修复**后重新运行直至全部 OK。
- 常见错误与修法：

| 错误码 | 级别 | 场景 | 错误写法 | 正确写法 |
|---|---|---|---|---|
| **E1** | ERROR | flowchart **未加引号**的 edge label 含 `<br/>` / `\n` | `-->|简单任务<br/>如天气查询|` | `-->|"简单任务<br/>如天气查询"|`（**加双引号**） |
| **E2** | ERROR | mermaid 围栏未闭合 | 缺结束 ` ``` ` | 补上 ` ``` ` |
| **E3** | ERROR | 图表类型缺失/拼错 | ` ```mermaid ` 后第一行空白或错误 | 首行写 `flowchart TD` / `mindmap` 等 |
| **E4** | ERROR | code 段（`` `…` `` **或** `<code>…</code>`）以 `=` 开头，触发 Dataview 误解析 | `` `===` ``、`<code>===</code>` | `` `(===)` `` 或 `= `a / b`` |
| **W1** | WARN | mindmap 括号节点含 `<br/>`（个别渲染器不渲染） | `root((提示词<br/>六大要素))` | `root((提示词六大要素))` 或 markdown 字符串 |
| **W2** | WARN | 节点标签含字面 `\n` | `["第一行\n第二行"]` | `["第一行<br/>第二行"]` |
| **W3** | WARN | 用了 `<br />`（带空格），Mermaid 不识别 | `<br />` | `<br/>` 或 `<br>` |
| **W4** | WARN | **timeline** 图含 `<br/>`（Obsidian 下不渲染，显示字面 `<br/>`） | `1956 : 会议<br/>诞生` | `1956 : 会议 : 诞生`（**冒号分隔为多事件**） |

> **核心记忆 1（edge label 的引号规则）**：Mermaid flowchart 的 edge label（`|...|`）**支持 `<br/>`，
> 但必须用双引号包裹**——`|"换行<br/>文本"|` 合法，`|换行<br/>文本|` 不带引号时会因 `< > /`
> 特殊字符导致解析失败。**节点标签**用方括号 `["...<br/>..."]` 本就合法。简言之：**带 `<br/>` 的
> 标签一律加引号**（节点用 `[]`、边用 `|""|`），最稳妥。
>
> **核心记忆 2（Dataview 触发）**：Obsidian Dataview 把**渲染后的 code 元素**当 inline query 扫描——
> 凡 code 文本**以 `=` 开头**就执行。所以 `` `===` `` 会弹 `PARSING FAILED`。
> ⚠️ **换成 `<code>===</code>` 没用**：它渲染出的 code 元素文本仍是 `===`，照样触发（这是最容易踩的坑）。
> 正确修法三选一：① 用非 `=` 字符开头，如 `` `(===)` ``；② 把 `=` 移到 code 外，如 `` = `a / b` ``；
> ③ 根治：Obsidian 设置 → Dataview → **Inline Query Prefix** 从 `=` 改为 `dv=`，全库一次性永久生效。

**7d — 思考题答案核验**：
```bash
for f in <out_dir>/[0-9]*.md; do
  q=$(grep -c '\[!QUESTION\]' "$f"); a=$(grep -c '\[!SUCCESS\]' "$f")
  [ "$q" -gt 0 ] && [ "$a" -eq 0 ] && echo "⚠️  $f 有思考题但缺参考答案"
done
```

**7e — 成稿外链可达性核验（必做，直击"图片无法显示"）**：
```bash
# 仅报告；发现不可达的 OSS 图，加 --images-dir 自动重传修复后复检
python3 __SKILL_DIR__/scripts/check_links.py <笔记.md 或笔记目录> \
  --images-dir /tmp/doc_notes_<name>/images
```
- 扫成稿 MD 里**真正引用的**所有 http(s) 图片/链接 URL，逐个 HTTP 回读，确认能正常展示。
  这是 Step 2 上传期校验之外的**最终防线**——能兜住手动拼的、外链的、漏网的 URL。
- **DOCX 来源**：`extract_docx.py` 已将 Word 内嵌超链接（`w:hyperlink`）提取为 `[text](url)` Markdown 格式，这些链接会一并被扫到并校验。
- 有 `[ERROR]` 时：给了 `--images-dir` 会自动调 `upload_oss.py` 全量重传修复再复检；
  仍不可达的需人工排查（OSS 公共读 / 防盗链 / 链接本身失效）。**必须修到 0 个不可达**。

**7f — 完成报告**：先按以下格式输出自检 checklist，再附摘要。
```
## 质量核查结果
- [x] 内容守恒：verify_content RATIO=xx.x% PASS（type=xxx）；数字 0 处 MISSING，枚举 0 处 FLAG
- [x] Mermaid 语法：check_mermaid 0 ERROR，0 WARN
- [x] 章节无遗漏：原文 N 个 H2，笔记已覆盖 N 个
- [x] 配图充分：Mermaid N 个 + LaTeX 公式 M 处 + HTML 卡片 K 个（每个 H2 ≥1 图）
- [x] 思考题均有参考答案
- [x] 无 `\n` 换行、无残留 `<!-- FILL -->`
```
摘要：output dir、files created、图片处理统计（嵌入 / 重绘 Mermaid / 转 LaTeX / 转卡片）、
Mermaid 数量、版本差异（technical）或"概念类已跳过版本重对齐"（conceptual）、思考题数量。

## Arguments (extract_docx.py)

| Arg | Default | Description |
|---|---|---|
| `doc_path` | — | Absolute path to `.docx` / `.doc` / `.pdf` |
| `--output-dir` | `/tmp/doc_notes_<name>` | Override extraction output dir |
| `--max-img-px` | 2000 | Resize images larger than this (any side) |
| `--split-level` | `auto` | Chapter split level: `auto` / `2` / `3` |
| `--no-split` | off | **推荐默认**：全部内容写入单个 `chapter_01.json`。写完 MD 后用 `wc -c` 检查**成稿大小**，超过 5 MB 再按 H2 手动拆分。 |
| `--min-sections` | 15 | Merge small same-parent chapters below this size (0 disables) |

### How chapters are split (one file per top-level chapter)

**`--no-split`（推荐默认）：全部内容放到单一 MD 文件，只有成稿超过 5 MB 时才拆分。**
适用于所有文档类型（`.docx` / `.doc` / `.pdf`）。运行后产出一个 `chapter_01.json`，
写成 MD 后用 `wc -c` 检查**成稿大小**；超过 5 MB 再按 H2 标题手动拆成多文件（见 Step 6d）。

**默认（不加 `--no-split`）：按 H2 每章一文件。** A document's `1.` `2.` `3.`
headings are the natural units, so a typical doc becomes just **a few files** (e.g. Flink
基础 → 3 files), not a swarm. Falls back to H1/H3 only when H2 is absent. 仅超大型参考手册按需使用。

> **A large chapter is NOT auto-split.** The 120s timeout limits a single Edit, not a file.
> A big chapter (e.g. 256 sections) is written safely via **skeleton → per-`###` Edit fill**.
> The script prints a heads-up for oversized chapters; only if one is unwieldy, re-run that
> doc with `--split-level 3` to break it up.

- `--no-split` — 单文件模式，写完检查大小。
- `--split-level 2` (default auto) / `3` — force coarser or finer.
- `--min-sections 15` — if you ever opt into H3 splitting, small same-parent chapters merge
  (carrying a `headings` list like `1.1` `1.2` `1.3`) so you don't get tiny files.

A "section" = one heading / paragraph / code block / list item / table / image (not words).
Content is conserved exactly across all chapter files (nothing dropped or duplicated).

## Batch processing

```bash
for f in "/path/to/资料"/*.docx; do
  [[ "$f" == *"(1).docx" ]] && continue   # skip duplicate copies
  python3 .../extract_docx.py "$f"
done
```

## Edge cases & compatibility

| Situation | Handling |
|---|---|
| `.doc` (legacy binary) | Auto-converted to `.docx` via `textutil` (macOS); else asks user to convert |
| Code in single-cell tables (多易 style) | Detected → code block with language from first line |
| Code as monospace paragraphs (other vendors) | Detected by font name → code block |
| No font-size headings (structure via numbering) | Falls back to `1.`/`1.1` numbering depth |
| No H2 chapters at all | Splits at H1, then H3; if none, single file (warns) |
| Huge chapter (>90 sections) | `auto` split drops to H3 for manageable files |
| Image > 2000px | Auto-resized before upload & visual analysis |
| Duplicate image in doc | Deduped (md5) — uploaded once |
| PDF prose fragmented | Spans merged per block, not per span |
| Image embedded in table cell | Extracted as image, not lost |
| Code only exists as a screenshot | OCR baseline (`ocr_image.py`) + vision correction → code block |
| Scanned PDF (no text layer) | `extract_docx.py` yields few sections; run `ocr_image.py` on page images |

See [REFERENCE.md](REFERENCE.md) for Mermaid rules, the diagram decision table,
language mapping, callout formats, and the per-chapter quality checklist.
