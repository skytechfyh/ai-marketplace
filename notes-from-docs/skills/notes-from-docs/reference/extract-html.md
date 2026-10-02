# 格式专属流程 · 通用 .html / .htm

本文件是 [SKILL.md](../SKILL.md) Step 0 路由到本地保存的 `.html`/`.htm` 输入时的补充说明。
**与 docx/pdf 共用同一条主流程**——落位决策、文档类型判定（technical/conceptual）、OSS 上传、
OCR+视觉分析、版本重对齐、骨架填充写作、`verify_content.py`/`check_mermaid.py`/
`check_links.py` 核验，全部照 [extract-docx-pdf.md](extract-docx-pdf.md) 的 A1-A7 执行，
**本文件只覆盖 A0（提取）阶段 html 专属的解析规则**。

**不适用场景**：极客时间（time.geekbang.org）专栏页面请仍走 `.mhtml` +
[extract-mhtml.md](extract-mhtml.md)——那条路径的 Slate.js DOM 结构（`data-slate-string`）、
`articleInfo` 作者提取、文档类型判定信号都是该站点专属的，本文件的标签映射规则不适用。

## Prerequisites

无新增依赖，标准库即可（`urllib` 下载远程图片）。仍需 `oss2`/`pymupdf`/`pillow`/`ocrmac`
——这些是 A1 之后共享流程（OSS 上传、OCR）的依赖，见 extract-docx-pdf.md。

## A0 — 提取结构

**单个 html 文件**（用法与 `extract_docx.py` 完全同构）：

```bash
python3 __SKILL_DIR__/scripts/extract_html.py \
  "/path/to/article.html"
```

> 单篇短文（总 section ≤ 90）可加 `--no-split`；更长的不要加——`chapter_NN.json` 只是处理分块，
> 成稿照样是一篇 md（见 extract-docx-pdf.md A0 的"两个拆分"说明）。

**同一逻辑内容的一批 html 文件**（如某训练营"课前学习资料"目录，每个文件是一讲）—— 用
`extract_batch.py`，与 [extract-docx-pdf.md](extract-docx-pdf.md) A0b 的"课程系列"用法完全一致，
**每个文件成为合并笔记里的一个 H2 章节**：

```bash
python3 __SKILL_DIR__/scripts/extract_batch.py \
  "/path/to/课前学习资料" --pattern "*.html" --title "训练营名-课前学习资料"
```

判断用哪种模式：同一批带连续编号的讲次文件（文件名形如 `NN-MM 序号. 标题.html`）→ 批量；
孤立的单篇网页 → 单文件。

两者都输出与 `extract_docx.py` **完全同构**的 `manifest.json` / `chapter_NN.json` /
`images/`——A1 之后的所有步骤不需要区分"这是 html 来源还是 docx/pdf 来源"，照常处理即可。

## HTML 标签 → section 映射

`extract_html.py` 把 html 解析成与 docx/pdf 相同的 `sections` 列表（schema 见
[extract-docx-pdf.md](extract-docx-pdf.md#extracted-json-schema)）：

| HTML 标签 | section type | 说明 |
|---|---|---|
| `h2`-`h6` | `heading`（level：h2→2, h3→3, h4/h5/h6→4） | 与 docx/pdf 的 H1-H4 上限一致 |
| `h1` | **不生成 section**（丢弃） | 见下方"标题来源"说明——`<h1>` 不可靠，永远不作为标题 |
| `p` | `paragraph`（`<strong>/<b>`→`**粗体**`，`<em>/<i>`→`*斜体*`，`<span class="orange">`→`**粗体**`，`<br>`→`<br/>`） | 段落内嵌 `<img>` 会打断成"前文段落 + 图片 section + 后文段落" |
| `ul`/`ol` > `li` | `list_item`（`ordered` 按父标签、支持嵌套） | `<li><p>...</p></li>` 包装视为透明层，`<p>` 内嵌的 `<img>` 同样会被正确拆出 |
| `table` | `table`（`markdown` 字段） | `<th>`/`<td>` 的 `style="text-align:..."` 转换为 Markdown 对齐语法 |
| `pre > code[class^="language-"]` | `code`（`lang` 字段） | class 里的语言名（如 `language-Plain`）经 `extract_docx.py` 的 `LANG_LABEL_MAP` 映射为 fence 语言；无法识别的标签落到 `text` |
| `blockquote` | `quote` | 内部多个 `<p>` 用 `<br/>` 拼接 |
| `img` | `image` | 见下方"图片处理" |
| `a`（内联） | 转 `[text](href)` 拼入所在段落/列表项/表格单元格/引用块的 `text` | 不单独成 section |
| `hr` | 忽略 | 纯视觉分隔，不承载内容 |
| `div`/`section`/`article`/`body`/`html`/`main`/`figure`/`figcaption` | 透明容器 | 直接递归其子节点，不生成 section |
| `script`/`style`/`nav`/`header`/`footer`/`aside`/`iframe`/`noscript` | **整个子树丢弃** | 防御性剥离——应对不像样本课程资料这么干净的通用网页（带导航栏/广告/评论区） |

**已知局限**：`<img>` 若嵌套在**表格单元格 / `<blockquote>` / 标题**内部（而不是直接在
`<p>`、`<li>` 或顶层），会被内联文本展开逻辑静默丢弃——`<p>`、`<li>`（含 `<li><p>...</p></li>`
包装）内嵌的 `<img>` **已处理**，是实测样本里唯一出现过的嵌套形态。若遇到表格/引用块里的图片
丢失，需要把该图片手动补进对应位置。

## 标题来源（不用不可靠的 `<h1>`）

样本课程资料（23 个文件）里只有 2 个带 `<h1>`，且都混有编辑标记噪音（`【定稿】...副本`、
`✅ 【定稿】...`），也没有任何 `<title>` 元素——`<h1>` 在这类导出内容上不可靠。因此：

- **`<h1>` 永远不生成 heading section**（不判断"干不干净"，直接丢弃），标题**始终**回退到
  `_finalize()` 的默认行为：取文件名（`Path(html_path).stem`）。这与 docx/pdf 路径"找不到
  H1 就用文件名"的兜底逻辑完全一致。
- **批量模式下同理**：`extract_batch.py` 默认 `--title-from filename`，每个文件的章节标题
  直接取文件名（如 `03-01 1. 开篇：课程设计思路、教学思路与学习指南`），不依赖文档内 `<h1>`。
- 若源站点的 `<h1>` 其实可靠（干净、无编辑噪音），当前实现仍不会用它做标题——这是为了单
  文件/批量两种模式行为一致，而非遗漏。如果确有需要用 `<h1>` 做标题的场景，再按需调整
  `extract_html.py`，不要绕开脚本手工改文件名。

## 图片处理

`<img src>` 三种来源都会被下载/读取到本地 `images/` 目录，再走与 docx/pdf **完全相同**的
`save_image()`/`resize_image()`（自动缩放到 `--max-img-px`，默认 2000px）：

| `src` 形式 | 处理方式 |
|---|---|
| `http://`/`https://` 远程 URL（样本资料 107 张图片全部是这种，托管在稳定 CDN） | `urllib.request` 下载，失败打印 `[WARN]` 并跳过该图（不中断整体提取） |
| `data:image/...;base64,...` 内联图片 | 直接 `base64` 解码 |
| 裸本地路径（相对/绝对文件路径） | 相对 html 文件所在目录解析后读取 |

下载到本地后，图片在 manifest 里与 docx/pdf 抽取的图片**没有任何区别**——A3（`upload_oss.py`
上传）、A4（`ocr_image.py` OCR + 视觉分析，决定重绘 Mermaid/转代码块/转表格/转 LaTeX/嵌入
OSS+`[!INFO]`/跳过）照常执行，不需要因为图片"原来是远程的"而特殊处理。

## 核验注意事项

`verify_content.py` 走 **manifest 分支**，传参与 docx/pdf 路径完全一致：

```bash
python3 __SKILL_DIR__/scripts/verify_content.py \
  /tmp/doc_notes_<name>/manifest.json <笔记.md 或笔记目录> --type <technical|conceptual>
```

**不要把原始 `.html` 文件路径传给 `verify_content.py`**——脚本按扩展名分派，`.html`/`.htm`
会命中一条明确报错（提示改传 manifest.json），不会误算出错误的核验基线。这与 mhtml 路径不同：
mhtml 走的是"直接解析原始文件"的 source 分支，html 走的是"先提取成 manifest 再核验"的
manifest 分支，两者路径不通用。

## Error handling

| Situation | Behavior |
|---|---|
| `<img>` 下载失败（网络错误/404/超时） | 打印 `[WARN]`，跳过该图，不中断提取 |
| 输入是完整网页（含 `<html>/<head>/<body>`） | 自动识别，`<script>/<style>/<nav>` 等噪音标签整体剥离后再解析正文 |
| html 结构畸形（标签未闭合等） | 解析器按"就近匹配已开启标签"容错处理，不会中断 |
| 一批文件文件名形如 `NN-MM 序号. 标题.html`（如样本课程资料） | `extract_batch.py` 的自然排序按文件名中**所有数字**排序（不是只取第一个），确保 `03-01`…`03-23` 顺序正确，不会被开头相同的 `03-` 前缀打乱 |
