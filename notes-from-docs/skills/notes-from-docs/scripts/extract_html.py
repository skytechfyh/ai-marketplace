#!/usr/bin/env python3
"""
Extract text structure, code blocks, lists, tables and images from a generic, already-
rendered .html/.htm article (local file) for the notes-from-docs skill. Produces the SAME
`sections` / manifest.json schema as extract_docx.py, so every downstream step in
reference/extract-docx-pdf.md (A1-A7: doc-type judgment, OSS upload, OCR+vision analysis,
version re-baseline, chunked write, verify_content.py/check_mermaid.py/check_links.py) is
reused unmodified — this script only replaces the A0 extraction step.

Usage:
    python3 extract_html.py <html_path> [--output-dir <dir>] [--max-img-px 2000] [--no-split]

Handles two shapes of input:
  * A bare content fragment (no <html>/<head>/<body> — the file starts directly with
    <p>/<h2>/...), typical of "article body only" exports from course/CMS platforms.
  * A full page (<html><body>...</body></html>) — <script>/<style>/<nav>/<header>/<footer>/
    <aside>/<iframe> and everything inside them are stripped before the rest is walked;
    other wrapper tags (<div>/<section>/<article>/<body>/<html>) are treated as transparent
    containers.

Key behaviours:
  * TITLE — body <h1> is unreliable on this kind of export (often missing, or polluted with
    editorial markers like "【定稿】" / "✅" / " 副本"), so <h1> is NEVER promoted to a
    heading section. The document title always falls back to the filename via
    extract_docx.py's _finalize() (same fallback it uses for docx/pdf with no H1) — this
    matches extract_batch.py's own default `--title-from filename` for exactly the same
    "cover text is unreliable, the filename carries the real title" reason.
  * HEADINGS — h2→level2, h3→level3, h4/h5/h6→level4 (same H1-H4 cap as extract_docx.py).
  * CODE — <pre><code class="language-X"> maps X (lower-cased) through extract_docx.py's
    LANG_LABEL_MAP; an absent/unmapped label falls back to "text". Whitespace/newlines
    inside <code> are preserved exactly (not reflowed).
  * LINKS — inline <a href> is rewritten to [text](href) Markdown, inside paragraphs, list
    items, table cells and quotes alike.
  * IMAGES — <img src> is fetched into images/ (http/https downloaded, data: URIs decoded,
    bare local paths resolved relative to the html file) and then goes through the exact
    same save_image()/resize_image() pipeline as docx/pdf images, so downstream OSS upload
    and OCR/vision analysis don't need to know an image originated remotely. A failed fetch
    is a [WARN], not a fatal error — extraction continues.

Known limitation: an <img> nested inside a table cell / <blockquote> / heading (rather than
directly inside a <p>, a <li>, or at the top level — all three of which ARE handled) is
currently dropped from that inline flow. None of the sample course exports do this, but a
future source might. If you hit this, promote the image out of the inline flattener into its
own section the same way the <p>/<li> walkers already do.

Requires: nothing beyond the stdlib (urllib for image download); reuses helpers from
extract_docx.py (save_image, is_small_inline, LANG_LABEL_MAP, _finalize).
"""

import sys
import os
import re
import argparse
import base64
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_docx import (  # noqa: E402
    save_image, is_small_inline, LANG_LABEL_MAP, _finalize,
    MIN_CHAPTER_SECTIONS, DEFAULT_MAX_IMG_PX,
)

STRIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"}
VOID_TAGS = {"img", "br", "hr", "meta", "link", "input", "source", "col", "area", "base"}
HEADING_LEVEL = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 4, "h6": 4}
NOISY_H1_RE = re.compile(r"【定稿】|副本|^\s*✅")


# ---------------------------------------------------------------------------
# Minimal DOM tree builder
# ---------------------------------------------------------------------------

class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []  # list[_Node | str]


class _TreeBuilder(HTMLParser):
    """Builds a lightweight nested tree (ignores STRIP_TAGS subtrees entirely) rather than a
    full DOM — good enough for the semantic-article HTML this script targets, and much
    simpler than tracking a stack of state machines for nested lists/tables/quotes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self._stack = [self.root]
        self._strip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in STRIP_TAGS:
            self._strip_depth += 1
            return
        if self._strip_depth:
            return
        node = _Node(tag, attrs)
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        # self-closing form, e.g. <img .../> or <br/>
        tag = tag.lower()
        if self._strip_depth or tag in STRIP_TAGS:
            return
        self._stack[-1].children.append(_Node(tag, attrs))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in STRIP_TAGS:
            self._strip_depth = max(0, self._strip_depth - 1)
            return
        if self._strip_depth or tag in VOID_TAGS:
            return
        # Pop until the matching open tag (defensive against malformed/unclosed HTML).
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if self._strip_depth:
            return
        self._stack[-1].children.append(data)


def parse_tree(html_text: str) -> _Node:
    tb = _TreeBuilder()
    tb.feed(html_text)
    tb.close()
    return tb.root


# ---------------------------------------------------------------------------
# Inline text flattening (paragraphs, list items, table cells, quotes, headings)
# ---------------------------------------------------------------------------

def _inline_text(node) -> str:
    """Flatten a node's children into Markdown inline text. Images inside this flow are
    dropped (see module docstring's Known limitation) — callers that need images extracted
    from a <p> use _walk_paragraph instead."""
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            continue
        tag = child.tag
        if tag == "br":
            parts.append("<br/>")
        elif tag == "img":
            continue
        elif tag == "a":
            href = child.attrs.get("href", "").strip()
            text = _inline_text(child).strip()
            if href and text:
                parts.append(f"[{text}]({href})")
            else:
                parts.append(text)
        elif tag in ("strong", "b"):
            text = _inline_text(child).strip()
            parts.append(f"**{text}**" if text else "")
        elif tag in ("em", "i"):
            text = _inline_text(child).strip()
            parts.append(f"*{text}*" if text else "")
        elif tag == "span" and "orange" in child.attrs.get("class", ""):
            text = _inline_text(child).strip()
            parts.append(f"**{text}**" if text else "")
        else:
            parts.append(_inline_text(child))
    return "".join(parts)


def _collapse_ws(text: str) -> str:
    return re.sub(r"[ \t　]+", " ", text).strip()


# ---------------------------------------------------------------------------
# Image fetching (remote URL / data: URI / local path -> images/)
# ---------------------------------------------------------------------------

def _guess_ext(url: str, content_type: str = "") -> str:
    path = urlparse(url).path
    ext = Path(path).suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        return ext
    ct_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
              "image/webp": ".webp", "image/bmp": ".bmp"}
    return ct_map.get(content_type.split(";")[0].strip().lower(), ".png")


def _fetch_image_bytes(src: str, html_dir: Path):
    """Returns (blob, ext) or (None, None) on failure. Never raises."""
    if src.startswith("data:"):
        try:
            header, b64data = src.split(",", 1)
            ext = _guess_ext("", header[5:])
            return base64.b64decode(b64data), ext
        except Exception as e:
            print(f"  [WARN] bad data: URI: {e}", file=sys.stderr)
            return None, None
    if src.startswith(("http://", "https://")):
        try:
            req = Request(src, headers={"User-Agent": "Mozilla/5.0 (notes-from-docs)"})
            with urlopen(req, timeout=20) as resp:
                blob = resp.read()
                ext = _guess_ext(src, resp.headers.get("Content-Type", ""))
                return blob, ext
        except Exception as e:
            print(f"  [WARN] failed to download image {src}: {e}", file=sys.stderr)
            return None, None
    # bare local path, relative to the source html file
    local = (html_dir / src).resolve()
    if local.exists():
        try:
            return local.read_bytes(), local.suffix.lower() or ".png"
        except Exception as e:
            print(f"  [WARN] failed to read local image {local}: {e}", file=sys.stderr)
    else:
        print(f"  [WARN] image not found: {src}", file=sys.stderr)
    return None, None


# ---------------------------------------------------------------------------
# Table -> markdown
# ---------------------------------------------------------------------------

ALIGN_RE = re.compile(r"text-align\s*:\s*(left|center|right)", re.I)


def _cell_align(cell_node) -> str:
    m = ALIGN_RE.search(cell_node.attrs.get("style", ""))
    if not m:
        return "---"
    a = m.group(1).lower()
    return {"left": "---", "center": ":---:", "right": "---:"}[a]


def _table_to_markdown(table_node):
    """Returns (markdown, n_rows, n_cols) from a <table> node's <tr>/<th>/<td> structure."""
    rows = []       # list[list[str]]
    aligns = None
    for section in table_node.children:
        if not (hasattr(section, "tag") and section.tag in ("thead", "tbody", "tfoot", "tr")):
            continue
        trs = [section] if section.tag == "tr" else \
            [c for c in section.children if hasattr(c, "tag") and c.tag == "tr"]
        for tr in trs:
            cells = [c for c in tr.children if hasattr(c, "tag") and c.tag in ("th", "td")]
            if not cells:
                continue
            row = [_collapse_ws(_inline_text(c)).replace("\n", "<br/>") for c in cells]
            rows.append(row)
            if aligns is None and any(c.tag == "th" for c in cells):
                aligns = [_cell_align(c) for c in cells]
    if not rows:
        return "", 0, 0
    n_cols = max(len(r) for r in rows)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    if aligns is None or len(aligns) != n_cols:
        aligns = ["---"] * n_cols
    md = ["| " + " | ".join(rows[0]) + " |",
          "| " + " | ".join(aligns) + " |"]
    for row in rows[1:]:
        md.append("| " + " | ".join(row) + " |")
    return "\n".join(md), len(rows), n_cols


# ---------------------------------------------------------------------------
# Block-level walk -> sections
# ---------------------------------------------------------------------------

def _walk_paragraph(p_node, emit_image):
    """Walk a <p>'s direct children, splitting on embedded <img>s so "text + trailing image"
    and "image-only" paragraphs both work. Returns a list of section dicts (paragraph/image)."""
    out = []
    buf_children = []

    def flush():
        if not buf_children:
            return
        fake = _Node("p", {})
        fake.children = buf_children[:]
        text = _collapse_ws(_inline_text(fake))
        if text:
            out.append({"type": "paragraph", "text": text})
        buf_children.clear()

    for child in p_node.children:
        if not isinstance(child, str) and child.tag == "img":
            flush()
            emit_image(child, out)
        else:
            buf_children.append(child)
    flush()
    return out


def _walk_list(list_node, level, emit_image):
    """Walk a <ul>/<ol>, yielding list_item sections (and any images found inline).

    Editors commonly wrap each <li>'s content in a <p> (`<li><p>text<img/></p></li>`) rather
    than putting text/img directly under <li> — <p> is treated as a transparent wrapper here
    so an <img> nested inside it still breaks the surrounding text into "before"/"after"
    list_item chunks instead of being silently dropped by _inline_text's image skip.
    """
    ordered = list_node.tag == "ol"
    out = []
    for li in list_node.children:
        if not (hasattr(li, "tag") and li.tag == "li"):
            continue
        nested_lists = []
        content_children = []
        for c in li.children:
            if hasattr(c, "tag") and c.tag in ("ul", "ol"):
                nested_lists.append(c)
            else:
                content_children.append(c)

        buf = []

        def flush():
            if not buf:
                return
            fake = _Node("li", {})
            fake.children = buf[:]
            text = _collapse_ws(_inline_text(fake))
            if text:
                out.append({"type": "list_item", "ordered": ordered, "level": level, "text": text})
            buf.clear()

        def handle(children):
            for c in children:
                if isinstance(c, str):
                    buf.append(c)
                elif c.tag == "img":
                    flush()
                    emit_image(c, out)
                elif c.tag == "p":
                    handle(c.children)  # transparent <li><p>...</p></li> wrapper
                else:
                    buf.append(c)

        handle(content_children)
        flush()

        for nested in nested_lists:
            out.extend(_walk_list(nested, level + 1, emit_image))
    return out


def _walk_blockquote(bq_node) -> str:
    parts = []
    for c in bq_node.children:
        if hasattr(c, "tag") and c.tag == "p":
            t = _collapse_ws(_inline_text(c))
            if t:
                parts.append(t)
        elif isinstance(c, str):
            t = _collapse_ws(c)
            if t:
                parts.append(t)
    return "<br/>".join(parts) if parts else _collapse_ws(_inline_text(bq_node))


def _code_lang_from_class(code_node) -> str:
    cls = code_node.attrs.get("class", "")
    m = re.search(r"language-([\w+/#-]+)", cls)
    label = (m.group(1) if m else "").strip().lower()
    return LANG_LABEL_MAP.get(label, "text")


def _pre_code_text(pre_node) -> str:
    """Raw text inside <pre><code>...</code></pre>, whitespace preserved as-is."""
    code = next((c for c in pre_node.children if hasattr(c, "tag") and c.tag == "code"), pre_node)

    def raw(node):
        buf = []
        for c in node.children:
            buf.append(c if isinstance(c, str) else raw(c))
        return "".join(buf)
    return raw(code).strip("\n")


def build_sections(root: _Node, html_dir: Path, img_dir: Path, max_px: int):
    sections = []
    img_counter = [0]

    def emit_image(img_node, out_list):
        src = (img_node.attrs.get("src") or "").strip()
        if not src:
            return
        blob, ext = _fetch_image_bytes(src, html_dir)
        if blob is None:
            return
        fname, w, h = save_image(blob, ext, img_dir, img_counter, max_px)
        out_list.append({"type": "image", "image_file": fname,
                          "caption": (img_node.attrs.get("alt") or "").strip(),
                          "width": w, "height": h, "small_inline": is_small_inline(w, h)})

    def walk_block(node):
        for child in node.children:
            if isinstance(child, str):
                text = _collapse_ws(child)
                if text:
                    sections.append({"type": "paragraph", "text": text})
                continue
            tag = child.tag
            if tag in HEADING_LEVEL:
                if tag == "h1":
                    # Never promoted to a title/heading section — see module docstring.
                    continue
                text = _collapse_ws(_inline_text(child))
                if text:
                    sections.append({"type": "heading", "level": HEADING_LEVEL[tag], "text": text})
            elif tag == "p":
                sections.extend(_walk_paragraph(child, emit_image))
            elif tag in ("ul", "ol"):
                sections.extend(_walk_list(child, 0, emit_image))
            elif tag == "table":
                md, n_rows, n_cols = _table_to_markdown(child)
                if md:
                    sections.append({"type": "table", "rows": n_rows, "cols": n_cols, "markdown": md})
            elif tag == "pre":
                code = next((c for c in child.children if hasattr(c, "tag") and c.tag == "code"), None)
                lang = _code_lang_from_class(code) if code else "text"
                text = _pre_code_text(child)
                if text.strip():
                    sections.append({"type": "code", "lang": lang, "text": text})
            elif tag == "blockquote":
                text = _walk_blockquote(child)
                if text:
                    sections.append({"type": "quote", "text": text})
            elif tag == "img":
                emit_image(child, sections)
            elif tag in ("hr",):
                continue
            elif tag in ("div", "section", "article", "body", "html", "main", "figure", "figcaption"):
                walk_block(child)  # transparent container
            else:
                # Unknown inline/unhandled tag at block level — recurse so its content
                # (and any nested headings/paragraphs/images) is still not silently lost.
                walk_block(child)

    walk_block(root)
    return sections, img_counter[0]


# ---------------------------------------------------------------------------
# Entry point (mirrors extract_docx()/extract_pdf() signature)
# ---------------------------------------------------------------------------

def extract_html(html_path: str, output_dir: str, max_px: int, split_level="auto",
                 min_size=MIN_CHAPTER_SECTIONS, finalize: bool = True):
    html_text = Path(html_path).read_text(encoding="utf-8", errors="replace")
    root = parse_tree(html_text)

    img_dir = Path(output_dir) / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    sections, n_images = build_sections(root, Path(html_path).resolve().parent, img_dir, max_px)

    if not finalize:
        return sections
    return _finalize(sections, html_path, img_dir, n_images, output_dir, split_level, min_size)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract .html/.htm for notes-from-docs")
    parser.add_argument("html_path", help="Absolute path to .html / .htm")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-img-px", type=int, default=DEFAULT_MAX_IMG_PX,
                        help="Resize images larger than this on any side (default 2000)")
    parser.add_argument("--split-level", default="auto",
                        help="Heading level to split chapter files at: auto|2|3 (default auto)")
    parser.add_argument("--no-split", action="store_true",
                        help="Output all content in a single chapter_01.json; "
                             "no chapter splitting. After writing the MD check its size — "
                             "if > 5 MB, split manually by H2 headings.")
    parser.add_argument("--min-sections", type=int, default=MIN_CHAPTER_SECTIONS,
                        help=f"Merge small same-parent chapters below this size "
                             f"(default {MIN_CHAPTER_SECTIONS}; 0 disables merging)")
    args = parser.parse_args()

    html_path = args.html_path
    if not os.path.exists(html_path):
        sys.exit(f"[ERROR] File not found: {html_path}")

    ext = Path(html_path).suffix.lower()
    if ext not in (".html", ".htm"):
        sys.exit(f"[ERROR] Unsupported type: {ext}. Use .html / .htm")

    if args.output_dir:
        output_dir = args.output_dir
    else:
        safe = re.sub(r"[^\w一-鿿.-]", "_", Path(html_path).stem)
        output_dir = f"/tmp/doc_notes_{safe}"
    os.makedirs(output_dir, exist_ok=True)

    if args.no_split:
        split = 0
    else:
        split = args.split_level
        if split not in ("auto",):
            try:
                split = int(split)
            except ValueError:
                sys.exit("[ERROR] --split-level must be auto, 2, or 3")

    extract_html(html_path, output_dir, args.max_img_px, split, args.min_sections)
