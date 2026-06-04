#!/usr/bin/env python3
"""
OCR code / UI / data screenshots to a TEXT BASELINE for the doc-to-notes skill.

Usage:
    python3 ocr_image.py <image_file>                 # print text for one image
    python3 ocr_image.py <images_dir> --json          # OCR all images → ocr_text.json
    python3 ocr_image.py <images_dir> --json --min-symbols 8   # only code-like images

Why a script + why "baseline": Apple Vision (via ocrmac) is fast and accurate for Chinese
+ English + code, but OCR of dense code can still mangle indentation and symbols ({ } ; →).
So this script produces a TEXT BASELINE that the model then CORRECTS while looking at the
image itself (vision). Two signals (OCR text + vision) beat one — fewer transcription
errors than vision alone, and far cheaper than the model typing out long code from scratch.

It also emits a `code_score` (count of code symbols) per image, which helps the Step-3
classifier decide "code screenshot vs UI screenshot vs diagram".

Engine preference: ocrmac (Apple Vision, no Homebrew) → pytesseract (if tesseract on PATH).
On non-macOS without tesseract, prints a clear install hint.
"""

import sys
import os
import re
import json
import glob
import argparse

_SUPPORTED = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")
_CODE_SYMBOLS = "{};()=<>.:/\"'#"

# Apple Vision language codes (NOT the short ISO forms; ocrmac validates strictly)
_VISION_LANGS = ["zh-Hans", "en-US"]


def _code_score(text: str) -> int:
    return sum(text.count(c) for c in _CODE_SYMBOLS)


def ocr_apple(path: str) -> str | None:
    """OCR via Apple Vision (ocrmac). Returns text or None if engine unavailable."""
    try:
        from ocrmac import ocrmac
    except ImportError:
        return None
    try:
        res = ocrmac.OCR(path, language_preference=_VISION_LANGS).recognize()
        # res items: (text, confidence, bbox). Keep reading order top→bottom.
        return "\n".join(r[0] for r in res)
    except Exception as e:
        print(f"  [WARN] Apple Vision OCR failed on {path}: {e}", file=sys.stderr)
        return None


def ocr_tesseract(path: str) -> str | None:
    """Fallback OCR via pytesseract (needs `tesseract` binary on PATH)."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    try:
        return pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")
    except Exception as e:
        print(f"  [WARN] tesseract OCR failed on {path}: {e}", file=sys.stderr)
        return None


def ocr_one(path: str) -> str:
    """Try Apple Vision, then tesseract. Exit with hint if neither is available."""
    for engine in (ocr_apple, ocr_tesseract):
        text = engine(path)
        if text is not None:
            return text
    sys.exit("[ERROR] No OCR engine available. Install one of:\n"
             "  pip install ocrmac            # macOS, Apple Vision (recommended)\n"
             "  pip install pytesseract + brew install tesseract tesseract-lang")


def ocr_directory(images_dir: str, min_symbols: int, output_path: str | None):
    files = sorted(
        f for f in glob.glob(os.path.join(images_dir, "*"))
        if f.lower().endswith(_SUPPORTED)
    )
    if not files:
        sys.exit(f"[ERROR] No images in {images_dir}")

    result = {}
    print(f"OCR {len(files)} images from {images_dir} ...")
    for f in files:
        name = os.path.basename(f)
        text = ocr_one(f)
        score = _code_score(text)
        if score < min_symbols:
            # Still record, but flag as low code-likelihood (probably a diagram/photo)
            result[name] = {"text": text, "code_score": score, "code_like": False}
            print(f"  · {name}: {len(text)} chars, code_score={score}")
        else:
            result[name] = {"text": text, "code_score": score, "code_like": True}
            print(f"  ✓ {name}: {len(text)} chars, code_score={score}  ← code-like")

    if output_path is None:
        output_path = os.path.join(images_dir, "ocr_text.json")
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    code_like = sum(1 for v in result.values() if v["code_like"])
    print(f"\nDone: {len(result)} OCR'd, {code_like} look code-like. Saved: {output_path}")


def main():
    ap = argparse.ArgumentParser(description="OCR screenshots to a text baseline")
    ap.add_argument("path", help="Image file or directory of images")
    ap.add_argument("--json", action="store_true",
                    help="Directory mode: write ocr_text.json {file: {text, code_score, code_like}}")
    ap.add_argument("--min-symbols", type=int, default=6,
                    help="code_score threshold to flag an image as code-like (default 6)")
    ap.add_argument("--output", default=None, help="Output path for ocr_text.json")
    args = ap.parse_args()

    if os.path.isdir(args.path):
        ocr_directory(args.path, args.min_symbols, args.output)
    elif os.path.isfile(args.path):
        text = ocr_one(args.path)
        if args.json:
            print(json.dumps({os.path.basename(args.path):
                              {"text": text, "code_score": _code_score(text)}},
                             ensure_ascii=False, indent=2))
        else:
            print(text)
    else:
        sys.exit(f"[ERROR] Not found: {args.path}")


if __name__ == "__main__":
    main()
