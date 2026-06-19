#!/usr/bin/env python3
"""
内容完整性核查 (doc-to-notes 版)：把"正文是否被压缩 / 关键元素是否丢失"从"靠自觉"
变成"机械可验"。移植自 mhtml-refine-to-md，数据源换成 extract_docx.py 的 manifest.json。

用法:
    python3 verify_content.py <manifest.json 或提取目录> <笔记.md 或笔记目录> \
        [--type technical|conceptual]

为什么需要这个脚本:
    单纯的 `wc -c` 文件大小检查是坏的——HTML 卡片的 inline style、Mermaid 代码块、
    LaTeX 公式会贡献海量字符。于是"堆图堆公式"就能轻松冲过大小线，**正文散文掉了一半
    也照样达标**。本脚本剥掉所有标记后只数纯散文字符，再机械核验关键数字/长枚举是否丢失。

数据源:
    manifest.json 中 paragraph / heading / list_item / quote 的 text 作为"原文散文基线"
    （code / table 不计入散文比例分母——它们在笔记里基本原样保留，计入会让基数虚高、
    掩盖叙述被压缩的问题）。

做两件事:
    1. 剥离笔记的 frontmatter / mermaid / HTML / callout / LaTeX 标记，只数**纯散文字符**，
       按文档类型阈值比对原文（technical 60% / conceptual 80%）。
    2. 从原文抽取关键数字 + 长顿号枚举，逐一在笔记中查找，缺失即告警。

局限（必须诚实告知）:
    只抓"整条长枚举被压缩""统计数字被删"这类**离散 token 丢失**，抓不住"提到但没展开"。
    输出是**告警 / FLAG**，供你回原文复核，而非硬性 PASS/FAIL 拍板。
"""

import argparse
import glob
import json
import os
import re
import sys


# ── 提取原文散文文本（来自 manifest.json）────────────────────────────────────

# 计入"散文基线"的 section 类型（code/table/image 不计入比例分母）
PROSE_TYPES = {"paragraph", "heading", "list_item", "quote"}


def load_source_text(manifest_path: str) -> str:
    """从 manifest.json 提取原文散文文本。支持传 manifest.json 或其所在目录。"""
    if os.path.isdir(manifest_path):
        manifest_path = os.path.join(manifest_path, "manifest.json")
    if not os.path.isfile(manifest_path):
        # 兜底：从同目录的 chapter_*.json 合并 sections
        d = os.path.dirname(manifest_path)
        chapters = sorted(glob.glob(os.path.join(d, "chapter_*.json")))
        if not chapters:
            raise FileNotFoundError(f"找不到 manifest.json 或 chapter_*.json: {manifest_path}")
        parts = []
        for c in chapters:
            data = json.load(open(c, encoding="utf-8"))
            for s in data.get("sections", []):
                if s.get("type") in PROSE_TYPES and s.get("text"):
                    parts.append(s["text"])
        return "".join(parts)
    data = json.load(open(manifest_path, encoding="utf-8"))
    parts = []
    for s in data.get("sections", []):
        if s.get("type") in PROSE_TYPES and s.get("text"):
            parts.append(s["text"])
    return "".join(parts)


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

def strip_to_prose(md: str) -> str:
    """
    去掉所有不属于"作者散文内容"的标记，保留正文文字。
    剥的是 inline style 噪声、公式、语法符号，而不是可见的叙述文字。
    """
    text = md
    # 1. frontmatter（文件开头的 --- ... ---）
    text = re.sub(r'^\s*---\n.*?\n---\n', '', text, count=1, flags=re.DOTALL)
    # 2. fenced 代码块整体去掉（代码不是散文，连同 ``` 围栏与块内一并剥离，避免代码文字混入散文计数）
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = text.replace('```', '')
    # 3. LaTeX 公式：块级 $$...$$ 与行内 $...$（公式不是散文）
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


def present(token: str, note: str) -> bool:
    return token in note


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="笔记内容完整性机械核查 (doc-to-notes)")
    ap.add_argument("manifest", help="manifest.json 绝对路径，或提取目录 /tmp/doc_notes_xxx/")
    ap.add_argument("note", help="生成的笔记 .md 绝对路径，或笔记目录（合并所有章节 md）")
    ap.add_argument("--type", choices=["technical", "conceptual"], default="conceptual",
                    help="文档类型：technical=代码/架构密集(阈值60%%)；"
                         "conceptual=散文/概念/历史(阈值80%%，默认)")
    args = ap.parse_args()

    try:
        src = load_source_text(args.manifest)
    except Exception as e:
        print(f"ERROR: 读取原文失败: {e}", file=sys.stderr)
        return 1
    try:
        note_raw = load_note_text(args.note)
    except Exception as e:
        print(f"ERROR: 读取笔记失败: {e}", file=sys.stderr)
        return 1

    note_prose = strip_to_prose(note_raw)

    src_chars = count_chars(src)
    prose_chars = count_chars(note_prose)
    threshold = 0.60 if args.type == "technical" else 0.80
    ratio = (prose_chars / src_chars) if src_chars else 0.0
    ratio_pass = ratio >= threshold

    print("=== 内容完整性核查 ===")
    print(f"文档类型(--type): {args.type}  阈值: {int(threshold*100)}%")
    print(f"SOURCE_CHARS(原文散文): {src_chars}")
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

    # 结论
    print("\n=== 结论 ===")
    flags = []
    if not ratio_pass:
        flags.append(f"散文比例 {ratio*100:.1f}% < {int(threshold*100)}%")
    if missing_nums:
        flags.append(f"{len(missing_nums)} 个数字缺失")
    if enum_flagged:
        flags.append(f"{enum_flagged} 条长枚举被丢弃")
    if flags:
        print("⚠️ 需人工复核: " + "；".join(flags))
        print("（注：脚本只抓离散 token 丢失，'提到但未展开'仍需对照内容守恒规则人工判断）")
    else:
        print("✅ 机械核查未发现明显内容丢失（仍建议抽查一处枚举/要素的展开质量）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
