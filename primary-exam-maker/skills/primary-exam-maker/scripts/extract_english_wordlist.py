#!/usr/bin/env python3
"""从译林版英语电子教材 PDF 的文字层提取 Word lists（按单元的生词/短语/句型）。

用法:
    python3 -I extract_english_wordlist.py <pdf> <out.json>

只输出 英文 / 中文释义 / 首次出现页码 / 是否带 * （非单元核心词），不含教材正文。
Word lists 页首标题含 "Word lists"，自动定位；条目格式为
    [*]English␣␣␣中文\n(页码)
中文过长时折行（缩进续行）。
单元词表之后的「按字母顺序」总索引与专有名词表不提取。
教材未印出总数，故无法像语文字表那样对总数；改用以下检查并在末尾打印告警：
  - 单元内页码单调不减
  - 单元编号连续
  - 英文、中文均非空
"""
import re
import sys
import json

import fitz

PAGE_ONLY = re.compile(r"^\((\d{1,3})\)\s*$")
PAGE_TAIL = re.compile(r"^(.*?)\s*\((\d{1,3})\)\s*$")
UNIT = re.compile(r"^Unit\s+(\d+)\s*$")
ENTRY = re.compile(r"^(\*?)\s*(\S.*?)\s{2,}(.*)$")
CJK = re.compile(r"[㐀-鿿]")


def wordlist_lines(pdf):
    doc = fitz.open(pdf)
    start = None
    for i, p in enumerate(doc):
        if start is None and "Word lists" in p.get_text()[:80]:
            start = i
    if start is None:
        sys.exit("未找到 Word lists 页")
    lines = []
    for i in range(start, len(doc)):
        txt = doc[i].get_text()
        done = "说明：本表按字母顺序" in txt     # 其后是按字母排序的总索引，丢弃
        if done:
            txt = txt.split("说明：本表按字母顺序")[0]
        for ln in txt.replace("\x08", "").split("\n"):
            lines.append(ln.rstrip())
        if done:
            break
    return lines


def parse(lines):
    units, unit, cur = [], None, None

    def finish(page):
        nonlocal cur
        if cur is None:
            return
        cur["zh"] = re.sub(r"\s+", "", cur["zh"])
        cur["page"] = page
        unit["words"].append(cur)
        cur = None

    for raw in lines:
        s = raw.strip()
        if (not s or s in ("Word lists", "I I", "核心词。") or s.startswith("说明：")
                or re.fullmatch(r"\d{1,3}|I+", s)):
            continue
        m = UNIT.match(s)
        if m:
            no = int(m.group(1))
            if unit is None or unit["unit"] != no:   # 标题被重复印刷，仅首次生效
                unit = {"unit": no, "words": []}
                units.append(unit)
            continue
        if unit is None:
            continue
        m = PAGE_ONLY.match(s)
        if m:
            finish(int(m.group(1)))
            continue
        # 折行续行：英文行尾换行后，中文单独成行（缩进可能是不同空白字符）；
        # 当前条目还没有中文时，把非新条目的行都当作中文续行。
        if cur is not None and (raw.startswith("      ") or cur["zh"] == ""):
            m2 = PAGE_TAIL.match(s)
            if m2:
                cur["zh"] += m2.group(1)
                finish(int(m2.group(2)))
                continue
            if not ENTRY.match(raw):
                cur["zh"] += s
                continue
        m = ENTRY.match(raw.strip("\n"))
        if m and not CJK.search(m.group(2)):
            star, en, zh = m.group(1), m.group(2).strip(), m.group(3)
            if not star and raw.lstrip().startswith("*"):
                star = "*"
            cur = {"en": en, "zh": "", "core": star != "*"}
            m2 = PAGE_TAIL.match(zh)
            if m2:
                cur["zh"] = m2.group(1)
                finish(int(m2.group(2)))
            else:
                cur["zh"] = zh
    return units


def check(units):
    warn = []
    nos = [u["unit"] for u in units]
    if nos != list(range(1, len(nos) + 1)):
        warn.append(f"单元编号不连续: {nos}")
    for u in units:
        last = 0
        for w in u["words"]:
            if not w["en"] or not w["zh"]:
                warn.append(f"U{u['unit']} 空字段: {w}")
            if w["page"] < last:
                warn.append(f"U{u['unit']} 页码回退: {w['en']} p{w['page']} < {last}")
            last = max(last, w["page"])
    return warn


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    pdf, out = sys.argv[1:]
    units = parse(wordlist_lines(pdf))
    json.dump({"source_pdf": pdf.split("/")[-1], "units": units},
              open(out, "w"), ensure_ascii=False, indent=1)
    for u in units:
        core = sum(w["core"] for w in u["words"])
        print(f"Unit {u['unit']}: {len(u['words'])} entries ({core} core)")
    for w in check(units):
        print("WARN", w)


if __name__ == "__main__":
    main()
