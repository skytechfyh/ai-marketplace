#!/usr/bin/env python3
"""从统编版语文电子教材 PDF 的文字层提取 识字表 / 写字表 / 词语表。

用法:
    python3 -I extract_chinese_tables.py <pdf> <out.json> [--pages literacy=118,writing=122,words=125]

只输出结构化字词，不含教材正文。PDF 中拼音用自定义字体编码、不可直接读取，
因此不提取拼音（拼音由 pypinyin 生成，多音字以人工校对为准）。
校验：识字表/写字表末尾印有「共N个生字/字」，提取数量必须与之相等。
"""
import re
import sys
import json
import argparse

import fitz

HEAD = {"识字表": "literacy", "写字表": "writing", "词语表": "words"}
CJK = re.compile(r"[㐀-鿿]")
LATIN = re.compile(r"[A-Za-z]")
SKIP = re.compile(r"仅供个人学习使用|^[①②③④⑤⑥⑦⑧⑨⑩]|识字表中|^（共|后\s*记")


BLUE = "\ue000"        # 标记「蓝色字」：此前已认读、作为多音字再学，不计入生字总数
BLACK = (0x231F20, 0)
WS = re.compile(r"[\s\u2002\u2003\u3000]+")


def page_lines(page):
    """逐行取文字；单字且非黑色的字（蓝色字）前加 BLUE 标记。"""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            txt = ""
            for sp in l["spans"]:
                t = sp["text"]
                if len(t.strip()) == 1 and CJK.match(t.strip()) and sp["color"] not in BLACK:
                    t = BLUE + t
                txt += t
            out.append(txt)
    return out


def load_sections(pdf, pages):
    """pages: {kind: 起始页(1起)}；缺省时按页首标题「识字表/写字表/词语表」自动定位。"""
    doc = fitz.open(pdf)
    starts = dict(pages)
    if not starts:
        for i, page in enumerate(doc):
            first = WS.sub("", page.get_text()[:40])
            if first[:3] in HEAD and HEAD[first[:3]] not in starts:
                starts[HEAD[first[:3]]] = i + 1
    order = sorted(starts.items(), key=lambda kv: kv[1])
    secs = {}
    for idx, (kind, st) in enumerate(order):
        end = order[idx + 1][1] - 1 if idx + 1 < len(order) else len(doc)
        ls = []
        for pn in range(st, end + 1):
            ls += page_lines(doc[pn - 1])
        ls = [x for x in ls if WS.sub("", x) not in HEAD]
        for j, x in enumerate(ls):
            if WS.sub("", x) == "后记":
                ls = ls[:j]
                break
        secs[kind] = ls
    return secs


def parse(lines, kind):
    """返回 [{label, section, no, garden, chars|words}]。"""
    out, cur, section = [], None, None
    total = None

    def start(**kw):
        nonlocal cur
        cur = dict(kw, items=[], blue=[])
        out.append(cur)

    for ln in lines:
        s = ln.replace(" ", " ").replace(" ", " ").strip()
        m_tot = re.search(r"共\s*(\d+)\s*个", s)
        if m_tot:
            total = int(m_tot.group(1))
            continue
        if kind == "words":
            s = s.replace(BLUE, "")
        if not s or SKIP.search(s):
            continue
        if s in ("阅读", "识字"):
            section = s
            continue
        m = re.match(r"^(\d{1,3})(?!\d)\s*(.*)$", s)
        if m:
            n = int(m.group(1))
            if n > 60:        # 页码
                continue
            start(section=section, no=n, garden=False)
            s = m.group(2).strip()
            if not s:
                continue
        if s.startswith("语文园地"):
            start(section=cur and cur["section"], no=None, garden=True,
                  after=cur and cur["no"])
            s = s[4:].lstrip("一二三四五六七八").strip()
            if not s:
                continue
        if cur is None:
            continue
        if kind == "words":
            cur["items"] += [w for w in re.split(r"\s+", s) if CJK.search(w)]
        else:
            if not CJK.search(s):
                continue            # 纯拼音行（拼音与汉字同行时，汉字照取）
            blue = False
            for c in s:
                if c == BLUE:
                    blue = True
                elif CJK.match(c):
                    cur["blue" if blue else "items"].append(c)
                    blue = False
    return out, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--pages", default="",
                    help="手动指定起始页，如 literacy=118,writing=122,words=125（标题缺失时用）")
    a = ap.parse_args()
    pages = {k: int(v) for k, v in (x.split("=") for x in a.pages.split(",") if x)}
    secs = load_sections(a.pdf, pages)
    result, report = {}, {}
    for kind, ls in secs.items():
        ents, total = parse(ls, kind)
        ents = [e for e in ents if e["items"] or e["blue"]]
        for e in ents:
            if not e["blue"]:
                del e["blue"]
        n = sum(len(e["items"]) for e in ents)
        report[kind] = (n, total, len(ents))
        result[kind] = ents
    json.dump({"source_pdf": a.pdf.split("/")[-1], "tables": result},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    for k, (n, t, e) in report.items():
        print(f"{k}: {n} items in {e} groups, declared total={t}")


if __name__ == "__main__":
    main()
