#!/usr/bin/env python3
"""
Mermaid + Obsidian 渲染检查（doc-to-notes 版）：扫描笔记 .md，检测 Mermaid 语法错误
和会触发 Obsidian 插件误解析的写法，输出 [ERROR] / [WARN] / [OK] 报告。

用法：
    python3 check_mermaid.py <笔记.md 或笔记目录>

检测规则：
    ERROR  — 肯定会导致渲染报错（Mermaid 红框 / Dataview 错误）
    WARN   — 可能在某些版本/渲染器下失败，建议修正
    OK     — 未发现问题

Mermaid 规则：
    [E1] flowchart/graph **未加引号** 的 edge label 含 <br/> 或 \\n
         -->|text<br/>more| 不带引号时，<br/> 里的 < > / 会让解析器混乱 → 报错。
         正确：给 edge label 加双引号 -->|"text<br/>more"|（带引号时 <br/> 合法）。
         注意：节点标签 ["text<br/>more"] 用方括号包裹，本来就合法，不在此规则内。
    [E2] Mermaid 围栏未闭合（缺少结束 ```）
    [E3] 图表类型声明缺失（``` mermaid 后第一行不是合法图表类型）
    [W1] mindmap 节点（括号类）含 <br/>
         mindmap 的 ((...)) 等节点对 HTML 支持有限
    [W2] 任意节点标签含字面 \\n（应改用 <br/>）
    [W3] 使用了 <br />（带空格）—— Mermaid 只认 <br> 或 <br/>，带空格会原样输出
    [W4] timeline 图含 <br/> —— Obsidian 等第三方渲染下不换行，会原样显示字面 <br/>；
         改用冒号 ` : ` 把一个时间点拆成多个事件（period : 事件1 : 事件2 : 事件3）

Obsidian 插件规则：
    [E4] code 段（反引号 `...` 或 HTML <code>...</code>）以 = 开头 → 触发 Dataview 误解析
         Dataview 扫描“渲染后的 code 元素”，凡 textContent 以 = 开头就当 inline query 执行。
         `===` 去掉前缀 = 后剩 ==，解析失败 → PARSING FAILED。
         ⚠️ 换成 <code>===</code> 没用——它渲染出的 code 元素文本仍是 ===，照样触发。
         正确修法：① 用括号等非 = 字符开头 `(===)`；② 把 = 移到 code 外 = `a / b`；
                   ③ 根治：Dataview 设置里把 Inline Query Prefix 从 = 改成 dv=（全库一次性）。
"""

import argparse
import glob
import os
import re
import sys

# ── 合法的 Mermaid 图表类型前缀 ────────────────────────────────────────────────
VALID_DIAGRAM_TYPES = {
    "flowchart", "graph", "sequencediagram", "classdiagram", "statediagram",
    "statediagram-v2", "erdiagram", "gantt", "pie", "mindmap", "timeline",
    "gitgraph", "xychart-beta", "block-beta", "quadrantchart", "sankey-beta",
    "requirementdiagram", "c4context",
}

# edge label：-->|text|, ==>|text|, -.->|text| 等
EDGE_LABEL_RE = re.compile(r'\|([^|\n]+)\|')

FLOW_TYPES = {"flowchart", "graph"}


def is_flow_diagram(diagram_type: str) -> bool:
    return diagram_type.lower() in FLOW_TYPES


def is_mindmap(diagram_type: str) -> bool:
    return diagram_type.lower() == "mindmap"


def is_timeline(diagram_type: str) -> bool:
    return diagram_type.lower() == "timeline"


# mindmap 带括号节点（非方括号）
MINDMAP_PAREN_NODE_RE = re.compile(r'\(+([^)]+)\)+')

# 反引号代码段：`内容`（单反引号，非围栏块）
INLINE_CODE_RE = re.compile(r'`([^`\n]+)`')
# HTML code 标签：<code>内容</code>（Dataview 同样会扫描渲染后的 code 元素）
CODE_TAG_RE = re.compile(r'<code>([^<\n]+)</code>')


# ── 提取 mermaid 块 ───────────────────────────────────────────────────────────

def extract_mermaid_blocks(md: str):
    """
    从 Markdown 提取所有 mermaid 代码块（跳过围栏块内的内容以免误匹配）。
    返回 [(start_line, content_lines, closed), ...]
    start_line 为 ```mermaid 所在行号（1-based），content_lines 不含围栏行。
    closed=False 表示缺少结束 ```。
    """
    blocks = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped in ("```mermaid", "~~~mermaid"):
            fence_char = stripped[0]
            start_line = i + 1
            i += 1
            content = []
            closed = False
            while i < len(lines):
                if lines[i].strip() == fence_char * 3:
                    closed = True
                    i += 1
                    break
                content.append(lines[i])
                i += 1
            blocks.append((start_line, content, closed))
        else:
            i += 1
    return blocks


def extract_fenced_ranges(md: str) -> list:
    """返回所有围栏代码块（任意语言）的行号范围 [(start, end), ...]，用于排除非 Mermaid 围栏块内容。"""
    ranges = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            start = i
            i += 1
            while i < len(lines):
                if lines[i].strip() == fence:
                    ranges.append((start, i))
                    i += 1
                    break
                i += 1
        else:
            i += 1
    return ranges


# ── 检查 Mermaid 块 ───────────────────────────────────────────────────────────

def check_mermaid_block(start_line: int, content_lines: list, closed: bool, filepath: str):
    issues = []
    rel = os.path.basename(filepath)

    if not closed:
        issues.append(("ERROR", "E2", start_line,
                        f"{rel}:{start_line} — mermaid 围栏未闭合（缺少结束 ```）"))
        return issues

    if not content_lines:
        return issues

    first = content_lines[0].strip().lower()
    diagram_type = first.split()[0] if first.split() else ""

    if diagram_type not in VALID_DIAGRAM_TYPES:
        issues.append(("ERROR", "E3", start_line,
                        f"{rel}:{start_line} — 图表类型 '{diagram_type}' 不合法（应为 flowchart/mindmap/… 等）"))

    for idx, line in enumerate(content_lines[1:], start=start_line + 2):
        if is_flow_diagram(diagram_type):
            for m in EDGE_LABEL_RE.finditer(line):
                label = m.group(1).strip()
                # 带双引号的 edge label 支持 <br/>，合法；只标记“未加引号”的
                quoted = label.startswith('"') and label.endswith('"')
                if not quoted and ("<br" in label.lower() or "\\n" in label):
                    issues.append(("ERROR", "E1", idx,
                                   f"{rel}:{idx} — 未加引号的 edge label 含 <br/>/\\n（请加双引号 |\"...\"|）: {line.strip()}"))
                    break

        if is_mindmap(diagram_type):
            for m in MINDMAP_PAREN_NODE_RE.finditer(line):
                if "<br" in m.group(1).lower():
                    issues.append(("WARN", "W1", idx,
                                   f"{rel}:{idx} — mindmap (( )) 节点含 <br/>（多数渲染器可用，个别不渲染；如遇问题改单行或 markdown 字符串）: {line.strip()}"))
                    break

        # [W4] timeline 的 <br/>：Obsidian 等第三方集成下不渲染，会原样显示字面 <br/>。
        # 正确做法：用冒号 ` : ` 把多行拆成同一时间点下的多个事件。
        if is_timeline(diagram_type) and "<br" in line.lower():
            issues.append(("WARN", "W4", idx,
                           f"{rel}:{idx} — timeline 含 <br/>（Obsidian 下不渲染，会显示字面 <br/>；改用冒号 ` : ` 分隔为多个事件）: {line.strip()}"))

        if r"\n" in line:
            issues.append(("WARN", "W2", idx,
                           f"{rel}:{idx} — 节点含字面 \\n（应改用 <br/>）: {line.strip()}"))

        # [W3] <br />（带空格）—— Mermaid 不识别，会原样输出
        if "<br />" in line:
            issues.append(("WARN", "W3", idx,
                           f"{rel}:{idx} — 使用了 <br />（带空格），Mermaid 只认 <br> 或 <br/>: {line.strip()}"))

    return issues


# ── 检查 Obsidian 插件误解析 ──────────────────────────────────────────────────

def check_obsidian_issues(md: str, filepath: str) -> list:
    """检测会触发 Obsidian 插件误解析的写法（与 Mermaid 无关）。"""
    issues = []
    rel = os.path.basename(filepath)
    lines = md.splitlines()

    # 计算围栏块行号范围，跳过围栏块内容（围栏块内的反引号不是 inline code）
    fenced = extract_fenced_ranges(md)
    fenced_lines = set()
    for s, e in fenced:
        for ln in range(s, e + 1):
            fenced_lines.add(ln)

    for i, line in enumerate(lines):
        lineno = i + 1
        if lineno in fenced_lines:
            continue

        # [E4] code 段以 = 开头 → 触发 Dataview inline query 误解析。
        # 关键：Dataview 扫描的是“渲染后的 code 元素”，所以反引号 `=...` 和
        # HTML <code>=...</code> 两种写法同样会触发（换成 <code> 并不能绕过！）。
        for m in INLINE_CODE_RE.finditer(line):
            content = m.group(1)
            if content.lstrip().startswith("="):
                issues.append(("ERROR", "E4", lineno,
                               f"{rel}:{lineno} — 反引号代码段以 '=' 开头，会被 Dataview 当作 inline query 解析: `{content}`"))
        for m in CODE_TAG_RE.finditer(line):
            content = m.group(1)
            if content.lstrip().startswith("="):
                issues.append(("ERROR", "E4", lineno,
                               f"{rel}:{lineno} — <code> 段以 '=' 开头，同样会被 Dataview 解析（<code> 绕不过）: <code>{content}</code>"))

    return issues


# ── 文件级入口 ─────────────────────────────────────────────────────────────────

def check_file(filepath: str) -> list:
    try:
        md = open(filepath, encoding="utf-8").read()
    except OSError as e:
        return [("ERROR", "IO", 0, f"{filepath}: 无法读取 — {e}")]

    issues = []
    for start_line, content_lines, closed in extract_mermaid_blocks(md):
        issues.extend(check_mermaid_block(start_line, content_lines, closed, filepath))
    issues.extend(check_obsidian_issues(md, filepath))
    return issues


def check_path(path: str) -> list:
    if os.path.isfile(path):
        return check_file(path)
    if os.path.isdir(path):
        issues = []
        for f in sorted(glob.glob(os.path.join(path, "**", "*.md"), recursive=True)):
            issues.extend(check_file(f))
        return issues
    return [("ERROR", "IO", 0, f"路径不存在: {path}")]


# ── 主程序 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Mermaid + Obsidian 渲染检查 (doc-to-notes)")
    ap.add_argument("note", help="笔记 .md 路径或目录")
    args = ap.parse_args()

    issues = check_path(args.note)
    errors = [i for i in issues if i[0] == "ERROR"]
    warns = [i for i in issues if i[0] == "WARN"]

    print("=== Mermaid + Obsidian 渲染检查 ===")
    if not issues:
        print("✅ 未发现渲染问题")
        return 0

    for level, code, line, msg in issues:
        print(f"  [{level} {code}]  {msg}")

    print()
    print(f"合计: {len(errors)} 个 ERROR，{len(warns)} 个 WARN")
    if errors:
        print("⚠️  存在 ERROR，请修复后重新运行。")
        print()
        print("常见修复方法:")
        print("  [E1] 给 edge label 加双引号：把 |text<br/>more| 改为 |\"text<br/>more\"|")
        print("  [E2] 补上结束 ``` 围栏")
        print("  [E3] 首行写合法图表类型：flowchart TD / mindmap / sequenceDiagram 等")
        print("  [E4] code 段不能以 = 开头（<code> 也不行！Dataview 扫的是渲染后的 code 元素）。三种修法：")
        print("       ① 改纯文本：`===` → 三个等号 `(===)`（用括号包住，首字符不是 =）")
        print("       ② 把 = 移到 code 外：`= a / b` → = `a / b`")
        print("       ③ 根治：Obsidian 设置 → Dataview → Inline Query Prefix 改成 `dv=`（全库一次性生效）")
        print("  [W1] mindmap 括号节点改为方括号 [text<br/>more] 或纯文本 (text more)")
        print("  [W4] timeline 改用冒号分隔：period : 事件1 : 事件2（不要用 <br/>）")
        return 1

    print("（WARN 多数不致命，但 W2/W4 会显示字面 \\n / <br/>，建议一并修复）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
