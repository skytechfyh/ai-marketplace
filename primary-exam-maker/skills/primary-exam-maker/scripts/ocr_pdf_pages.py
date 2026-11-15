#!/usr/bin/env python3
"""把扫描版 PDF 的指定页渲染为图片并用 Apple Vision（ocrmac）识别，输出每页文本。

用法:
    python3 -I ocr_pdf_pages.py <pdf> <out_dir> --pages 1-8[,20-30] [--zoom 2.5]

输出 <out_dir>/p<页码>.txt（OCR 文本）和 p<页码>.png。OCR 对扫描件仍可能有错字，
用于定位章节、提取条目后须与图片对照核对，不能当作逐字准确。仅 macOS。
"""
import os
import sys
import argparse

import fitz
from ocrmac import ocrmac


def parse_pages(spec, total):
    pages = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        pages += [p for p in range(lo, hi + 1) if 1 <= p <= total]
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out_dir")
    ap.add_argument("--pages", required=True)
    ap.add_argument("--zoom", type=float, default=2.5)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    doc = fitz.open(a.pdf)
    for pn in parse_pages(a.pages, len(doc)):
        png = os.path.join(a.out_dir, f"p{pn}.png")
        doc[pn - 1].get_pixmap(matrix=fitz.Matrix(a.zoom, a.zoom)).save(png)
        res = ocrmac.OCR(png, language_preference=["zh-Hans", "en-US"]).recognize()
        # res: [(text, confidence, bbox)]；bbox 原点在左下，按 y 从上到下排序
        res.sort(key=lambda r: (-round(r[2][1] + r[2][3], 2), r[2][0]))
        with open(os.path.join(a.out_dir, f"p{pn}.txt"), "w") as f:
            f.write("\n".join(r[0] for r in res))
        print(pn, len(res), "lines")


if __name__ == "__main__":
    main()
