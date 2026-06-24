#!/usr/bin/env python3
"""
成稿外链可达性核验（doc-to-notes Step 7e）：扫描笔记 .md 里引用的所有图片/链接 URL，
逐个 HTTP 探测，确认能正常展示。发现不可达的 OSS 图时，加 --images-dir 可自动重传修复。

用法：
    python3 check_links.py <笔记.md 或笔记目录>
    python3 check_links.py <笔记.md 或笔记目录> --images-dir /tmp/doc_notes_xxx/images

检测规则：
    [ERROR] URL 无法访问（非 200、连接超时、Content-Type 非 image/* 且为图片语法、Content-Length=0）
    [WARN]  非图片 URL（外链 / github / localhost 等）无法访问
    [OK]    所有 URL 可正常访问

--images-dir 修复模式：
    发现 OSS 图片 URL 不可达时，自动调用 upload_oss.py 全量重传并复检。
    仍不可达的需人工排查（bucket 公共读设置 / 防盗链 / 链接本身失效）。
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 匹配 Markdown 图片语法 ![alt](url) 和普通链接 [text](url)
_MD_URL_RE = re.compile(r'!?\[(?:[^\]]*)\]\((https?://[^) \t\n]+)\)')
# 匹配裸 https?:// URL（不在括号里）
_BARE_URL_RE = re.compile(r'(?<!\()(https?://[^\s)"\'<>]+)')

_TIMEOUT = 15  # 秒
_OSS_HOST = "oss-cn-shanghai.aliyuncs.com"
_OSS_CUSTOM = "sky-obsidian-images.oss-cn-shanghai.aliyuncs.com"


def extract_urls(md_text: str) -> list:
    """提取 MD 里所有 http(s) URL，标注是否为图片语法。返回 [(url, is_image), ...]，去重保序。"""
    seen = set()
    results = []
    # 图片语法优先（带 !）
    for m in _MD_URL_RE.finditer(md_text):
        url = m.group(1).rstrip(")")
        is_img = m.group(0).startswith("!")
        if url not in seen:
            seen.add(url)
            results.append((url, is_img))
    # 裸 URL（补漏）
    for m in _BARE_URL_RE.finditer(md_text):
        url = m.group(1).rstrip(".,;)")
        if url not in seen:
            seen.add(url)
            results.append((url, False))
    return results


def check_url(url: str, is_image: bool) -> dict:
    """
    HTTP HEAD 探测 URL 可达性。返回 {url, is_image, ok, status, content_type, size, error}。
    HEAD 被拒时 fallback GET（只取头部）。
    """
    result = {"url": url, "is_image": is_image, "ok": False,
              "status": None, "content_type": "", "size": -1, "error": ""}
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method,
                                         headers={"User-Agent": "doc-to-notes-checker/1.0"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                result["status"] = resp.status
                result["content_type"] = resp.headers.get("Content-Type", "")
                cl = resp.headers.get("Content-Length", "")
                result["size"] = int(cl) if cl.isdigit() else -1
                if resp.status == 200:
                    # 图片 URL 要求 Content-Type 为 image/*
                    if is_image and not result["content_type"].startswith("image/"):
                        result["error"] = f"Content-Type={result['content_type']} (期望 image/*)"
                    elif result["size"] == 0:
                        result["error"] = "Content-Length=0，对象可能为空"
                    else:
                        result["ok"] = True
                else:
                    result["error"] = f"HTTP {resp.status}"
            return result
        except urllib.error.HTTPError as e:
            result["status"] = e.code
            result["error"] = f"HTTP {e.code}"
            if method == "HEAD" and e.code in (405, 403):
                continue  # 尝试 GET
            return result
        except Exception as e:
            result["error"] = str(e)
            if method == "HEAD":
                continue
            return result
    return result


def check_urls_parallel(url_list: list, workers: int = 8) -> list:
    """并发探测所有 URL，返回结果列表（保序）。"""
    results = [None] * len(url_list)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(check_url, url, is_img): i
                   for i, (url, is_img) in enumerate(url_list)}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


def is_oss_url(url: str) -> bool:
    return _OSS_HOST in url or _OSS_CUSTOM in url


def fix_with_reupload(images_dir: str) -> bool:
    """调用 upload_oss.py 重传 images_dir，返回是否成功（退出码 0）。"""
    script = Path(__file__).parent / "upload_oss.py"
    ret = subprocess.run(
        [sys.executable, str(script), images_dir],
        capture_output=False
    )
    return ret.returncode == 0


def check_file(filepath: str) -> list:
    try:
        md = open(filepath, encoding="utf-8").read()
    except OSError as e:
        return [{"url": filepath, "is_image": False, "ok": False,
                 "error": f"无法读取: {e}", "status": None, "content_type": "", "size": -1}]
    url_list = extract_urls(md)
    if not url_list:
        return []
    return check_urls_parallel(url_list)


def check_path(path: str) -> list:
    if os.path.isfile(path):
        return check_file(path)
    if os.path.isdir(path):
        results = []
        for f in sorted(glob.glob(os.path.join(path, "**", "*.md"), recursive=True)):
            results.extend(check_file(f))
        return results
    return [{"url": path, "is_image": False, "ok": False,
             "error": "路径不存在", "status": None, "content_type": "", "size": -1}]


def main() -> int:
    ap = argparse.ArgumentParser(description="成稿外链可达性核验 (doc-to-notes Step 7e)")
    ap.add_argument("note", help="笔记 .md 路径或目录")
    ap.add_argument("--images-dir", default=None,
                    help="本地图片目录（/tmp/doc_notes_xxx/images），发现 OSS 图不可达时自动重传修复")
    args = ap.parse_args()

    print(f"=== 外链可达性核验: {args.note} ===")
    results = check_path(args.note)

    if not results:
        print("✅ 未发现任何 URL")
        return 0

    errors = [r for r in results if not r["ok"] and r["is_image"]]
    warns  = [r for r in results if not r["ok"] and not r["is_image"]]
    ok     = [r for r in results if r["ok"]]

    # 输出 OK 的图片
    for r in ok:
        if r["is_image"]:
            size_str = f" ({r['size']} bytes)" if r["size"] > 0 else ""
            print(f"  [OK]  {r['url']}{size_str}")

    # 输出警告（非图片 URL）
    for r in warns:
        print(f"  [WARN] {r['url']}")
        print(f"         → {r['error']}")

    # 输出 ERROR（图片 URL 不可达）
    for r in errors:
        print(f"  [ERROR] {r['url']}")
        print(f"          → {r['error']}")

    print()
    print(f"合计: {len(ok)} 可达, {len(errors)} 个图片 ERROR, {len(warns)} 个外链 WARN")

    if errors:
        oss_errors = [r for r in errors if is_oss_url(r["url"])]
        if oss_errors and args.images_dir:
            print(f"\n🔧 发现 {len(oss_errors)} 个 OSS 图片不可达，正在重传 {args.images_dir} ...")
            ok_reupload = fix_with_reupload(args.images_dir)
            if ok_reupload:
                print("\n🔁 重传完成，复检中 ...")
                results2 = check_path(args.note)
                errors2 = [r for r in results2 if not r["ok"] and r["is_image"]]
                if not errors2:
                    print("✅ 复检通过，所有图片 URL 均可达")
                    return 0
                else:
                    print(f"⚠️  仍有 {len(errors2)} 个 URL 不可达，需人工排查：")
                    for r in errors2:
                        print(f"  [ERROR] {r['url']} → {r['error']}")
                    return 1
            else:
                print("❌ 重传失败，请检查 upload_oss.py 错误输出")
                return 1
        elif oss_errors:
            print(f"\n💡 {len(oss_errors)} 个 OSS 图不可达。加 --images-dir 参数可自动重传修复：")
            print(f"   python3 {Path(__file__).name} {args.note} --images-dir <本地图片目录>")
        print("⚠️  存在图片不可达，请修复后重新运行。")
        return 1

    if warns:
        print("（WARN 为非图片外链，不影响笔记图片展示，可酌情排查）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
