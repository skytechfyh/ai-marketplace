---
name: notes-from-docs
description: 将学习/培训资料转换为结构化、图解丰富、内容经过机械核验的 Obsidian Markdown 笔记。当前支持三类输入：(1) .docx/.doc/.pdf/.html/.htm 培训文档（含本地保存的通用网页，如训练营课前资料）——解析标题/代码/列表/表格/图片并按章节拆分，图片上传阿里云 OSS（html 的远程图片自动下载后走同一上传流程），超大截图自动缩放+OCR(Apple Vision)+视觉分析（架构图→Mermaid、代码截图→代码块、数据截图→表格、数学公式→LaTeX），技术类文档内容重基线到最新稳定版（旧版仅作为迁移提示保留），支持批量合并同一课程/训练营的多份讲义/讲次为一篇笔记；(2) 极客时间（time.geekbang.org）专栏 .mhtml 文件——提炼为固定结构的单篇笔记（关键概念/原理解析/代码示例/最佳实践/思考题+参考答案/总结mindmap），仅适用于极客时间站点；(3) 极客时间课程资料包目录（含 md版/md版本 子目录的实操任务 md 文件 + 可选 PDF 课件）——合并为单篇笔记，PDF 课件重排为结构化图解，图片上传阿里云 OSS。三条路径共享 Mermaid+HTML卡片可视化规则；docx/pdf/html 与 mhtml 两组路径额外共享 technical/conceptual 文档类型判定、内容守恒机械核验（verify_content.py）、时效性复查流程；三条路径都用 check_mermaid.py 核验 Mermaid 语法。触发场景：用户提供 .docx/.doc/.pdf/.html/.htm/.mhtml 路径或资料包目录要求转换为笔记，提到"资料转换"/"培训文档整理"/"学习笔记"/"批量合并笔记"/极客时间专栏提炼/课程资料包整合，或对已有笔记要求"时效性检查"/核对官方文档是否有过期内容。
---

# Notes from Docs

统一把学习/培训资料转换为结构化 Obsidian Markdown 笔记。本文件只放**编排骨架**——格式检测路由、
对所有格式生效的全局硬规则、共享步骤的指针；具体怎么解析每种格式、怎么写、用什么脚本核查，都在
`reference/` 下按格式或按主题分文件展开。

## Step 0 — 检测输入格式，路由到对应流程

| 输入 | 路由到 |
|---|---|
| `.docx` / `.doc` / `.pdf` 文件路径（单个或一批逻辑上属于一篇内容的文件） | [reference/extract-docx-pdf.md](reference/extract-docx-pdf.md) |
| `.html` / `.htm` 文件路径（本地保存的通用网页，单个或一批逻辑上属于一篇内容的文件；非极客时间专栏） | 同样是 [reference/extract-docx-pdf.md](reference/extract-docx-pdf.md) 这条主流程，A0 提取步骤按 [reference/extract-html.md](reference/extract-html.md) 的规则用 `extract_html.py` |
| `.mhtml` 文件路径，且内容来自 **time.geekbang.org**（极客时间专栏） | [reference/extract-mhtml.md](reference/extract-mhtml.md) |
| `.mhtml` 但非极客时间站点 | **不要**套用极客时间专属提取规则（`data-slate-string`/`articleInfo` 等选择器对其它站点不成立），明确告知用户暂不支持该站点 |
| 目录路径，内含 `md版本`/`md版`/`md` 开头的子目录（实操任务 md 文件，可选 + 根目录 PDF 课件） | [reference/organize-course-package.md](reference/organize-course-package.md) |
| 用户对**已有笔记**发起时效性检查（而非从源文档生成新笔记） | 跳过本文件其余步骤，直接进入 [reference/freshness-check.md](reference/freshness-check.md) |

路由确定后，进入对应 reference 文件的完整步骤序列（docx/pdf/html 路径为 A0…A7，只有 A0
提取步骤按格式分文件——html 见 [extract-html.md](reference/extract-html.md)；mhtml 路径为
B1…B6，资料包目录路径为独立的 Step 1…3），过程中会按需链接回本文件下方的全局规则，以及
[reference/visualization.md](reference/visualization.md)、[reference/verification.md](reference/verification.md)、
[reference/math-latex.md](reference/math-latex.md) 等共享规则文件。`__SKILL_DIR__` 在所有
reference 文件的脚本命令里都指代本 skill 目录（即 `.../skills/notes-from-docs/`）。

## 🚨 全局硬规则（对所有格式生效，优先级最高）

### 规则 1 — Chunk everything（120s 超时）

Cloudflare 代理层超时是 **120s**，单次过大的 Write/Edit 会超时并破坏已写入的状态。因此：
- **脚本承担重活**（提取结构、图片上传等）在一次快速批处理里完成。
- 模型**一次只处理一个输出单元**——docx/pdf/html 路径是一个 `chapter_NN.json`，mhtml 路径是一个
  `##` 章节——绝不在一次调用里处理整个 manifest 或整篇文章。
- 大文件按"骨架 → 逐段 Edit"或"Write → Bash cat >> 逐段追加"的方式分步写入，具体分段节点见
  各自 reference 文件。
- 图片视觉分析**每批最多 4 张**，读完立即归纳成摘要表再读下一批，防止图片 base64 撑爆上下文。

**永远不要**一次性写完多个章节，也永远不要一次性写完整篇正文。

### 规则 2 — 全局换行规则：统一用 `<br/>`，禁止用 `\n`

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

### 规则 3 — 内容守恒规则：提炼重组，绝不删减

整理 = **提炼 + 重组 + 图解**，不是摘要。源文档里的每一个事实点（定义、步骤、参数、案例、
数据、结论、举的每一个例子）都必须在笔记中保留——可以合并同类、改写得更清晰、配图解释，但
**不能丢信息**。

- ✅ 允许：把零散段落按主题合并；口语化表述改写得更准确；长流程配 Mermaid；枚举配表格。
- ❌ 禁止：跳过某个小节；把"讲了 5 点"概括成"讲了几点"；删掉案例只留结论；漏掉某张图承载的信息。
- **单文件/单篇输出模式尤其要警惕**：一次产出所有内容时，必须**逐节**搭骨架、逐节填充，写完后
  核对标题数量与原文章节数一致——确认每个章节都落到成稿里，绝不能写到一半就收尾。

## Step N — 判定文档类型（technical / conceptual，仅 docx/pdf/html、mhtml 两组路径）

docx/pdf/html 与 mhtml 都在各自的解析阶段判定文档类型（docx/pdf/html 见
[extract-docx-pdf.md](reference/extract-docx-pdf.md) 的 A2，html 复用同一判定逻辑，无需
单独定义；mhtml 见 [extract-mhtml.md](reference/extract-mhtml.md) 的 B1），决定可视化强度、
版本重对齐是否执行（仅 docx/pdf/html 路径）、核查阈值（`verify_content.py --type` 取值）。
判定结果必须在输出中显式声明，不输出视为未完成该步骤。资料包目录路径
（[organize-course-package.md](reference/organize-course-package.md)）输入本身已是成稿 md，
不做深度提炼，跳过此步骤。

## Step N — 可视化

按 [reference/visualization.md](reference/visualization.md) 的规则作图：**有方向的拓扑 →
Mermaid；无方向的陈列/矩阵 → HTML 卡片；精确查找 → 表格；数学公式 → LaTeX**（LaTeX 规则见
[reference/math-latex.md](reference/math-latex.md)，目前仅 docx/pdf 路径常用）。

## Step N — 写入文件

具体写入方式（分段策略、目录/文件命名规则、frontmatter 结构、输出模板）完全由输入格式决定，
见各自 reference 文件——docx/pdf/html 路径按原文章节结构拆分，mhtml 路径固定为八段式单文章模板，
不强行统一成同一种输出风格。

## Step N — 内容核验（必做）

用 [reference/verification.md](reference/verification.md) 里说明的脚本核验，核验不通过不算完成
任务：`check_mermaid.py`（Mermaid 语法）三条路径都要跑；`verify_content.py`（内容守恒）、
`check_links.py`（外链可达性）仅 docx/pdf/html、mhtml 两组路径需要（资料包目录路径不做深度提炼，
不适用，原因见 [organize-course-package.md](reference/organize-course-package.md) Step 3）。html
走 `verify_content.py` 的 manifest 分支，用法与 docx/pdf 完全一致（传 `extract_html.py` 产出的
manifest.json，不要传原始 `.html` 文件，见 [extract-html.md](reference/extract-html.md)）。
每种格式的具体核查项清单和通过标准见各自 reference 文件。

## 时效性复查（可选，非日常流程）

用户对**已有笔记**（不论来自哪种源格式生成）要求核对内容是否与官方最新文档一致时，完整流程见
[reference/freshness-check.md](reference/freshness-check.md)。
