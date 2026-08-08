#!/usr/bin/env python3
"""
内容完整性核查 (notes-from-docs 合并版)：把"正文是否被压缩 / 关键元素是否丢失"从
"靠自觉"变成"机械可验"。合并自 doc-to-notes 与 mhtml-refine-to-md 两份几乎相同的实现，
按第一个参数是 manifest（结构化提取产物）还是原始网页文件（.mhtml）自动选择取原文
基线的方式。

用法:
    # docx/pdf/html 路径：原文基线来自 extract_docx.py / extract_batch.py / extract_html.py
    # 产出的 manifest.json（html 与 docx/pdf 产出同构的 manifest，走同一分支，用法一致）
    python3 verify_content.py <manifest.json 或提取目录> <笔记.md 或笔记目录> \
        [--type technical|conceptual]

    # mhtml 路径：原文基线直接从原始 .mhtml 文件解析（Slate.js 纯文本）
    python3 verify_content.py <原始.mhtml 绝对路径> <笔记.md> [--type technical|conceptual]

为什么需要这个脚本:
    单纯的 `wc -c`/`wc -m` 文件大小检查是坏的——HTML 卡片的 inline style、Mermaid 代码块、
    LaTeX 公式会贡献海量字符。于是"堆图堆公式"就能轻松冲过大小线，**正文散文掉了一半
    也照样达标**。本脚本剥掉所有标记后只数纯散文字符，再机械核验关键数字/长枚举是否丢失。

两种输入的基线口径不同，因此剥离规则也不同（据此判断走哪条分支）:
    - manifest（.json 文件，或含 manifest.json/chapter_*.json 的目录）：docx/pdf/html
      三条路径通用（html 由 extract_html.py 产出与 docx/pdf 同构的 manifest.json，走
      同一套逻辑，无需区分来源）。基线只取 paragraph/heading/list_item/quote 类型的
      text（code/table 不计入分母——它们在笔记里基本原样保留，计入会让基数虚高、掩盖
      叙述被压缩的问题）。因此笔记侧剥离时也要把 fenced 代码块整体去掉、把 LaTeX 公式
      去掉，口径才对得上。
    - source（仅 .mhtml，极客时间专栏专属）：基线是原始网页的全部可见文本（Slate.js
      纯文本，未做结构分类，代码/公式同样混在其中）。因此笔记侧剥离时**保留**代码块内
      文字（只去掉 ``` 围栏），也不剥离 LaTeX，口径才对得上。

做三件事:
    1. 剥离笔记的 frontmatter / mermaid / HTML / callout / (manifest 路径下)LaTeX 标记，
       只数**纯散文字符**，按文档类型阈值比对原文（technical 60% / conceptual 80%）。
    2. 从原文抽取关键数字 + 长顿号枚举，逐一在笔记中查找，缺失即告警。
    3. 仅 manifest 路径：从原文抽取"结构化列表枚举"——manifest 里连续 ≥5 条 list_item 的
       分组（讲义/PPT 型 PDF 的标签墙/工具清单常以这种逐行罗列而非顿号散文出现），同样
       逐项核对是否被保留。

局限（必须诚实告知）:
    只抓"整条长枚举被压缩""统计数字被删"这类**离散 token 丢失**，抓不住"提到但没展开"。
    输出是**告警 / FLAG**，供你回原文复核，而非硬性 PASS/FAIL 拍板。
"""

import argparse
import email
import glob
import json
import os
import re
import sys


# ── 判断输入类型：manifest（结构化）还是 source（原始网页文件）──────────────────

def detect_source_kind(path: str) -> str:
    if os.path.isdir(path):
        if (os.path.isfile(os.path.join(path, "manifest.json"))
                or glob.glob(os.path.join(path, "chapter_*.json"))):
            return "manifest"
        raise FileNotFoundError(f"目录下找不到 manifest.json 或 chapter_*.json: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return "manifest"
    if ext == ".mhtml":
        return "source"
    if ext in (".html", ".htm"):
        raise ValueError(
            f"{path}: html 路径请传 extract_html.py 产出的 manifest.json（或其所在目录），"
            f"不要传原始 .html 文件——html 与 docx/pdf 走同一条 manifest 基线，"
            f"不是这里的 source 分支（source 分支仅 .mhtml 适用）。")
    raise ValueError(f"无法识别的输入类型（既非 manifest 目录/.json，也非 .mhtml）: {path}")


# ── manifest 路径：提取原文散文文本（来自 manifest.json）───────────────────────

# 计入"散文基线"的 section 类型（code/table/image 不计入比例分母）
PROSE_TYPES = {"paragraph", "heading", "list_item", "quote"}


def load_source_sections(manifest_path: str) -> list:
    """从 manifest.json（或其所在目录，或兜底的 chapter_*.json）加载原始 sections 列表。"""
    if os.path.isdir(manifest_path):
        manifest_path = os.path.join(manifest_path, "manifest.json")
    if not os.path.isfile(manifest_path):
        d = os.path.dirname(manifest_path)
        chapters = sorted(glob.glob(os.path.join(d, "chapter_*.json")))
        if not chapters:
            raise FileNotFoundError(f"找不到 manifest.json 或 chapter_*.json: {manifest_path}")
        sections = []
        for c in chapters:
            data = json.load(open(c, encoding="utf-8"))
            sections.extend(data.get("sections", []))
        return sections
    data = json.load(open(manifest_path, encoding="utf-8"))
    return data.get("sections", [])


def load_baseline_from_manifest(manifest_path: str):
    """返回 (原文散文文本, sections 列表)。sections 供结构化列表枚举核查使用。"""
    sections = load_source_sections(manifest_path)
    text = "".join(s["text"] for s in sections
                    if s.get("type") in PROSE_TYPES and s.get("text"))
    return text, sections


# ── source 路径：从原始网页文件提取纯文本 ──────────────────────────────────────

def load_slate_text(mhtml_path: str) -> str:
    """从极客时间 .mhtml 提取 Slate.js 原文纯文本（未做结构分类，代码/公式混在其中）。"""
    with open(mhtml_path, "rb") as f:
        msg = email.message_from_bytes(f.read())
    html = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html = part.get_payload(decode=True).decode("utf-8", errors="ignore")
            break
    segs = re.findall(r'<span data-slate-string="true">(.*?)</span>', html, re.DOTALL)
    out = []
    for t in segs:
        t = re.sub(r'<[^>]+>', '', t)
        t = (t.replace('&nbsp;', ' ').replace('&amp;', '&')
              .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'))
        out.append(t)
    return ''.join(out)


def load_baseline_from_source(source_path: str):
    """返回 (原文纯文本, None)。第二个元素占位对齐 load_baseline_from_manifest 的签名。
    detect_source_kind() 保证走到这里的只有 .mhtml（html 走 manifest 分支，见文件头说明）。"""
    return load_slate_text(source_path), None


# ── 笔记加载 ──────────────────────────────────────────────────────────────────

def load_note_text(note_path: str) -> str:
    """读取笔记。支持传单个 .md，或传目录（合并目录下所有 [0-9]*.md，排除 00-索引）。"""
    if os.path.isdir(note_path):
        files = sorted(glob.glob(os.path.join(note_path, "[0-9]*.md")))
        files = [f for f in files if not os.path.basename(f).startswith("00")]
        if not files:
            raise FileNotFoundError(f"目录下无章节 md: {note_path}")
        return "\n".join(open(f, encoding="utf-8").read() for f in files)
    return open(note_path, encoding="utf-8").read()


# ── 把笔记 markdown 剥成"纯散文" ─────────────────────────────────────────────

def strip_to_prose(md: str, strip_code_blocks: bool, strip_latex: bool) -> str:
    """
    去掉所有不属于"作者散文内容"的标记，保留正文文字。
    剥的是 inline style 噪声、语法符号，而不是可见的叙述文字。

    strip_code_blocks / strip_latex 是否剥离取决于原文基线的口径（见文件头说明）：
    manifest 路径原文基线本就不含代码/公式 → 笔记侧也要剥掉，口径才对得上；
    source 路径原文基线是网页全文（含代码/公式）→ 笔记侧保留，只去掉围栏本身。
    """
    text = md
    # 1. frontmatter（文件开头的 --- ... ---）
    text = re.sub(r'^\s*---\n.*?\n---\n', '', text, count=1, flags=re.DOTALL)
    # 2. fenced 代码块
    if strip_code_blocks:
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)  # 连围栏带块内文字整体剥离
        text = text.replace('```', '')
    else:
        text = re.sub(r'```[^\n]*\n', '', text)                 # 只去掉围栏行，保留块内文字
        text = text.replace('```', '')
    # 3. LaTeX 公式：块级 $$...$$ 与行内 $...$
    if strip_latex:
        text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
        text = re.sub(r'\$[^$\n]+\$', '', text)
    # 4. HTML 标签整体去掉（去掉 <div style="...一大串...">，保留其中可见文字）
    text = re.sub(r'<[^>]+>', '', text)
    # 5. callout 标记 [!TYPE] / [!TYPE]- 等
    text = re.sub(r'\[!\w+\][-+]?', '', text)
    # 6. markdown 行内 / 结构标点
    text = text.replace('|', ' ')                                  # 表格竖线
    text = re.sub(r'^[#>\s]+', '', text, flags=re.MULTILINE)       # 行首 # / > / 空白
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)       # 列表符号
    text = re.sub(r'^[-:\s|]+$', '', text, flags=re.MULTILINE)     # 表格分隔行
    text = text.replace('*', '').replace('`', '').replace('>', '')
    return text


def count_chars(s: str) -> int:
    """统计非空白字符数。"""
    return len(re.sub(r'\s+', '', s))


# ── 关键元素抽取 ──────────────────────────────────────────────────────────────

# 长枚举阈值：项数 ≥ 这个值才检查（短枚举噪声大，跳过）
ENUM_MIN_ITEMS = 5
# 长枚举被判"整体丢弃"的缺失比例阈值
ENUM_MISS_RATIO = 0.6


def extract_numbers(src: str):
    """抽取原文中所有阿拉伯数字 token（去重、保序）。"""
    seen, out = set(), []
    for m in re.findall(r'\d+(?:\.\d+)?', src):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def extract_long_enumerations(src: str):
    """
    抽取长顿号枚举：连续 ≥ ENUM_MIN_ITEMS 个由 、 分隔的短项。
    返回 [(原始片段, [item, ...]), ...]
    """
    results = []
    for m in re.finditer(r'[^，。；！？、\n]+(?:、[^，。；！？、\n]+)+', src):
        seg = m.group(0)
        items = [x.strip().rstrip('…. ') for x in seg.split('、')]
        items = [x for x in items if 0 < len(x) <= 12]
        if len(items) >= ENUM_MIN_ITEMS:
            results.append((seg, items))
    return results


def extract_list_enumerations(sections: list):
    """
    抽取"结构化列表枚举"：manifest sections 里连续 ≥ ENUM_MIN_ITEMS 条 list_item 的分组
    （例如讲义型 PDF 里"标签墙/工具清单"式的逐行罗列，被 extract_docx.py 识别为 list_item，
    而不是靠 、 分隔的散文——extract_long_enumerations 的正则抓不到这种按行罗列的枚举）。
    仅 manifest 路径可用（source 路径没有结构化 sections）。
    返回 [(分组预览文本, [item, ...]), ...]，与 extract_long_enumerations 的返回结构一致。
    """
    if not sections:
        return []
    results = []
    i, n = 0, len(sections)
    while i < n:
        if sections[i].get("type") == "list_item":
            j = i
            while j < n and sections[j].get("type") == "list_item":
                j += 1
            items = [sections[k].get("text", "").strip() for k in range(i, j)]
            items = [x for x in items if x]
            if len(items) >= ENUM_MIN_ITEMS:
                preview = "、".join(items[:5]) + ("…" if len(items) > 5 else "")
                results.append((preview, items))
            i = j
        else:
            i += 1
    return results


def present(token: str, note: str) -> bool:
    return token in note


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="笔记内容完整性机械核查 (notes-from-docs)")
    ap.add_argument("source",
                     help="原文基线来源：manifest.json 绝对路径 / 提取目录 /tmp/doc_notes_xxx/ "
                          "（docx/pdf 路径），或原始 .mhtml 绝对路径（mhtml 路径）")
    ap.add_argument("note", help="生成的笔记 .md 绝对路径，或笔记目录（合并所有章节 md）")
    ap.add_argument("--type", choices=["technical", "conceptual"], default="conceptual",
                    help="文档类型：technical=代码/架构密集(阈值60%%)；"
                         "conceptual=散文/概念/历史(阈值80%%，默认)")
    args = ap.parse_args()

    try:
        kind = detect_source_kind(args.source)
        if kind == "manifest":
            src, src_sections = load_baseline_from_manifest(args.source)
        else:
            src, src_sections = load_baseline_from_source(args.source)
    except Exception as e:
        print(f"ERROR: 读取原文失败: {e}", file=sys.stderr)
        return 1
    try:
        note_raw = load_note_text(args.note)
    except Exception as e:
        print(f"ERROR: 读取笔记失败: {e}", file=sys.stderr)
        return 1

    # manifest 路径原文基线不含代码/公式 → 笔记侧同步剥离；source 路径原文基线是网页
    # 全文（含代码/公式）→ 笔记侧保留，口径才对得上。
    strip_code_and_latex = (kind == "manifest")
    note_prose = strip_to_prose(note_raw, strip_code_blocks=strip_code_and_latex,
                                 strip_latex=strip_code_and_latex)

    src_chars = count_chars(src)
    prose_chars = count_chars(note_prose)
    threshold = 0.60 if args.type == "technical" else 0.80
    ratio = (prose_chars / src_chars) if src_chars else 0.0
    ratio_pass = ratio >= threshold

    print("=== 内容完整性核查 ===")
    print(f"输入类型: {kind}  文档类型(--type): {args.type}  阈值: {int(threshold*100)}%")
    print(f"SOURCE_CHARS(原文{'散文' if kind == 'manifest' else '纯文本'}): {src_chars}")
    print(f"NOTE_PROSE_CHARS(笔记剥标记后): {prose_chars}")
    print(f"RATIO: {ratio*100:.1f}%  → {'PASS' if ratio_pass else 'FAIL ⚠️ 散文被过度压缩'}")

    # 关键数字
    nums = extract_numbers(src)
    missing_nums = [n for n in nums if not present(n, note_raw)]
    print("\n=== 关键数字核查 ===")
    if not nums:
        print("(原文无数字)")
    elif not missing_nums:
        print(f"全部 {len(nums)} 个数字均在笔记中出现。")
    else:
        print(f"原文 {len(nums)} 个数字，以下 {len(missing_nums)} 个在笔记中缺失（确认是否漏掉统计/引用）:")
        for n in missing_nums:
            print(f"  [MISSING] {n}")

    # 长顿号枚举
    enums = extract_long_enumerations(src)
    print(f"\n=== 长顿号枚举核查（≥{ENUM_MIN_ITEMS} 项并列，缺失 ≥{int(ENUM_MISS_RATIO*100)}% 即告警）===")
    enum_flagged = 0
    if not enums:
        print(f"(原文无 ≥{ENUM_MIN_ITEMS} 项的长枚举)")
    else:
        for seg, items in enums:
            miss = [it for it in items if not present(it, note_raw)]
            if len(miss) >= ENUM_MISS_RATIO * len(items):
                enum_flagged += 1
                preview = seg if len(seg) <= 50 else seg[:50] + '…'
                print(f"[FLAG] 整条长枚举疑似被整体丢弃（{len(miss)}/{len(items)} 项缺失）:")
                print(f"       {preview}")
                print(f"       缺失项: {'、'.join(miss[:8])}{' …' if len(miss) > 8 else ''}")
        if enum_flagged == 0:
            print(f"原文 {len(enums)} 条长枚举均已基本保留。")

    # 结构化列表枚举（仅 manifest 路径；讲义型 PDF 的标签墙/要点罗列常以此形式出现）
    list_enum_flagged = 0
    if kind == "manifest":
        list_enums = extract_list_enumerations(src_sections)
        print(f"\n=== 结构化列表枚举核查（≥{ENUM_MIN_ITEMS} 条连续 list_item，缺失 ≥{int(ENUM_MISS_RATIO*100)}% 即告警）===")
        if not list_enums:
            print(f"(原文无 ≥{ENUM_MIN_ITEMS} 条的连续列表分组)")
        else:
            for preview, items in list_enums:
                miss = [it for it in items if not present(it, note_raw)]
                if len(miss) >= ENUM_MISS_RATIO * len(items):
                    list_enum_flagged += 1
                    print(f"[FLAG] 整组列表枚举疑似被整体丢弃（{len(miss)}/{len(items)} 项缺失）:")
                    print(f"       {preview}")
                    print(f"       缺失项: {'、'.join(miss[:8])}{' …' if len(miss) > 8 else ''}")
            if list_enum_flagged == 0:
                print(f"原文 {len(list_enums)} 组连续列表均已基本保留。")

    # 结论
    print("\n=== 结论 ===")
    flags = []
    if not ratio_pass:
        flags.append(f"散文比例 {ratio*100:.1f}% < {int(threshold*100)}%")
    if missing_nums:
        flags.append(f"{len(missing_nums)} 个数字缺失")
    if enum_flagged:
        flags.append(f"{enum_flagged} 条长枚举被丢弃")
    if list_enum_flagged:
        flags.append(f"{list_enum_flagged} 组结构化列表枚举被丢弃")
    if flags:
        print("⚠️ 需人工复核: " + "；".join(flags))
        print("（注：脚本只抓离散 token 丢失，'提到但未展开'仍需对照内容守恒规则人工判断）")
    else:
        print("✅ 机械核查未发现明显内容丢失（仍建议抽查一处枚举/要素的展开质量）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
