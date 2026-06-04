#!/usr/bin/env python3
"""
Upload a directory of images to Aliyun OSS and output a URL mapping JSON.

Usage:
    python3 upload_oss.py <images_dir> [--output <mapping.json>]

Outputs:
    <images_dir>/url_mapping.json  (or --output path)
    Format: {"image001.png": "https://...", ...}

Requires: oss2  (pip install oss2)
"""

import sys
import os
import json
import hashlib
import argparse
from pathlib import Path

try:
    import oss2
except ImportError:
    sys.exit("[ERROR] oss2 not installed. Run: pip install oss2")

# OSS configuration — mirrors PicGo / organize-course-package settings
_OSS_ACCESS_KEY_ID     = os.environ.get("OSS_ACCESS_KEY_ID", "")
_OSS_ACCESS_KEY_SECRET = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
_OSS_BUCKET_NAME       = "sky-obsidian-images"
_OSS_ENDPOINT          = "https://oss-cn-shanghai.aliyuncs.com"
_OSS_PATH_PREFIX       = "images/"
_OSS_CUSTOM_DOMAIN     = "sky-obsidian-images.oss-cn-shanghai.aliyuncs.com"

_SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


def get_bucket():
    auth = oss2.Auth(_OSS_ACCESS_KEY_ID, _OSS_ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, _OSS_ENDPOINT, _OSS_BUCKET_NAME)


def content_key(local_path: str) -> str:
    """
    Deterministic OSS key derived from file CONTENT (md5).

    Using a content hash (instead of Python's process-randomized hash()) means:
      - Re-running never produces a different key for the same image → no duplicate
        uploads, no orphaned objects, stable url_mapping.json across runs.
      - Identical images (common: repeated logos/screenshots) dedupe to one object.
    """
    h = hashlib.md5()
    with open(local_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_image(bucket, local_path: str):
    """
    Upload single image keyed by content md5.
    Returns (url, status) where status is 'uploaded' | 'skipped' | None (failure).
    """
    if not os.path.exists(local_path):
        print(f"  [WARN] Not found: {local_path}", file=sys.stderr)
        return (None, None)

    ext = Path(local_path).suffix.lower()
    oss_key = f"{_OSS_PATH_PREFIX}doc_{content_key(local_path)}{ext}"
    url = f"https://{_OSS_CUSTOM_DOMAIN}/{oss_key}"
    try:
        # Skip re-upload if object already exists (idempotent across runs)
        if bucket.object_exists(oss_key):
            return (url, "skipped")
        bucket.put_object_from_file(oss_key, local_path)
        return (url, "uploaded")
    except Exception as e:
        print(f"  [ERROR] Upload failed for {local_path}: {e}", file=sys.stderr)
        return (None, None)


def upload_directory(images_dir: str, output_path: str | None = None) -> dict:
    """
    Upload all images in images_dir to OSS.
    Returns mapping: {filename: url}
    """
    images_dir = Path(images_dir)
    if not images_dir.is_dir():
        sys.exit(f"[ERROR] Not a directory: {images_dir}")

    # Collect image files
    image_files = sorted(
        f for f in images_dir.iterdir()
        if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS
    )

    if not image_files:
        print(f"[WARN] No images found in {images_dir}")
        return {}

    bucket = get_bucket()
    mapping = {}
    uploaded = skipped = failed = 0

    print(f"Processing {len(image_files)} images from {images_dir} ...")

    for img_file in image_files:
        print(f"  → {img_file.name}", end=" ", flush=True)
        url, status = upload_image(bucket, str(img_file))
        if url:
            mapping[img_file.name] = url
            if status == "skipped":
                skipped += 1
                print("• already on OSS")
            else:
                uploaded += 1
                print(f"✓ {url}")
        else:
            failed += 1
            print("✗ FAILED")

    print(f"\nDone: {uploaded} uploaded, {skipped} already existed, {failed} failed")

    # Save mapping
    if output_path is None:
        output_path = str(images_dir / "url_mapping.json")
    Path(output_path).write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapping saved: {output_path}")

    return mapping


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload images to Aliyun OSS")
    parser.add_argument("images_dir", help="Directory containing images to upload")
    parser.add_argument("--output", default=None, help="Output path for url_mapping.json")
    args = parser.parse_args()

    upload_directory(args.images_dir, args.output)
