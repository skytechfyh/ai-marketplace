#!/usr/bin/env python3
"""试卷 MD → PDF（Chrome 无头打印）。

MD 里可用 {{指令}}（见 directives.py）。流程：展开指令 → markdown → 套 print.css → Chrome 打印。
用法：python3 render_pdf.py 试卷.md [-o 试卷.pdf] [--html-only]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent))
import directives  # noqa: E402

CSS = Path(__file__).resolve().parent.parent / "assets" / "print.css"

# Chrome/Chromium/Edge 候选路径（macOS 优先，含 Linux 常见路径）
_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_chrome(override: str | None = None) -> str:
    """查找可用的 Chrome/Chromium/Edge；优先 --chrome 参数 > CHROME_PATH 环境变量 > 自动检测。"""
    candidates = []
    if override:
        candidates.append(override)
    env_path = os.environ.get("CHROME_PATH")
    if env_path:
        candidates.append(env_path)
    candidates.extend(_CHROME_CANDIDATES)
    for c in candidates:
        if c and Path(c).exists():
            return c
    return ""


def build_html(md_text: str) -> str:
    body = markdown.markdown(
        directives.expand(md_text), extensions=["tables", "sane_lists", "md_in_html"]
    )
    css = CSS.read_text(encoding="utf-8")
    css = css.replace("__CROSS__", directives.CROSS_URI).replace("__PYLINES__", directives.PINYIN_URI)
    return f"<!doctype html><html lang='zh'><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


def render_md_text_to_pdf(md_text: str, out_pdf: Path, chrome: str | None = None) -> Path:
    """将 Markdown 文本直接渲染为 PDF（不落盘 .md 中间文件）。"""
    html = build_html(md_text)
    chrome_bin = find_chrome(chrome)
    if not chrome_bin:
        raise RuntimeError(
            "找不到 Chrome/Chromium/Edge，请安装或通过 --chrome 参数 / CHROME_PATH 环境变量指定路径"
        )
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "exam.html"
        src.write_text(html, encoding="utf-8")
        r = subprocess.run(
            [
                chrome_bin,
                "--headless=new",
                "--disable-gpu",
                f"--user-data-dir={td}/profile",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out_pdf.resolve()}",
                src.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    if not out_pdf.exists():
        raise RuntimeError(f"Chrome 未生成 PDF：\n{r.stderr[-800:]}")
    return out_pdf


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--html-only", action="store_true", help="只输出 HTML，便于调试版式")
    ap.add_argument("--chrome", help="Chrome/Chromium/Edge 可执行文件路径（默认自动检测，可用 CHROME_PATH 环境变量）")
    a = ap.parse_args()

    md_text = a.md.read_text(encoding="utf-8")
    out = a.out or a.md.with_suffix(".pdf")
    if a.html_only:
        try:
            html = build_html(md_text)
        except ValueError as e:
            sys.exit(f"错误：{a.md.name} {e}")
        out = out.with_suffix(".html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(out)
        return
    try:
        render_md_text_to_pdf(md_text, out, chrome=a.chrome)
    except ValueError as e:
        sys.exit(f"错误：{a.md.name} {e}")
    except RuntimeError as e:
        sys.exit(str(e))
    print(out)


if __name__ == "__main__":
    main()
