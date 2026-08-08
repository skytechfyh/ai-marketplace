# 核查脚本：用法与输出解读

四个核查脚本被两条格式路径共用（docx/pdf 见 [extract-docx-pdf.md](extract-docx-pdf.md) A7，
mhtml 见 [extract-mhtml.md](extract-mhtml.md) B6）。本文件是"怎么读输出、出问题怎么修"的统一
说明；具体调用命令、笔记专属的 checklist 项目仍在各自的 reference 文件里，因为两条路径的输出结构
不同（docx/pdf 按章节拆分多文件，mhtml 固定单文件模板），核查维度的具体条数也不同。

核查哲学：**整理 = 提炼 + 重组 + 图解，不是摘要**——源文档的每个事实点都必须在笔记中保留。
`wc -c`/`wc -m` 单纯数整篇字符数是坏的检查方式：HTML 卡片的 inline style、Mermaid 代码块、
LaTeX 公式会贡献海量字符，"堆图堆公式"就能轻松冲过大小线，**正文散文掉了一半也照样达标**。
下面这些脚本都是为了堵住这个漏洞而写的。

## verify_content.py

```bash
# docx/pdf 路径：原文基线来自 extract_docx.py/extract_batch.py 产出的 manifest.json
python3 __SKILL_DIR__/scripts/verify_content.py <manifest.json> <笔记.md 或笔记目录> --type <technical|conceptual>

# mhtml 路径：原文基线直接从原始 .mhtml 文件解析
python3 __SKILL_DIR__/scripts/verify_content.py <原始.mhtml 绝对路径> <笔记.md> --type <technical|conceptual>
```

脚本按第一个参数的文件类型自动判断取原文基线的方式（`manifest.json` → 结构化字段；`.mhtml`/`.html`
→ 解析原始网页文本），下游的核验逻辑完全一致：

1. **RATIO 检查**：剥离笔记里的 frontmatter / Mermaid 代码块 / HTML 标签 / callout 前缀 / LaTeX
   标记后，只数**纯散文字符**，与原文纯散文字符（docx/pdf 路径不计入 `code`/`table` 类型
   section——它们在笔记里基本原样保留，计入会让基数虚高、掩盖叙述被压缩的问题）比对：
   - `technical`（代码/架构密集）：阈值 **60%**（正文之外还有代码/图表等内容，阈值放松）
   - `conceptual`（散文/管理/软技能）：阈值 **80%**（无代码可丢，散文保真度要求更高）
   - `RATIO` 行输出 **PASS/FAIL**。FAIL 说明叙述被过度压缩，回原文把缺的内容补回，**不要靠堆图
     凑字数**。
2. **关键数字核查**：从原文抽取具体数值（500 / 12 / 27 …），逐一在笔记中查找，缺失标 `[MISSING]`。
   丢失往往意味着统计/引用被删。
3. **长顿号枚举核查**：抽取原文中 ≥5 项的顿号并列枚举（如"使用电脑、学习语言、设计算法、开发
   功能、遵循规范"），当 ≥60% 的项在笔记中找不到，判定为该条长枚举被整体丢弃，标 `[FLAG]`。
4. **结构化列表枚举核查**（仅 docx/pdf 路径，manifest 里连续 ≥5 条 `list_item` 的分组——讲义/PPT
   型 PDF 的标签墙/工具清单常以这种逐行罗列而非顿号散文出现）：同样逐项核对是否被保留，与
   "长顿号枚举核查"互补。

脚本**只抓离散 token 丢失**（数字、枚举项整体消失），抓不住"提到但没展开"——例如"四大目的"
被点名但没有逐条解释，脚本不会报警，这类问题仍需人工对照写作规则判断。输出是**告警**，供你回
原文复核，而非硬性 PASS/FAIL 拍板整篇笔记合格与否（RATIO 行除外，那是硬指标）。

## check_mermaid.py

```bash
python3 __SKILL_DIR__/scripts/check_mermaid.py <笔记.md 或笔记目录>
```

有 `[ERROR]` 输出时，Obsidian 中对应 mermaid 块会显示红色报错，**必须修复**后重新运行直至全部 OK。

| 错误码 | 级别 | 场景 | 错误写法 | 正确写法 |
|---|---|---|---|---|
| **E1** | ERROR | flowchart **未加引号**的 edge label 含 `<br/>` / `\n` | `-->\|简单任务<br/>如天气查询\|` | `-->\|"简单任务<br/>如天气查询"\|`（**加双引号**） |
| **E2** | ERROR | mermaid 围栏未闭合 | 缺结束 ` ``` ` | 补上 ` ``` ` |
| **E3** | ERROR | 图表类型缺失/拼错 | ` ```mermaid ` 后第一行空白或错误 | 首行写 `flowchart TD` / `mindmap` 等 |
| **E4** | ERROR | code 段（`` `…` `` **或** `<code>…</code>`）以 `=` 开头，触发 Dataview 误解析 | `` `===` ``、`<code>===</code>` | `` `(===)` `` 或 `= `a / b`` |
| **E5** | ERROR | `</div>` 闭合标签与 `>` 引用块/callout 之间缺少空行，Obsidian 停留在 HTML 模式，callout 显示为纯文本 | `</div>`<br/>`> [!NOTE] 说明` | `</div>`<br/>（空行）<br/>`> [!NOTE] 说明` |
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
>
> **核心记忆 3（HTML 块 → Markdown 切换）**：Obsidian 渲染器在处理 HTML 块时，必须有**一个空行**才能切换回正常的 Markdown 解析模式。`</div>` 后如果直接跟 `>` callout / 引用块（无空行），渲染器仍停留在 HTML 上下文，`>` 被当作 HTML 的一部分，callout 以**纯文本**显示。修复：在 `</div>` 与 `>` 之间插入一个空行（`check_mermaid.py` 会用 `[E5]` 自动检测此问题）。

## check_links.py

```bash
# 仅报告；发现不可达的 OSS 图，加 --images-dir 自动重传修复后复检
python3 __SKILL_DIR__/scripts/check_links.py <笔记.md 或笔记目录> --images-dir <images 目录>
```

扫成稿 MD 里**真正引用的**所有 http(s) 图片/链接 URL，逐个 HTTP 回读，确认能正常展示。这是图片
上传阶段校验之外的**最终防线**——能兜住手动拼的、外链的、漏网的 URL。有 `[ERROR]` 时：给了
`--images-dir` 会自动调 `upload_oss.py` 全量重传修复再复检；仍不可达的需人工排查（OSS 公共读 /
防盗链 / 链接本身失效）。**必须修到 0 个不可达**。

主要用于 docx/pdf 路径（笔记里会嵌入 OSS 图片 URL）。mhtml 路径的输出规则**禁止任何外部图片
URL**（一律转 Mermaid/HTML 卡片/代码块/表格），因此该路径天然不需要调用本脚本；脚本本身是通用的，
未来其它格式若也会产出外链图片，可直接复用。

## extract_note_claims.py

用于时效性复查（见 [freshness-check.md](freshness-check.md)），从已生成的笔记 frontmatter 与
代码块里机械提取技术声明（`tech`/`classes`/`methods`/`configs`/`deprecated_warnings` 等），
兼容两种 frontmatter 形态（docx/pdf 路径的 `current_version` 字段 / mhtml 路径的 `date` 字段），
不属于日常转换流程的一部分。

## Chapter-End Exercise + Answer（章节思考题 + 参考答案）

docx/pdf 路径（A6c）每章、mhtml 路径（B2 思考题章节）每篇笔记末尾都要求思考题配参考答案，标准
一致：

- 结论先行：每问先给直接结论，再讲原理（机制/为什么），必要时附代码片段、对比表，或指向上文
  具体小节的指针。
- **完整**：每一问都答，不能只答一部分；多小问的题逐条编号对应。
- **正确且最新**：涉及 API 的答案必须与版本重基线（docx/pdf 路径的 A5）一致，旧 API 在答案里
  要给新写法；不得凭空杜撰 API。
- **贴合本章/本文**：问题与答案都只围绕实际讲过的内容，不引入未覆盖的概念。
- 不得用"见上文"之类的空答案敷衍。

**格式**（docx/pdf 路径用 `[!SUCCESS]-`，mhtml 路径用 `[!NOTE]-`，二者语义相同，按各自模板选用）：

```markdown
> [!QUESTION] 思考题
> 1. 问题一（针对本章核心概念，要求理解而非记忆）？
> 2. 问题二（对比 / 原理 / 踩坑类）？
> 3. 问题三（结合最新版本 API 的应用题）？

> [!SUCCESS]- 参考答案（先自己想，再点击展开）
> **1.** 先给结论。再讲为什么（机制 / 原理）。必要时附代码或指向上文小节。
>
> **2.** 同上：结论 → 原理 → 例证。对比题用小表格或「A 是……；B 是……」并列。
>
> **3.** 版本相关的答案必须与「版本说明」一致，给出**当前版本**的正确写法，不杜撰 API。
```

**Worked example（Flink 窗口章节，docx/pdf 路径）**：

```markdown
> [!QUESTION] 思考题
> 1. 为什么 NonKeyed `windowAll` 的并行度只能是 1？能否调大并行度绕过？
> 2. 某个 Kafka 分区长期无数据时，EventTime 窗口的 Watermark 会怎样？如何避免？

> [!SUCCESS]- 参考答案（先自己想，再点击展开）
> **1.** 不能绕过。`windowAll` 没有 key，无法按 key 把数据分散到多个 subtask，所有数据必须
> 汇聚到同一个算子实例做全局聚合，因此 Window Operator 并行度被强制为 1。手动 `setParallelism(n)`
> 会被忽略。要并行就必须先 `keyBy()` 走 Keyed Window（见 3.1）。
>
> **2.** 该分区的 Watermark 会停滞，而下游取 `min(各分区 Watermark)`，于是整体 Watermark 被这个
> 空闲分区拖住，窗口迟迟不触发。解决：`WatermarkStrategy.withIdleness(Duration.ofMinutes(1))`
> 标记空闲分区，使其暂时退出 min 计算，让时间正常推进（见 3.5.3）。
```
