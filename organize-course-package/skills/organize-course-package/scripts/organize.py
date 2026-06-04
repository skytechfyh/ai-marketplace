#!/usr/bin/env python3
"""
Combine GeekTime 资料包 MD task files (实操任务 + SDD训练) into one Markdown file.
Also extracts PDF 课件 from the package root and prepends it as a structured section.
Uploads local images directly to Aliyun OSS via oss2 SDK.

Usage:
    python3 organize.py <package_dir> <output_dir> [--filename <name>]

Requires: oss2  (pip install oss2)
Optional: PyMuPDF / fitz  (pip install pymupdf)  — enables PDF extraction
"""

import sys
import os
import re
import argparse
import datetime
from pathlib import Path

try:
    import oss2
except ImportError:
    sys.exit("[ERROR] oss2 not installed. Run: pip install oss2")

try:
    import fitz  # PyMuPDF
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

try:
    import anthropic as _anthropic_mod
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# OSS configuration (mirrors PicGo settings)
_OSS_ACCESS_KEY_ID     = os.environ.get("OSS_ACCESS_KEY_ID", "")
_OSS_ACCESS_KEY_SECRET = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
_OSS_BUCKET_NAME       = "sky-obsidian-images"
_OSS_ENDPOINT          = "https://oss-cn-shanghai.aliyuncs.com"
_OSS_PATH_PREFIX       = "images/"
_OSS_CUSTOM_DOMAIN     = "sky-obsidian-images.oss-cn-shanghai.aliyuncs.com"

_auth   = oss2.Auth(_OSS_ACCESS_KEY_ID, _OSS_ACCESS_KEY_SECRET)
_bucket = oss2.Bucket(_auth, _OSS_ENDPOINT, _OSS_BUCKET_NAME)

# Maps original abs path → remote URL, avoids re-uploading the same file twice.
_cache: dict[str, str] = {}

# Bullet characters used in Chinese slide decks
_BULLET_CHARS = frozenset("•·–—▪◦‣⁃")

# Math / logic operators that signal a key-insight line worth quoting.
# Intentionally excludes plain "=" (too common in general text like "x = value").
_MATH_OPS = frozenset("≠×÷→←⇒⟹")


# ---------------------------------------------------------------------------
# OSS upload
# ---------------------------------------------------------------------------

def upload_image(src_path: str, unique_name: str) -> str | None:
    """Upload src_path to OSS as unique_name and return the public URL."""
    if src_path in _cache:
        return _cache[src_path]

    if not os.path.exists(src_path):
        print(f"  [WARN] not found: {src_path}", file=sys.stderr)
        return None

    ext = Path(src_path).suffix
    oss_key = f"{_OSS_PATH_PREFIX}{unique_name}{ext}"
    try:
        _bucket.put_object_from_file(oss_key, src_path)
        url = f"https://{_OSS_CUSTOM_DOMAIN}/{oss_key}"
        _cache[src_path] = url
        return url
    except Exception as e:
        print(f"  [ERROR] OSS upload failed for {src_path}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def _render_table_md(table) -> str:
    """Convert a PyMuPDF Table object to a Markdown table string."""
    data = table.extract()
    if not data or not data[0]:
        return ""
    rows: list[str] = []
    for r, row in enumerate(data):
        cells = [str(c or "").replace("\n", " ").strip() for c in row]
        rows.append("| " + " | ".join(cells) + " |")
        if r == 0:
            rows.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(rows)


def _format_body_lines(lines: list[str]) -> list[str]:
    """
    - Lines starting with a bullet character → markdown `- ` list items.
    - Short lines containing math/logic operators → Obsidian [!QUOTE] callouts.
    - Everything else → unchanged.
    """
    result: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s[0] in _BULLET_CHARS:
            result.append(f"- {s[1:].strip()}")
        elif any(c in _MATH_OPS for c in s) and 4 <= len(s) <= 60:
            result.append(f"> [!QUOTE]\n> {s}")
        else:
            result.append(s)
    return result


def _join_body_lines(formatted: list[str]) -> str:
    """
    Smart paragraph joining:
    - Consecutive `- ` list items → single newline (stay in same list block).
    - Each [!QUOTE] callout → its own paragraph (blank line above and below).
    - Plain text → grouped into paragraphs separated by blank lines on block change.
    """
    if not formatted:
        return ""

    paragraphs: list[str] = []
    current_block: list[str] = []
    current_type = "text"

    def flush() -> None:
        if current_block:
            paragraphs.append("\n".join(current_block))
        current_block.clear()

    for line in formatted:
        if line.startswith("> [!"):
            flush()
            current_type = "text"
            paragraphs.append(line)
        elif line.startswith("- "):
            if current_type != "list":
                flush()
                current_type = "list"
            current_block.append(line)
        else:
            if current_type == "list":
                flush()
                current_type = "text"
            current_block.append(line)

    flush()
    return "\n\n".join(paragraphs)


def _cover_abstract(page) -> str:
    """Build an [!ABSTRACT] callout from the cover slide (page 0)."""
    lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    if not lines:
        return ""
    title = lines[0]
    if len(lines) > 1:
        detail = "  \n> ".join(lines[1:])
        return f"> [!ABSTRACT] 课件摘要\n> **{title}**  \n> {detail}\n"
    return f"> [!ABSTRACT] 课件摘要\n> **{title}**\n"


def _process_slide(page) -> tuple[str, str] | None:
    """
    Process one PDF slide page.
    Returns (title, body_md) or None if the page should be skipped (≤2 lines).
    Tables are extracted via find_tables() and rendered as Markdown tables;
    their cell text is deduplicated from the plain-text body.
    """
    raw_lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    if len(raw_lines) <= 2:
        return None

    title = raw_lines[0]
    body_lines = raw_lines[1:]

    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []

    if tables:
        # Collect all text present in table cells to avoid duplicates in body text
        table_cell_texts: set[str] = set()
        table_mds: list[str] = []
        for tbl in tables:
            md = _render_table_md(tbl)
            if md:
                table_mds.append(md)
            for row in (tbl.extract() or []):
                for cell in (row or []):
                    if cell:
                        for cell_line in str(cell).splitlines():
                            cl = cell_line.strip()
                            if cl:
                                table_cell_texts.add(cl)

        non_table = [l for l in body_lines if l not in table_cell_texts]
        parts: list[str] = []
        body_text = _join_body_lines(_format_body_lines(non_table))
        if body_text:
            parts.append(body_text)
        parts.extend(table_mds)
        body_md = "\n\n".join(parts)
    else:
        body_md = _join_body_lines(_format_body_lines(body_lines))

    return title, body_md


# ---------------------------------------------------------------------------
# Claude API — PDF restructuring
# ---------------------------------------------------------------------------

_PDF_RESTRUCTURE_PROMPT = """\
以下是极客时间课件的 PDF 幻灯片逐页提取内容（标题 + 正文）。

请将这些内容重新整理为结构化的学习笔记，严格遵守以下规范：

【结构要求】
- 按主题合并相关幻灯片（不要按页码展示），用 ### 作章节标题
- 章节顺序遵循课件的内在逻辑，而非幻灯片顺序

【Mermaid 图表（最重要）】
遇到以下内容必须生成 Mermaid 代码块：
1. 层级 / 分层架构 → graph TD + subgraph
2. 演进路径 / 阶段递进 → graph LR
3. 流程 / 步骤 → graph TD 或 graph LR
4. 对比 / A vs B → graph LR 并排 subgraph
5. 知识体系总览 → mindmap
图表节点内换行用 <br/>，不用 \\n。
统一色板：
  起点/入口：fill:#4CAF50,stroke:#388E3C,color:#fff
  核心概念：fill:#2196F3,stroke:#1565C0,color:#fff
  结果/输出：fill:#FF9800,stroke:#E65100,color:#fff
每个 Mermaid 图表上方加一行说明，格式：> 📊 [图表描述]

【Obsidian Callout】
- 核心概念定义 → [!NOTE]
- 关键数据/统计 → [!INFO]
- 最佳实践/技巧 → [!TIP]
- 核心洞见/金句 → [!QUOTE]
- 作业/任务 → [!QUESTION]

【其他规范】
- 表格数据保留为 Markdown 表格
- 代码块保留原样
- 输出纯 Markdown，不加任何额外说明或前缀
- 章节间用 --- 分隔线

课件标题：{title}

原始幻灯片内容：
---
{raw_slides}
---
"""


def restructure_pdf_with_claude(raw_slides_md: str, course_title: str) -> str | None:
    """
    Send raw page-by-page slide text to Claude API and get back structured
    Markdown with themed sections and Mermaid diagrams.
    Returns the restructured string, or None if Claude is unavailable.

    Environment variables:
      ANTHROPIC_API_KEY   — required
      ANTHROPIC_BASE_URL  — optional, override the API endpoint (e.g. a proxy)
      ANTHROPIC_MODEL     — optional, defaults to claude-sonnet-4-6
    """
    if not _ANTHROPIC_AVAILABLE:
        print("  [WARN] anthropic not installed — raw output kept. Run: pip install anthropic", file=sys.stderr)
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    if not api_key:
        print("  [WARN] ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN not set — raw output kept", file=sys.stderr)
        return None

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    client_kwargs: dict = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = _anthropic_mod.Anthropic(**client_kwargs)
    prompt = _PDF_RESTRUCTURE_PROMPT.format(title=course_title, raw_slides=raw_slides_md)

    url_hint = f" [{base_url}]" if base_url else ""
    print(f"    → Claude restructuring ({model}{url_hint})...", end=" ", flush=True)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        result = msg.content[0].text
        print(f"done ({len(result)} chars)")
        return result
    except Exception as e:
        print(f"failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def collect_root_pdfs(package_dir: Path) -> list[Path]:
    """Return PDFs directly inside package_dir (not in subdirectories)."""
    return sorted(
        [f for f in package_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"],
        key=lambda f: f.name,
    )


def extract_pdf_content(pdf_path: Path, use_claude: bool = True) -> tuple[str, str]:
    """
    Extract slide content from a PDF.
    Returns (abstract_callout, slides_md).
    The cover page (page 0) becomes the [!ABSTRACT] callout and is not repeated as a slide.
    When use_claude=True and ANTHROPIC_API_KEY is set, the raw slide text is sent to
    Claude for restructuring into themed sections with Mermaid diagrams.
    """
    if not _FITZ_AVAILABLE:
        msg = "> ⚠️ PyMuPDF 未安装，无法提取 PDF 内容。运行 `pip install pymupdf` 后重试。\n"
        return msg, ""

    doc = fitz.open(str(pdf_path))
    abstract = ""
    slides: list[str] = []

    for i, page in enumerate(doc):
        if i == 0:
            abstract = _cover_abstract(page)
            continue  # Cover page → abstract only, not a regular slide section

        result = _process_slide(page)
        if result is None:
            continue
        title, body_md = result
        slides.append(f"### {title}\n\n{body_md}" if body_md else f"### {title}")

    doc.close()
    raw_slides_md = "\n\n".join(slides)

    if use_claude and raw_slides_md.strip():
        restructured = restructure_pdf_with_claude(raw_slides_md, pdf_path.stem)
        if restructured:
            return abstract, restructured

    return abstract, raw_slides_md


def build_pdf_section(pdf_path: Path, use_claude: bool = True) -> tuple[str, str]:
    """Process one PDF file. Returns (abstract_callout, section_md)."""
    stem = pdf_path.stem
    print(f"\n  [PDF] {stem}")
    abstract, slides_md = extract_pdf_content(pdf_path, use_claude=use_claude)
    section_md = f"## {stem}\n\n{slides_md.strip()}"
    return abstract, section_md


# ---------------------------------------------------------------------------
# MD file processing
# ---------------------------------------------------------------------------

def find_md_folder(package_dir: Path) -> Path | None:
    for name in ["md版本", "md版", "md"]:
        p = package_dir / name
        if p.is_dir():
            return p
    for item in sorted(package_dir.iterdir()):
        if item.is_dir() and item.name.lower().startswith("md"):
            return item
    return None


def collect_md_files(md_folder: Path) -> list[Path]:
    return sorted(
        [f for f in md_folder.iterdir() if f.is_file() and f.suffix == ".md"],
        key=lambda f: f.name,
    )


def process_md_file(md_file: Path, md_folder: Path, file_index: int, pkg_prefix: str) -> str:
    """
    Read a single MD file, upload every local image with a unique OSS name,
    and return the processed markdown content.

    unique_name format: {pkg_prefix}_f{file_index:02d}_img{img_index:03d}
    pkg_prefix (e.g. "p01") ensures images from different packages never overwrite each other.
    """
    content = md_file.read_text(encoding="utf-8")
    img_pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
    img_counter = 0

    def replace_image(match: re.Match) -> str:
        nonlocal img_counter
        alt = match.group(1)
        rel_path = match.group(2)

        if rel_path.startswith(("http://", "https://")):
            return match.group(0)

        abs_path = str(md_folder / rel_path)
        img_counter += 1
        unique_name = f"{pkg_prefix}_f{file_index:02d}_img{img_counter:03d}"

        url = upload_image(abs_path, unique_name)
        if url:
            print(f"    [{img_counter}] {os.path.basename(rel_path)} → {url[url.rfind('/')+1:]}")
            return f"![{alt}]({url})"
        return f"![{alt} ⚠️上传失败]({rel_path})"

    content = img_pattern.sub(replace_image, content)

    # Collapse 3+ consecutive blank lines → 1 blank line (GeekTime MD source often has double spacing)
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

def pdf_cover_title(pdf_path: Path) -> str:
    """Extract the lecture title from the PDF cover slide (first non-empty line of page 0)."""
    if not _FITZ_AVAILABLE or not pdf_path.exists():
        return ""
    try:
        doc = fitz.open(str(pdf_path))
        lines = [l.strip() for l in doc[0].get_text().splitlines() if l.strip()]
        doc.close()
        return lines[0] if lines else ""
    except Exception:
        return ""


def build_frontmatter(package_dir: Path, doc_title: str) -> str:
    """Build YAML frontmatter with title, course, tags, and today's date."""
    course = package_dir.parent.name
    today = datetime.date.today().isoformat()
    return (
        "---\n"
        f'title: "{doc_title}"\n'
        f'course: "{course}"\n'
        "tags:\n"
        "  - geektime\n"
        "  - agent\n"
        f"date: {today}\n"
        "---\n"
    )


def build_document(
    md_files: list[Path],
    md_folder: Path,
    package_dir: Path,
    pkg_prefix: str,
    pdf_files: list[Path] | None = None,
    use_claude: bool = True,
) -> str:
    sections: list[str] = []
    abstract_blocks: list[str] = []

    # Derive document title: "{pkg_num} {pdf_cover_title}" or package dir name
    m = re.match(r"^(\d+)", package_dir.name)
    pkg_num = m.group(1).zfill(2) if m else ""
    cover_title = pdf_cover_title(pdf_files[0]) if pdf_files else ""
    doc_title = f"{pkg_num} {cover_title}".strip() if cover_title else package_dir.name

    # Process PDFs first (collect abstracts + section content)
    pdf_sections: list[str] = []
    if pdf_files:
        for pdf_file in pdf_files:
            abstract, section_md = build_pdf_section(pdf_file, use_claude=use_claude)
            if abstract:
                abstract_blocks.append(abstract.strip())
            pdf_sections.append(section_md)

    # Document header block: H1 + abstract callout(s) + overview line
    pdf_count = len(pdf_files) if pdf_files else 0
    overview = (
        f"> 共 {len(md_files)} 份实操文档"
        + (f"，{pdf_count} 份课件" if pdf_count else "")
    )
    header_parts = [f"# {doc_title}"]
    if abstract_blocks:
        header_parts.extend(abstract_blocks)
    header_parts.append(overview)
    sections.append("\n\n".join(header_parts))

    # PDF 课件 sections
    sections.extend(pdf_sections)

    # 实操部分 divider
    sections.append(
        "## 动手实操\n\n"
        "> 以下为配套实操任务，包含环境配置、Step-by-step 操作步骤和截图验证。"
    )

    # MD task sections
    for i, md_file in enumerate(md_files, start=1):
        title = md_file.stem
        print(f"\n  [{i}/{len(md_files)}] {title}")
        content = process_md_file(md_file, md_folder, file_index=i, pkg_prefix=pkg_prefix)

        # Demote any H1 headings in the content to H2 so the doc has one clear root
        content = re.sub(r"^# (.+)$", r"## \1", content, flags=re.MULTILINE)

        sections.append(f"## {title}\n\n{content.strip()}")

    body = "\n\n---\n\n".join(sections)
    return build_frontmatter(package_dir, doc_title) + "\n" + body


# ---------------------------------------------------------------------------
# Mermaid validation & auto-fix
# ---------------------------------------------------------------------------

def _fix_mermaid_block(src: str, block_num: int) -> tuple[str, list[str]]:
    """
    Auto-fix known Mermaid syntax issues in a single block.
    Returns (fixed_src, messages).  Messages are prefixed with "auto-fixed:" or "WARNING:".
    """
    fixed = src
    msgs: list[str] = []

    # Fix 1: literal \n inside quoted node labels → <br/>
    # e.g.  A["line1\nline2"]  →  A["line1<br/>line2"]
    def _replace_escaped_newline(m: re.Match) -> str:
        inner = m.group(0)
        if r"\n" in inner:
            msgs.append(r'  auto-fixed: \n in node label replaced with <br/>')
            return inner.replace(r"\n", "<br/>")
        return inner

    fixed = re.sub(r'"[^"]*\\n[^"]*"', _replace_escaped_newline, fixed)

    # Fix 2: real newlines inside quoted labels (happens when PDF text wraps)
    # e.g.  A["line1
    #         line2"]  →  A["line1<br/>line2"]
    def _replace_real_newline_in_label(m: re.Match) -> str:
        inner = m.group(0)
        if "\n" in inner[1:-1]:  # ignore surrounding quotes
            replacement = '"' + inner[1:-1].replace("\n", "<br/>").strip() + '"'
            msgs.append("  auto-fixed: real newline inside node label replaced with <br/>")
            return replacement
        return inner

    fixed = re.sub(r'"[^"]*\n[^"]*"', _replace_real_newline_in_label, fixed)

    # Warn: mismatched subgraph / end count
    n_sub = len(re.findall(r"\bsubgraph\b", fixed))
    n_end = len(re.findall(r"(?m)^\s*end\s*$", fixed))
    if n_sub != n_end:
        msgs.append(f"  WARNING: {n_sub} subgraph(s) but {n_end} end(s) — check manually")

    # Collect subgraph IDs (e.g. "subgraph FOO[...]" or "subgraph FOO")
    subgraph_ids: set[str] = set(
        re.findall(r"(?m)^\s*subgraph\s+([A-Za-z_][A-Za-z0-9_]*)", fixed)
    )

    # Warn: arrows using subgraph IDs as endpoints — Mermaid does not support this.
    # Pattern: "SG_ID --" or "--> SG_ID" on an arrow line (not inside a subgraph declaration)
    if subgraph_ids:
        for arrow_line in re.findall(r"(?m)^\s*[A-Za-z_].*-->.*$", fixed):
            # Skip subgraph declaration lines themselves
            if re.match(r"\s*subgraph\s", arrow_line):
                continue
            for sg_id in subgraph_ids:
                # Match if the subgraph ID appears at the start or end of an arrow
                if re.search(rf"\b{re.escape(sg_id)}\s*--", arrow_line) or \
                   re.search(rf"--[^>]*>\s*{re.escape(sg_id)}\b", arrow_line):
                    msgs.append(
                        f"  WARNING: arrow uses subgraph ID '{sg_id}' directly — "
                        f"connect internal nodes instead (e.g. '{sg_id}_node --> target')"
                    )

    # Collect node IDs actually defined in this block (best-effort)
    defined_ids: set[str] = set()
    for pat in (
        r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[\[({|\"<]",
        r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*-->",
        r"(?m)-->\s*([A-Za-z_][A-Za-z0-9_]*)",
        r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*--",
    ):
        defined_ids.update(re.findall(pat, fixed))

    # Warn: style / classDef statements referencing IDs not seen above
    for m in re.finditer(r"(?m)^\s*style\s+(\S+)", fixed):
        nid = m.group(1)
        if nid not in defined_ids:
            msgs.append(f"  WARNING: `style {nid}` — node '{nid}' not detected in diagram")

    # Warn: graph type line present and valid
    first_line = fixed.strip().splitlines()[0] if fixed.strip() else ""
    valid_starts = (
        "graph ", "flowchart ", "sequenceDiagram", "classDiagram",
        "stateDiagram", "erDiagram", "gantt", "pie", "mindmap",
        "gitGraph", "timeline", "xychart",
    )
    if first_line and not any(first_line.startswith(s) for s in valid_starts):
        msgs.append(f"  WARNING: unexpected first line '{first_line}' — may be missing graph type declaration")

    return fixed, msgs


def validate_and_fix_mermaid(content: str) -> tuple[str, int, int]:
    """
    Scan all ```mermaid blocks in content, auto-fix what we can, warn about the rest.
    Prints a per-block report.
    Returns (fixed_content, total_blocks, total_issues).
    """
    pattern = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
    total_blocks = 0
    total_issues = 0

    def _sub(m: re.Match) -> str:
        nonlocal total_blocks, total_issues
        total_blocks += 1
        src = m.group(1)
        fixed_src, msgs = _fix_mermaid_block(src, total_blocks)
        if msgs:
            total_issues += len(msgs)
            print(f"  [Mermaid #{total_blocks}] {len(msgs)} issue(s):")
            for msg in msgs:
                print(f"  {msg}")
        return f"```mermaid\n{fixed_src}```"

    fixed_content = pattern.sub(_sub, content)
    return fixed_content, total_blocks, total_issues


def fix_markdown_tables(content: str) -> tuple[str, int]:
    """
    Fix common Markdown table issues:
    1. Empty first header cell written as '||...' → '| |...' (Obsidian renders '||' incorrectly)
    2. Table row not preceded by a blank line → insert blank line before the table block
       (Obsidian requires a blank line before a table to render it; a bold label like
       '**检查清单：**' immediately followed by '|...' will display as raw pipe text.)
    Returns (fixed_content, fix_count).
    """
    fix_count = 0
    lines = content.splitlines(keepends=True)
    result: list[str] = []

    def _is_table_row(s: str) -> bool:
        return s.lstrip().startswith("|")

    def _is_blank(s: str) -> bool:
        return s.strip() == ""

    for i, line in enumerate(lines):
        # Fix 1: empty first header cell '||' → '| |'
        if re.match(r"^\|\|", line):
            line = "| " + line[1:]
            fix_count += 1

        # Fix 2: table row not preceded by a blank line
        # Insert '\n' before the first row of a table block when the previous
        # non-skipped output line is non-empty and not itself a table row.
        if _is_table_row(line) and result:
            prev = result[-1]
            if not _is_blank(prev) and not _is_table_row(prev):
                result.append("\n")  # inject blank line
                fix_count += 1

        result.append(line)

    fixed = "".join(result)
    if fix_count:
        print(f"  [Table] auto-fixed {fix_count} table formatting issue(s) ('||' headers / missing blank lines)")
    return fixed, fix_count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def derive_filename(package_dir: Path, provided: str | None, pdf_files: list[Path] | None = None) -> str:
    if provided:
        return provided if provided.endswith(".md") else provided + ".md"
    m = re.match(r"^(\d+)", package_dir.name)
    pkg_num = m.group(1).zfill(2) if m else ""
    cover = pdf_cover_title(pdf_files[0]) if pdf_files else ""
    if cover:
        safe_title = re.sub(r"[^\w一-鿿\-]", "_", cover).strip("_")
        return f"{pkg_num} {safe_title}.md"
    safe = re.sub(r"[^\w一-鿿\-]", "_", package_dir.name).strip("_")
    return f"{safe}.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine 资料包 MD task files into one Markdown note"
    )
    parser.add_argument("package_dir", help="Path to the 资料包 directory")
    parser.add_argument("output_dir", help="Target output directory")
    parser.add_argument("--filename", default=None, help="Output filename (without .md)")
    parser.add_argument("--use-claude", action="store_true",
                        help="Call Claude API to restructure PDF content (requires ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN)")
    args = parser.parse_args()

    package_dir = Path(args.package_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not package_dir.is_dir():
        sys.exit(f"[ERROR] Not found: {package_dir}")

    md_folder = find_md_folder(package_dir)
    if not md_folder:
        sys.exit(f"[ERROR] No md folder found in: {package_dir}")

    md_files = collect_md_files(md_folder)
    if not md_files:
        sys.exit(f"[ERROR] No .md files in: {md_folder}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Derive short package prefix from leading digits in directory name (e.g. "01资料包" → "p01")
    m = re.match(r"^(\d+)", package_dir.name)
    pkg_prefix = f"p{m.group(1).zfill(2)}" if m else "pkg"

    pdf_files = collect_root_pdfs(package_dir)
    output_path = output_dir / derive_filename(package_dir, args.filename, pdf_files or None)

    print(f"[INFO] Package  : {package_dir.name}  (prefix={pkg_prefix})")
    print(f"[INFO] MD folder: {md_folder.name}  ({len(md_files)} files)")
    if pdf_files:
        print(f"[INFO] PDF 课件 : {', '.join(f.name for f in pdf_files)}")
    else:
        print(f"[INFO] PDF 课件 : (none found)")
    print(f"[INFO] Output   : {output_path}")

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    # Claude API restructuring is opt-in (--use-claude). Default is raw output so that
    # the Claude Code skill executor can do the restructuring step directly.
    use_claude = args.use_claude and has_key
    if pdf_files:
        if use_claude:
            base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
            model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            url_part = f"  base_url={base_url}" if base_url else ""
            print(f"[INFO] Claude重排: {model}{url_part}")
        elif not args.use_claude:
            print("[INFO] Claude重排: 跳过（默认，skill 执行者直接重排）")
        else:
            print("[INFO] Claude重排: 跳过（未设置 ANTHROPIC_API_KEY）")
    doc = build_document(md_files, md_folder, package_dir, pkg_prefix, pdf_files=pdf_files or None, use_claude=use_claude)

    # Markdown table fixes
    print("\n[Table] 检查表格格式...")
    doc, table_fixes = fix_markdown_tables(doc)
    if table_fixes == 0:
        print("  ✓ 无问题")

    # Mermaid validation & auto-fix
    print("\n[Mermaid] 检查语法...")
    doc, mermaid_total, mermaid_issues = validate_and_fix_mermaid(doc)
    if mermaid_total == 0:
        print("  (无 Mermaid 图表)")
    elif mermaid_issues == 0:
        print(f"  ✓ {mermaid_total} 个图表，无问题")
    else:
        print(f"  ⚠ {mermaid_total} 个图表，{mermaid_issues} 处需人工检查（见上方 WARNING）")

    # Atomic write: write to a temp file then rename to avoid race conditions with oss_watcher
    tmp_path = output_path.with_suffix(".tmp")
    tmp_path.write_text(doc, encoding="utf-8")
    tmp_path.replace(output_path)

    pdf_info = f", {len(pdf_files)} PDF(s) extracted" if pdf_files else ""
    mermaid_info = f", {mermaid_total} Mermaid 图表" + (f" ({mermaid_issues} 处警告)" if mermaid_issues else "")
    print(f"\n[DONE] {output_path.name}  ({len(_cache)} images uploaded{pdf_info}{mermaid_info})")


if __name__ == "__main__":
    main()
