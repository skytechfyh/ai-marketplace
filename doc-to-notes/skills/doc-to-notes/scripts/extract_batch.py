#!/usr/bin/env python3
"""
Batch-merge multiple .docx / .doc / .pdf source documents into ONE combined
manifest.json + chapter_NN.json — for doc-to-notes cases where several files logically
form a single note (e.g. a training-camp week made of several per-lecture PDFs) and should
become one merged Markdown note instead of one note per file.

Usage:
    # Directory mode: glob-match files in a folder, auto-ordered by the first number found
    # in each filename (so "第2节" sorts before "第10节", unlike plain string sort).
    python3 extract_batch.py "<dir>" [--pattern "*.pdf"] --title "Week1 导论" \\
        [--output-dir /tmp/doc_notes_xxx] [--no-split] [--max-img-px 2000] [--min-sections 15]

    # Explicit file list mode: files are merged in the EXACT order given (no re-sorting).
    python3 extract_batch.py file1.pdf file2.pdf file3.docx --title "..."

Design (reuses extract_docx.py, does not modify single-file behaviour):
    Each source file is extracted in its own scratch sub-directory via the existing
    extract_docx()/extract_pdf() functions with finalize=False, so they return a raw
    `sections` list instead of writing manifest/chapter files. This script then:
      1. Renumbers and moves that file's images into the batch's shared images/ dir (so
         numbering stays continuous and no two files' images collide).
      2. Prepends a synthetic H2 heading using the file's own detected title (or its
         filename), and demotes all of that file's own heading levels by one so the file's
         internal H2/H3/... become H3/H4/... beneath the synthetic H2 — replicating the
         convention that one file == one H2 chapter, same as extract_docx.py's own
         --split-level auto default.
      3. Concatenates every file's sections in order and calls the SAME `_finalize()` used
         by single-file extraction.
    The resulting manifest.json / chapter_NN.json is therefore INDISTINGUISHABLE in shape
    from single-file output — Step 1 onward of the doc-to-notes workflow needs no changes
    to consume a batch-merged doc.
"""

import argparse
import glob
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_docx import (  # noqa: E402
    extract_docx, extract_pdf, convert_doc_to_docx, _finalize,
    MIN_CHAPTER_SECTIONS, DEFAULT_MAX_IMG_PX,
)

SUPPORTED_EXTS = (".pdf", ".docx", ".doc")


def _natural_key(path: str):
    """Sort key: first integer found in the filename stem, ascending; no digit sorts last.

    Plain string sort would put "第10节" before "第2节" — this avoids that trap for the
    common "第N节" / "第N讲" naming convention.
    """
    stem = Path(path).stem
    m = re.search(r"\d+", stem)
    return (0, int(m.group())) if m else (1, stem)


def _collect_directory(dir_path: str, pattern: str) -> list:
    patterns = [pattern] if pattern else [f"*{ext}" for ext in SUPPORTED_EXTS]
    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(dir_path, pat)))
    files = [f for f in files if Path(f).suffix.lower() in SUPPORTED_EXTS]
    files = [f for f in files if "(1)." not in Path(f).name]  # skip duplicate downloads
    files = sorted(set(files), key=_natural_key)
    return files


def _pick_chapter_title(path: str, sections: list, title_from: str) -> str:
    """Choose the H2 chapter title for one source file.

    For slide decks the in-document H1 is usually the cover *slogan* ("工具太多不可怕，
    没有地图才可怕。"), while the real chapter name lives in the FILENAME
    ("第4节：选型力：看懂 AI 编程工具的七层架构"). So `filename` is the default; `heading`
    forces the in-document H1; `auto` uses the filename only when it carries a chapter
    number (第N节/讲/课, or a leading digit), else falls back to the H1.
    """
    stem = Path(path).stem
    doc_h1 = next((s["text"] for s in sections
                   if s.get("type") == "heading" and s.get("level") == 1), None)
    if title_from == "heading":
        return doc_h1 or stem
    if title_from == "filename":
        return stem
    numbered = re.search(r"第\s*\d+\s*[节讲课章]|^\d+[.\-_、\s]", stem)
    return stem if numbered else (doc_h1 or stem)


def _extract_one(path: str, scratch_dir: str, max_px: int, title_from: str) -> tuple:
    """Extract one file (finalize=False) in an isolated scratch dir. Returns (title, sections)."""
    os.makedirs(scratch_dir, exist_ok=True)
    ext = Path(path).suffix.lower()
    if ext == ".doc":
        path = convert_doc_to_docx(path)
        ext = ".docx"
    if ext == ".docx":
        sections = extract_docx(path, scratch_dir, max_px, split_level=0, finalize=False)
    elif ext == ".pdf":
        sections = extract_pdf(path, scratch_dir, max_px, split_level=0, finalize=False)
    else:
        sys.exit(f"[ERROR] Unsupported type in batch: {path}")
    return _pick_chapter_title(path, sections, title_from), sections


def _rehome_images(sections: list, scratch_dir: str, shared_img_dir: Path, counter: list) -> None:
    """Move this file's images out of its scratch dir into the batch's shared images/ dir,
    renumbering filenames so they don't collide with other files' images, and rewrite each
    image section's `image_file` in place."""
    for s in sections:
        if s.get("type") != "image":
            continue
        old_fname = s["image_file"]
        old_path = Path(scratch_dir) / "images" / old_fname
        if not old_path.exists():
            continue  # already reported as a WARN by the extractor; nothing to move
        counter[0] += 1
        new_fname = f"image{counter[0]:03d}{old_path.suffix}"
        shutil.copy2(old_path, shared_img_dir / new_fname)
        s["image_file"] = new_fname


def _demote_and_merge(title: str, sections: list) -> list:
    """Prepend a synthetic H2 chapter heading, then demote every heading of this file to
    H3/H4 so none of them can compete with the synthetic H2 (which must remain the file's
    single chapter boundary — otherwise a leftover H1/H2 would split the file into extra
    chapters). A heading identical to the chosen title is dropped to avoid duplication.
    Non-heading sections pass through unchanged.
    """
    merged = [{"type": "heading", "level": 2, "text": title}]
    dropped_dup = False
    for s in sections:
        if s.get("type") == "heading":
            if not dropped_dup and s.get("text") == title:
                dropped_dup = True
                continue
            s = dict(s)
            # H1/H2 -> H3, H3 -> H4, H4 stays H4 (never above H3, never below H4)
            s["level"] = max(3, min(s.get("level", 2) + 1, 4))
            merged.append(s)
        else:
            merged.append(s)
    return merged


# NOTE: there is deliberately NO cross-file text dedupe. Within one file, extract_pdf()
# already drops header/footer banners repeated on ≥3 pages. Across files, repeated text is
# usually real content (chart labels like "方法论 · SDD", product names, a punchline reused
# between lectures) or a per-file cover banner that is harmless to keep — dropping it would
# violate the skill's content-conservation rule.


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Merge multiple .docx/.doc/.pdf files into one manifest/chapter set")
    ap.add_argument("paths", nargs="+",
                     help="A single directory to glob-scan, or an explicit list of files "
                          "(explicit lists are merged in the exact order given)")
    ap.add_argument("--pattern", default=None,
                     help="Glob pattern for directory mode (default: match .pdf/.docx/.doc)")
    ap.add_argument("--title", default=None,
                     help="Title for the merged document (default: directory name, or the "
                          "first file's stem for an explicit file list)")
    ap.add_argument("--title-from", choices=["filename", "heading", "auto"], default="filename",
                     help="Where each file's H2 chapter title comes from. filename (default) "
                          "— slide decks' in-document H1 is usually a cover slogan, the real "
                          "chapter name is the filename; heading — use the in-document H1; "
                          "auto — filename when it carries a 第N节/讲/课 number, else the H1")
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--max-img-px", type=int, default=DEFAULT_MAX_IMG_PX)
    ap.add_argument("--split-level", default="auto",
                     help="Heading level to split chapter files at: auto|2|3 (default auto)")
    ap.add_argument("--no-split", action="store_true",
                     help="Output all content in a single chapter_01.json")
    ap.add_argument("--min-sections", type=int, default=MIN_CHAPTER_SECTIONS)
    args = ap.parse_args()

    if len(args.paths) == 1 and os.path.isdir(args.paths[0]):
        dir_path = args.paths[0]
        files = _collect_directory(dir_path, args.pattern)
        if not files:
            sys.exit(f"[ERROR] No .pdf/.docx/.doc files found in: {dir_path}")
        default_title = Path(dir_path.rstrip("/")).name
        source_label = dir_path
    else:
        files = args.paths
        for f in files:
            if not os.path.exists(f):
                sys.exit(f"[ERROR] File not found: {f}")
        default_title = Path(files[0]).stem
        source_label = " | ".join(files)

    title = args.title or default_title

    if args.output_dir:
        output_dir = args.output_dir
    else:
        safe = re.sub(r"[^\w一-鿿.-]", "_", title)
        output_dir = f"/tmp/doc_notes_{safe}"
    out = Path(output_dir)
    shared_img_dir = out / "images"
    shared_img_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = out / "_batch_scratch"

    split = 0 if args.no_split else args.split_level
    if split not in ("auto", 0):
        try:
            split = int(split)
        except ValueError:
            sys.exit("[ERROR] --split-level must be auto, 2, or 3")

    img_counter = [0]
    all_sections = [{"type": "heading", "level": 1, "text": title}]
    print(f"合并顺序（共 {len(files)} 个文件）：")
    for i, f in enumerate(files, 1):
        scratch_dir = str(scratch_root / f"f{i:02d}")
        file_title, sections = _extract_one(f, scratch_dir, args.max_img_px, args.title_from)
        _rehome_images(sections, scratch_dir, shared_img_dir, img_counter)
        merged = _demote_and_merge(file_title, sections)
        n_images = sum(1 for s in sections if s.get("type") == "image")
        print(f"  {i:2d}. {Path(f).name}  →  \"{file_title}\"  ({len(sections)} sections, {n_images} images)")
        all_sections.extend(merged)

    shutil.rmtree(scratch_root, ignore_errors=True)

    print()
    _finalize(all_sections, source_label, shared_img_dir, img_counter[0],
              output_dir, split, args.min_sections)
    return 0


if __name__ == "__main__":
    sys.exit(main())
