---
name: doc-to-notes
description: Convert .docx / .doc / .pdf training or learning documents into structured, up-to-date Obsidian Markdown notes. Scripts parse headings/code/lists/tables/images and split the doc into per-chapter JSON; images upload to Aliyun OSS; oversized screenshots are auto-resized, OCR'd (Apple Vision) and visually analyzed (architecture→Mermaid, code screenshot→code block, data screenshot→table); content is re-baselined to the latest stable version against official docs (concepts/API/config/terminology taught in the new version's voice, old version kept only as migration notes); output is split into one Markdown file per chapter. Big-data tech (Flink/Hadoop/Spark/Kafka) routes to 214_Big_Data. Use when user provides a .docx/.doc/.pdf path to turn into knowledge base notes, mentions 资料转换 / 培训文档整理 / 学习笔记, or processes training materials (e.g. 多易大数据, Flink/Spark/Kafka internal docs).
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
| 表格单元格 | `内容A<br/>内容B` | `内容A\n内容B` |
| callout / 正文段落内联换行 | `说明第一句。<br/>说明第二句。` | `说明第一句。\n说明第二句。` |

> `\n` 在 Markdown 中不会渲染为换行，只会产生乱码或意外空行；`<br/>` 是唯一可靠的内联换行方式。

## Prerequisites

`pip install python-docx oss2 pymupdf pillow ocrmac`
- pillow optional — image resize falls back to macOS `sips`
- ocrmac optional — code/UI screenshot OCR (Apple Vision); falls back to pytesseract

## Workflow

### Step 0 — Extract structure

```bash
source ~/.zprofile && python3 __SKILL_DIR__/scripts/extract_docx.py \
  "/path/to/document.docx"
```

Handles `.docx`, `.doc` (auto-converts via `textutil`), and `.pdf`. Outputs to
`/tmp/doc_notes_<name>/`:
- `manifest.json` — full structure (headings, code, lists, tables, images w/ dimensions)
- `chapter_NN.json` — **one file per chapter** (auto-split at H2, or H3 if chapters are huge)
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

Output structure — one sub-dir per source doc, one `.md` per **top-level chapter**, plus
an index. A typical doc yields just a few files:
```
214_Big_Data/Flink/01_Flink基础/
├── 00-索引.md                 # MOC: links every chapter in order
├── 01-快速认识Flink.md         # = H2 "1.快速认识flink"
├── 02-环境准备与编程入门.md      # = H2 "2.Flink环境准备和编程入门"
└── 03-DataStream编程基础.md    # = H2 "3.DataStream编程基础" (large → fill ### by ###)
```

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
| Code screenshot | **Transcribe into a code block** — use OCR text as the baseline, then **fix indentation/symbols against the image** (OCR alone mangles `{} ; →` and indent) |
| Data / table screenshot | **Rebuild as a Markdown table** |
| UI / config screenshot (operation demo) | **Embed OSS URL** + `[!INFO]` caption ≥3 sentences |
| Decorative / logo | Skip |

> Why both: Apple Vision OCR is fast and gives a text baseline, but errs on dense code;
> your vision Read corrects it. Two signals beat one, and you avoid re-typing long code.

⚠️ **Context control**: Read at most **4 images**, write a compact summary table
(filename · type · key info · decision), then read the next batch. This clears image
base64 from context and prevents request-body overflow.

### Step 4 — Re-baseline content to the latest version (unless `--no-version-update`)

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

### Step 6 — Write each chapter file (skeleton → fill, ONE chapter at a time)

Loop over `chapter_01.json … chapter_NN.json`. For each:

**6a — Skeleton** (single Write, fast): frontmatter + version callout + `###` headings
with `<!-- FILL -->` placeholders. Use the chapter's `parent` field for the breadcrumb.

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

### Step 7 — Write the index + report

- Write `00-索引.md`: a MOC linking every chapter `[[NN-title]]` in order, with a 1-line
  summary each, and a top-level Mermaid overview of the whole doc's structure.
- **Verify every chapter has answered exercises** before reporting done:
  ```bash
  for f in <out_dir>/[0-9]*.md; do
    q=$(grep -c '\[!QUESTION\]' "$f"); a=$(grep -c '\[!SUCCESS\]' "$f")
    [ "$q" -gt 0 ] && [ "$a" -eq 0 ] && echo "⚠️  $f 有思考题但缺参考答案"
  done
  ```
- Report: output dir, files created, images uploaded vs redrawn, Mermaid count,
  version gap summary, and exercise count (questions answered).

## Arguments (extract_docx.py)

| Arg | Default | Description |
|---|---|---|
| `doc_path` | — | Absolute path to `.docx` / `.doc` / `.pdf` |
| `--output-dir` | `/tmp/doc_notes_<name>` | Override extraction output dir |
| `--max-img-px` | 2000 | Resize images larger than this (any side) |
| `--split-level` | `auto` | Chapter split level: `auto` / `2` / `3` |
| `--min-sections` | 15 | Merge small same-parent chapters below this size (0 disables) |

### How chapters are split (one file per top-level chapter)

**Default: one Markdown file per top-level chapter (H2).** A document's `1.` `2.` `3.`
headings are the natural units, so a typical doc becomes just **a few files** (e.g. Flink
基础 → 3 files), not a swarm. Falls back to H1/H3 only when H2 is absent.

> **A large chapter is NOT auto-split.** The 120s timeout limits a single Edit, not a file.
> A big chapter (e.g. 256 sections) is written safely via **skeleton → per-`###` Edit fill**.
> The script prints a heads-up for oversized chapters; only if one is unwieldy, re-run that
> doc with `--split-level 3` to break it up.

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
