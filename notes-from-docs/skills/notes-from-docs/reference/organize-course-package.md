# 格式专属流程 · 极客时间课程资料包（目录）

本文件是 [SKILL.md](../SKILL.md) Step 0 路由到"资料包目录"输入时的完整流程。与 docx/pdf、mhtml
两条路径不同，这条路径的输入本身已经是**近乎成稿的 md 文件**（配套实操任务文档）+ 可选的 PDF
课件——工作模式是"合并 + 对 PDF 课件做结构化重排"，不是"从非结构化原文深度提炼"。因此**不需要**
`verify_content.py`（见 Step 3 说明）、`extract_note_claims.py`/时效复查、technical/conceptual
文档类型判定，这些是另外两条路径特有的环节，不要套用到这里。

可视化规则（Mermaid 语法禁忌、色板、HTML 卡片模板、callout 类型）统一见
[visualization.md](visualization.md)，本文件不重复列出。

## Prerequisites

- Python 3.10+
- `oss2`：`pip install oss2`
- `pymupdf`：`pip install pymupdf`（用于 PDF 课件提取）

## 📥 输入参数

- `package_dir`：`资料包` 目录绝对路径（如 `01资料包`），内含 `md版本`/`md版`/`md` 开头的子目录
  （实操任务 md 文件）+ 可选根目录 PDF 课件。
- `output_dir`：笔记输出目标目录。

## Step 1 — 运行脚本（图片上传 + PDF 原始提取）

```bash
source ~/.zprofile && python3 __SKILL_DIR__/scripts/organize.py \
  "/path/to/NNxx资料包" \
  "/path/to/SecondBrain/Courses"
```

脚本做的事：
- 合并 `md版本`/`md版`/`md` 子目录下所有 `.md` 文件为一篇笔记，图片走 `upload_oss.py` 的
  `upload_image()` 自动上传（内容 md5 去重，重复图片/重复运行不会产生冗余对象）。
- 若 `package_dir` 根目录下有 PDF 课件，逐页提取标题/正文/表格，以 `## 课件 XX：TITLE` 段落输出
  在合并文档最前面（`--use-claude` 可选：设置 `ANTHROPIC_API_KEY` 后调外部 API 直接重排；默认
  不加此参数，输出逐页原始提取内容，由 Claude Code 在 Step 2 直接重排）。
- 完成后自动跑一遍脚本内置的 Mermaid/表格格式自动修复（`_fix_mermaid_block` /
  `fix_markdown_tables`），打印修复/警告报告。

## Step 2 — 重写课件 section（Claude Code 直接做）

脚本跑完后，读取生成文件，**只重写 `## 课件 ...` section**，`## 动手实操` 之后的内容保持原样
不动（那部分已经是脚本合并好的成稿 md，不需要再改写）。

> ⚠️ **超时防护**：Cloudflare 超时 120s，课件内容较长时禁止一次性 Write 全部内容，必须先写骨架
> 再逐节填充（对应 SKILL.md 全局硬规则 1）。

### Step 2a — 写骨架（Edit，快速完成）

读取原始课件 section，规划 5-8 个主题分组，用 **Edit 工具**把原始 `## 课件 ...` section 整体
替换为只含 `###` 标题 + `<!-- FILL -->` 占位符的骨架，每节不超过 3 行：

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

### Step 2b — 逐节填充（Edit，每次一节）

骨架写完后**逐节**用 Edit 把 `<!-- FILL -->` 替换为该节完整结构化内容。**每次只处理一个 `###`
节**，不合并多节写入；按骨架顺序从第一节到最后一节依次 Edit，不可乱序或跳跃。

每节内容规则：
1. **按主题合并 slides**（不是按页码罗列）分组为 `###` 子节。
2. **图表/卡片/callout/表格具体写法**按 [visualization.md](visualization.md) 的规则执行（Mermaid
   有方向拓扑、HTML 卡片无方向陈列、表格精确查找的判断标准，色板/禁止项/callout 类型表都在那边）。
3. **`###` 子节间用 `---` 分隔**。

## Step 3 — 核验与报告结果

**必须**运行 `check_mermaid.py`（用法见 [verification.md](verification.md)）：Step 2 生成了新的
Mermaid 图，必须核验语法无 `[ERROR]` 才算完成。

**不需要**运行 `verify_content.py`：`## 动手实操` 部分是脚本近乎原样合并的现成 md（未经深度提取
压缩，不存在"散文被压缩掉"的风险）；`## 课件` 部分的完整性由 Step 2 的骨架-填充纪律
（写完核对标题数量与原始提取的页数量级一致）+ `organize.py` 自身的 Mermaid/表格自动修复共同兜底，
与另外两条路径"从非结构化原文深度提炼"的核验需求不同，不要额外调用。

向用户汇报：
- 输出文件路径
- 合并的 MD 文件数、上传图片数
- 课件 section 新增的 Mermaid 图表数
- `check_mermaid.py` 核验结果（有无遗留 WARN）

## Arguments

| Arg | Required | Description |
|-----|----------|-------------|
| `package_dir` | yes | 资料包目录绝对路径（如 `01资料包`） |
| `output_dir` | yes | 输出目录 |
| `--filename` | no | 自定义输出文件名（不含 `.md`），默认取 PDF 封面标题 |
| `--use-claude` | no | 调外部 Claude API 重排 PDF（需要 API key；Claude Code 环境下不需要，Step 2 由 Claude Code 直接重排） |

## Batch processing all packages

```bash
for pkg_dir in "/path/to/course_root"/*/; do
  [[ "$pkg_dir" == *"资料包"* ]] || continue
  source ~/.zprofile && python3 __SKILL_DIR__/scripts/organize.py \
    "$pkg_dir" \
    "__OUTPUT_DIR__"
done
```

## Error handling

| Situation | Behavior |
|-----------|----------|
| 图片文件缺失 | 打印 `[WARN]`，保留原始 markdown 引用 |
| 未找到 md 子目录 | 打印 `[ERROR]`，退出码 1 |
| 输出目录不存在 | 自动创建 |
| 未找到 PDF | 静默跳过，不生成课件 section |
| Mermaid 语法问题 | 脚本尝试自动修复；无法修复时打印 WARNING，人工复核 |
