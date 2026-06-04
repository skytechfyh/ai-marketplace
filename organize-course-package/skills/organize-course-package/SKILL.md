---
name: organize-course-package
description: Organize a GeekTime-style course resource package (资料包) directory into a single Markdown file for Obsidian. Uploads all local images to Aliyun via PicGo. Use when user wants to organize, consolidate, or convert a course 资料包 directory into a learning note, or mentions GeekTime/极客时间 course materials.
---

# Organize Course Package

Convert a `资料包` directory (md版本 / md版 folder + optional PDF 课件) into one structured `.md` file for Obsidian, with all images uploaded to Aliyun OSS.

## Prerequisites

- Python 3.10+ available
- `oss2` installed: `pip install oss2`
- `pymupdf` installed: `pip install pymupdf` (for PDF extraction)

## Workflow

### Step 1 — Run the script (image upload + raw PDF extraction)

```bash
source ~/.zprofile && python3 __SKILL_DIR__/scripts/organize.py \
  "/path/to/NNxx资料包" \
  "/path/to/SecondBrain/Courses"
```

The script outputs raw page-by-page PDF content under the `## 课件 XX：TITLE` section.

### Step 2 — Rewrite the 课件 section (Claude Code does this directly)

After the script finishes, read the generated file and **rewrite only the `## 课件 ...` section** with structured learning content. Keep everything after `## 动手实操` untouched.

> ⚠️ **超时防护**：Cloudflare 超时为 120s。课件内容较长时，禁止一次性 Write 全部内容。必须分两步完成：先写骨架，再逐节填充。

#### Step 2a — 写骨架（Write，快速完成）

读取原始 课件 section，规划 5-8 个主题分组，然后用 **Edit 工具**将原始 `## 课件 ...` section 整体替换为只含 `###` 标题 + `<!-- FILL -->` 占位符的骨架。每节不超过 3 行。

骨架示例：

```markdown
## 课件 第X节-TITLE

### 主题一：XXX

<!-- FILL -->

---

### 主题二：XXX

<!-- FILL -->

---

### 本节作业

<!-- FILL -->

---
```

**必须包含的固定末节**：`### 本节作业`（对应 PDF 中的作业/任务页）。

#### Step 2b — 逐节填充（Edit，每次一节）

骨架写完后，**逐节**用 Edit 将 `<!-- FILL -->` 替换为该节的完整结构化内容。**每次只处理一个 `###` 节**，不要合并多节写入。

每节内容规则（同下方 Rewrite rules）：按主题合并 slides → Mermaid 图 → Callouts → 表格 → `---` 分隔符。

填充顺序：从第一节到最后一节，按骨架顺序依次 Edit，不可乱序或跳跃。

---

**Rewrite rules for each section（适用于 Step 2b 每节的内容）：**

1. **Merge slides by theme** — group related slides into `###` subsections (not page-by-page)
2. **Mermaid diagrams** — generate for every architecture / flow / evolution / contrast found:
   - Layered architecture → `graph TD` + subgraph per layer
   - Evolution / stages → `graph LR`
   - A vs B comparison → `graph LR` side-by-side subgraphs
   - Knowledge overview → `graph LR` tree (root → branches → leaves) — ⚠️ 禁止用 `mindmap`：该类型需要 Mermaid v9.4+，Obsidian 内置版本可能不支持，会直接显示原始文本
   - Node labels: use `<br/>` for line breaks, never `\n`
   - Color palette: start/entry=`fill:#4CAF50,stroke:#388E3C,color:#fff` · core=`fill:#2196F3,stroke:#1565C0,color:#fff` · output=`fill:#FF9800,stroke:#E65100,color:#fff`
   - Each diagram preceded by `> 📊 [description]`
3. **Mermaid 禁止项（必须遵守）**：
   - ❌ 禁止用 subgraph ID 做箭头端点：`SDD --> H` 无效，必须连接内部节点：`A --> H1`
   - ❌ 禁止节点标签内用 `\n`，必须用 `<br/>`
   - ❌ 禁止在节点标签内使用 Unicode 箭头符号（`→` `←` `↑` `↓`）——Mermaid 解析器可能误判为流向语法，改用纯文字：`->`、`to`、`then` 等
   - ❌ 禁止在 pipe 边标签内使用引号：`-->|"label"|` 无效，必须写 `-->|label|`（Mermaid 解析器不识别 pipe 内的双引号，会导致整个图无法渲染）
   - ❌ 禁止在节点标签内使用圆括号 `()`：Mermaid 解析器在某些版本下会将 `["text (sub)"]` 中的圆括号误判为圆角矩形节点语法。改用方括号 `[]`、中文括号 `（）` 或直接去掉括号，如 `["OpenCode MCP Client"]`
   - ❌ 禁止在 subgraph 内创建有向环（cyclic edges）——即 A→B 同时 B→A。Dagre 布局引擎遇到 subgraph 内环会崩溃或渲染异常。修复方案：
     - 双向关系：把源节点拆成「入口节点」和「出口节点」（同名可加后缀 `_in`/`_out`），避免物理上的环
     - 双向通信（如读写共享板）：只画一侧箭头，在标签内注明 `写入读取`，不画反向边
   - ❌ 禁止在需要跨 subgraph 连接时把外部节点和 subgraph 内节点混用——如确实需要 `外部节点 --> subgraph内节点`，优先将 subgraph 去掉，改为平铺节点 + `style` 着色区分层次
   - ✅ 多个 subgraph 之间的连接：从源 subgraph 内的节点 → 目标 subgraph 内的节点
4. **Callouts** — use Obsidian callout format:
   - Key concepts / definitions → `[!NOTE]`
   - Stats / data → `[!INFO]`
   - Best practices → `[!TIP]`
   - Core insights / quotes → `[!QUOTE]`
   - Assignments / tasks → `[!QUESTION]`
5. **Tables** — preserve all comparison tables in Markdown format
   - ❌ 禁止表格首行使用 `||`（空白首格无空格），必须写 `| |` 或 `| 维度 |` 等有效内容
   - ❌ 表格前必须有**空行**（blank line）——`**标题：**` 与 `|列头|` 之间若无空行，Obsidian 不渲染为表格，直接显示原始管道符文本
6. **Section separator** — `---` between each `###` subsection
7. **Run Mermaid validation** — after rewriting, mentally check: every `subgraph` has a matching `end`, no `style` references undefined nodes, no `\n` in labels, no Unicode arrows in labels, no cyclic edges inside subgraphs, no `mindmap` diagram type used, no quoted pipe labels (`|"..."|` → `|...|`), no ASCII parentheses `()` inside node labels

### Step 3 — Report results

Tell the user:
- Output file path
- Number of MD files merged, images uploaded
- Number of Mermaid diagrams added in the 课件 section
- Whether Mermaid validation found any issues

## Arguments

| Arg | Required | Description |
|-----|----------|-------------|
| `package_dir` | yes | Absolute path to the `资料包` folder (e.g. `01资料包`) |
| `output_dir` | yes | Target directory for the output `.md` file |
| `--filename` | no | Custom output filename (without `.md`); defaults to PDF cover title |
| `--use-claude` | no | Call external Claude API to restructure PDF (requires API key; not needed for Claude Code) |

## Default paths for this project

- Source root: `__SOURCE_DIR__`
- Target dir: `__OUTPUT_DIR__`

## Batch processing all packages

```bash
for pkg_dir in "/Users/fengyuhao/study_materials/ai/多Agent设计与工程化行动营"/*/; do
  [[ "$pkg_dir" == *"资料包"* ]] || continue
  source ~/.zprofile && python3 __SKILL_DIR__/scripts/organize.py \
    "$pkg_dir" \
    "__OUTPUT_DIR__"
done
```

## Error handling

| Situation | Behavior |
|-----------|----------|
| Image file missing | Prints `[WARN]`, keeps original markdown |
| md folder not found | Prints `[ERROR]`, exits with code 1 |
| Output dir missing | Created automatically |
| PDF not found | Skipped silently, no 课件 section |
| Mermaid syntax issue | Auto-fixed if possible; WARNING printed for manual review |
