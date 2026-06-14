#!/usr/bin/env python3
"""
内容完整性核查：把"散文是否被压缩 / 关键元素是否丢失"从"靠自觉"变成"机械可验"。

用法:
    python3 verify_content.py <mhtml文件绝对路径> <笔记.md绝对路径> [--type technical|conceptual]

为什么需要这个脚本:
    SKILL 原有的"笔记字符数 ≥ SLATE_CHARS × 60%"检查是坏的——它用 `wc -m` 数整篇笔记，
    而 HTML 卡片的 inline style 属性、Mermaid 代码块会贡献海量字符。于是"堆图"就能轻松
    冲过 60% 线，**散文内容掉了一半也照样达标**（实测一篇 4380 字原文的笔记达到 9076 字
    符、十项核查全过，却仍丢了 4 处正文内容）。

本脚本做两件事:
    1. 剥离纯标记（frontmatter / mermaid 块 / HTML 标签 / callout 与 markdown 标点），
       只数**纯散文字符**，再按文档类型用合理阈值比对 SLATE_CHARS：
         - technical（代码/架构密集）：60%（正文之外另有代码截图等内容，阈值放松）
         - conceptual（散文/管理/软技能）：80%（无代码可丢，散文保真度要求更高）
    2. 从原文 Slate 文本抽取两类高信号元素，逐一在笔记中查找，缺失即告警：
         - 关键数字（500 / 12 / 27 …）：丢失往往意味着统计/引用被删
         - 长顿号枚举（≥5 项并列，如"使用电脑、学习语言、设计算法、开发功能、遵循规范"）：
           当 ≥60% 的项在笔记中找不到，判定为"整条长枚举被整体丢弃"

为什么只查"长枚举"而不查短枚举 / 中文数量短语:
    短枚举（3-4 项）首尾项常粘连前导语、且易被同义改写（"管理上级的预期"→"管理预期"），
    逐项字面匹配会大量误报；"四大目的"这类"N个 X"结构是否**展开**，恰恰是字面匹配抓不住的
    （点了名 ≠ 展开）。为保持高精确率，这两类一律交给人工对照 SKILL Step 2 散文规则判断。

局限（必须诚实告知）:
    本脚本抓的是"整条长枚举被压缩""统计数字被删"这类**离散 token 丢失**；抓不住
    "提到了但没展开"。脚本输出的是**告警 / FLAG**，供 agent 复核，而非硬性 PASS/FAIL 拍板。
"""

import argparse
import email
import os
import re
import sys


# ── 提取原文 Slate 纯文本 ────────────────────────────────────────────────────

def load_slate_text(mhtml_path: str) -> str:
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


# ── 把笔记 markdown 剥成"纯散文" ─────────────────────────────────────────────

def strip_to_prose(md: str) -> str:
    """
    去掉所有不属于"作者散文内容"的标记，保留正文文字 + 代码块内文字 + 卡片可见文字。
    关键：剥的是 inline style 噪声和语法符号，而不是可见内容文字。
    """
    text = md
    # 1. frontmatter（文件开头的 --- ... ---）
    text = re.sub(r'^\s*---\n.*?\n---\n', '', text, count=1, flags=re.DOTALL)
    # 2. fenced 代码块的"栅栏行"去掉，但保留块内文字
    #    （代码截图在技术文里是内容，mermaid 文字也是语义，仅去掉 ``` 围栏与语言标注）
    text = re.sub(r'```[^\n]*\n', '', text)
    text = text.replace('```', '')
    # 3. HTML 标签整体去掉（去掉 <div style="...一大串...">，保留其中可见文字）
    text = re.sub(r'<[^>]+>', '', text)
    # 4. callout 标记 [!TYPE] / [!TYPE]- 等
    text = re.sub(r'\[!\w+\][-+]?', '', text)
    # 5. markdown 行内 / 结构标点
    text = text.replace('|', ' ')                                  # 表格竖线
    text = re.sub(r'^[#>\s]+', '', text, flags=re.MULTILINE)       # 行首 # / > / 空白
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)       # 列表符号
    text = re.sub(r'^[-:\s|]+$', '', text, flags=re.MULTILINE)     # 表格分隔行
    text = text.replace('*', '').replace('`', '').replace('>', '')
    return text


def count_chars(s: str) -> int:
    """统计非空白字符数，与 extract_images.py 的 SLATE_CHARS 口径对齐。"""
    return len(re.sub(r'\s+', '', s))


# ── 关键元素抽取 ──────────────────────────────────────────────────────────────

# 长枚举阈值：项数 ≥ 这个值才检查（短枚举噪声大，跳过）
ENUM_MIN_ITEMS = 5
# 长枚举被判"整体丢弃"的缺失比例阈值
ENUM_MISS_RATIO = 0.6


def extract_numbers(slate: str):
    """抽取原文中所有阿拉伯数字 token（去重、保序）。"""
    seen, out = set(), []
    for m in re.findall(r'\d+(?:\.\d+)?', slate):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def extract_long_enumerations(slate: str):
    """
    抽取长顿号枚举：连续 ≥ ENUM_MIN_ITEMS 个由 、 分隔的短项。
    返回 [(原始片段, [item, ...]), ...]
    """
    results = []
    for m in re.finditer(r'[^，。；！？、\n]+(?:、[^，。；！？、\n]+)+', slate):
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
    ap = argparse.ArgumentParser(description="笔记内容完整性机械核查")
    ap.add_argument("mhtml", help=".mhtml 源文件绝对路径")
    ap.add_argument("note", help="生成的笔记 .md 绝对路径")
    ap.add_argument("--type", choices=["technical", "conceptual"], default="conceptual",
                    help="文档类型：technical=代码/架构密集(阈值60%%)；conceptual=散文/管理(阈值80%%，默认)")
    args = ap.parse_args()

    if not os.path.isfile(args.mhtml):
        print(f"ERROR: 源文件不存在: {args.mhtml}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.note):
        print(f"ERROR: 笔记文件不存在: {args.note}", file=sys.stderr)
        return 1

    slate = load_slate_text(args.mhtml)
    note_raw = open(args.note, encoding="utf-8").read()
    note_prose = strip_to_prose(note_raw)

    slate_chars = count_chars(slate)
    prose_chars = count_chars(note_prose)
    threshold = 0.60 if args.type == "technical" else 0.80
    ratio = (prose_chars / slate_chars) if slate_chars else 0.0
    ratio_pass = ratio >= threshold

    print("=== 内容完整性核查 ===")
    print(f"文档类型(--type): {args.type}  阈值: {int(threshold*100)}%")
    print(f"SLATE_CHARS(原文纯文本): {slate_chars}")
    print(f"NOTE_PROSE_CHARS(笔记剥标记后): {prose_chars}")
    print(f"RATIO: {ratio*100:.1f}%  → {'PASS' if ratio_pass else 'FAIL ⚠️ 散文被过度压缩'}")

    # 关键数字
    nums = extract_numbers(slate)
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
    enums = extract_long_enumerations(slate)
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
        print("（注：脚本只抓离散 token 丢失，'提到但未展开'仍需对照 Step 2 散文规则人工判断）")
    else:
        print("✅ 机械核查未发现明显内容丢失（仍建议抽查一处枚举/要素的展开质量）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
