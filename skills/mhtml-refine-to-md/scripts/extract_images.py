#!/usr/bin/env python3
"""
从极客时间 .mhtml 文件中提取内容图片到临时目录，并输出原文统计信息。

用法:
    python3 extract_images.py <mhtml文件绝对路径> [--out 输出目录]

行为:
    1. 清空输出目录（默认 /tmp/geektime_imgs），避免与上次运行的图片混淆
    2. 遍历 MHTML 的 MIME parts，提取所有 Content-Location 含 'resource/image' 的图
    3. 通过对比图片引用位置与首段 Slate 文本位置，标注 COVER / CONTENT
    4. 对 CONTENT 图检查尺寸，若任意边 > 2000px 则自动缩放至 ≤ 2000px（保持比例）
       — 原因：Claude API many-image requests 限制单边最大 2000px
    5. **装饰图启发式标记**：CONTENT 图若同时满足"任意边 < 1500px"且"字节数 < 350KB"，
       追加 [LIKELY_DECORATIVE] 标注 —— 这类图多为卡通插画/概念隐喻装饰，文字信息密度低，
       视觉分析时可以快速扫一眼即可决定要不要还原成 [!INFO] 类比块（多数情况省略也无损信息）
    6. 每张图输出一行: <文件名> | <COVER|CONTENT> | <字节数> | <原始URL前80字符>
       — 若发生缩放，追加 [RESIZED WxH→W'xH']
       — 若疑似装饰图，追加 [LIKELY_DECORATIVE]
    7. 最后输出一行 SLATE_CHARS: <N>，统计原文 data-slate-string 纯文本总字符数

输出图片可直接用 Read 工具视觉分析，COVER 图直接跳过。
[LIKELY_DECORATIVE] 图建议先用一张图判断是否系列重复装饰，是则后续同系列图可批量略读。
SLATE_CHARS 用于 Step 6 字数比例核查（笔记字符数 ≥ N × 60%）。
"""

import argparse
import email
import os
import re
import shutil
import struct
import subprocess
import sys
import zlib

# ── 尺寸检查 / 缩放工具函数 ──────────────────────────────────────────────────

MAX_DIM = 2000  # Claude many-image requests 单边像素上限

# 装饰图启发式阈值：任意边 < 这个值 且 字节数 < 阈值 → 标记 LIKELY_DECORATIVE
DECORATIVE_MAX_DIM = 1500
DECORATIVE_MAX_BYTES = 350 * 1024  # 350KB


def _get_dims_sips(path: str):
    """用 macOS sips 获取图片尺寸，返回 (width, height) 或 None。"""
    try:
        out = subprocess.check_output(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        w = h = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("pixelWidth:"):
                w = int(line.split(":")[-1].strip())
            elif line.startswith("pixelHeight:"):
                h = int(line.split(":")[-1].strip())
        if w and h:
            return w, h
    except Exception:
        pass
    return None


def _get_dims_pil(path: str):
    """用 Pillow 获取图片尺寸，返回 (width, height) 或 None。"""
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as im:
            return im.size  # (width, height)
    except Exception:
        return None


def _get_dims_png(path: str):
    """从 PNG 文件头直接读取尺寸，无需第三方库，返回 (width, height) 或 None。"""
    try:
        with open(path, "rb") as f:
            sig = f.read(8)
            if sig != b'\x89PNG\r\n\x1a\n':
                return None
            f.read(4)  # length
            chunk_type = f.read(4)
            if chunk_type != b'IHDR':
                return None
            w = struct.unpack(">I", f.read(4))[0]
            h = struct.unpack(">I", f.read(4))[0]
            return w, h
    except Exception:
        return None


def _get_dims_jpeg(path: str):
    """从 JPEG 文件段解析尺寸，无需第三方库，返回 (width, height) 或 None。"""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b'\xff\xd8':
                return None
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    break
                if marker[0] != 0xff:
                    break
                seg_id = marker[1]
                length = struct.unpack(">H", f.read(2))[0]
                if seg_id in (0xc0, 0xc1, 0xc2):  # SOF0/1/2
                    f.read(1)  # precision
                    h = struct.unpack(">H", f.read(2))[0]
                    w = struct.unpack(">H", f.read(2))[0]
                    return w, h
                f.seek(length - 2, 1)
    except Exception:
        pass
    return None


def get_image_dims(path: str):
    """
    尝试多种方式获取图片尺寸，返回 (width, height) 或 None。
    优先级：Pillow > 纯Python内置解析 > sips（macOS）
    """
    dims = _get_dims_pil(path)
    if dims:
        return dims
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "png":
        dims = _get_dims_png(path)
    elif ext in ("jpg", "jpeg"):
        dims = _get_dims_jpeg(path)
    if dims:
        return dims
    return _get_dims_sips(path)


def resize_if_needed(path: str):
    """
    检查图片尺寸，若任意边 > MAX_DIM 则缩放至 ≤ MAX_DIM（保持比例）。
    返回 (original_w, original_h, new_w, new_h, actual_path) 或 None（未发生缩放/无法获取尺寸）。
    actual_path 为缩放后的文件路径（webp 会被转为 png，路径会变）。
    """
    dims = get_image_dims(path)
    if not dims:
        return None
    w, h = dims
    if w <= MAX_DIM and h <= MAX_DIM:
        return None  # 无需缩放

    # 计算缩放后尺寸
    ratio = MAX_DIM / max(w, h)
    new_w, new_h = int(w * ratio), int(h * ratio)

    # 优先用 Pillow 缩放
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as im:
            resized = im.resize((new_w, new_h), Image.LANCZOS)
            resized.save(path)
        return w, h, new_w, new_h, path
    except ImportError:
        pass

    # 降级用 sips（macOS 内建）
    # sips 无法原地写 WebP，需先转 PNG 再缩放
    out_path = path
    if path.lower().endswith(".webp"):
        out_path = path[:-5] + ".png"  # 转为 PNG

    try:
        cmd = ["sips", "-s", "format", "png", "--resampleHeightWidthMax", str(MAX_DIM), path, "--out", out_path]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if out_path != path:
            os.remove(path)  # 删除原 webp
        # 重新读取实际尺寸确认
        new_dims = get_image_dims(out_path)
        if new_dims:
            return w, h, new_dims[0], new_dims[1], out_path
        return w, h, new_w, new_h, out_path
    except Exception as e:
        print(f"  ⚠️  无法缩放 {path}（sips 失败: {e}）", file=sys.stderr)
        return None


# ── 主提取逻辑 ────────────────────────────────────────────────────────────────

def extract(source_file: str, out_dir: str) -> int:
    if not os.path.isfile(source_file):
        print(f"ERROR: 源文件不存在: {source_file}", file=sys.stderr)
        return 1

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    with open(source_file, "rb") as f:
        msg = email.message_from_bytes(f.read())

    html = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html = part.get_payload(decode=True).decode("utf-8", errors="ignore")
            break

    first_slate = html.find('data-slate-string="true"')
    if first_slate < 0:
        first_slate = len(html)  # 没找到 Slate 标记时所有图都按 CONTENT 处理

    idx = 0
    for part in msg.walk():
        ct = part.get_content_type()
        loc = part.get("Content-Location", "")
        if not (ct.startswith("image/") and "resource/image" in loc):
            continue

        data = part.get_payload(decode=True)
        ext = "jpg" if "jpeg" in ct else ct.split("/")[-1]
        fname = os.path.join(out_dir, f"img_{idx:02d}.{ext}")
        with open(fname, "wb") as out:
            out.write(data)

        # 用图片文件名（不含查询参数）在 HTML 中定位引用位置
        ref_key = loc.split("/")[-1].split("?")[0]
        img_pos = html.find(ref_key)
        tag = "COVER" if 0 <= img_pos < first_slate else "CONTENT"

        resize_note = ""
        decorative_note = ""
        display_fname = f"img_{idx:02d}.{ext}"
        actual_path = fname
        if tag == "CONTENT":
            result = resize_if_needed(fname)
            if result:
                ow, oh, nw, nh, actual_path = result
                resize_note = f" [RESIZED {ow}x{oh}→{nw}x{nh}]"
                # 如果文件被重命名（webp→png），更新显示名
                if actual_path != fname:
                    display_fname = os.path.basename(actual_path)
                # 更新字节数为缩放后大小
                data = open(actual_path, "rb").read()
            # 装饰图启发式：缩放后的最终尺寸 & 字节数都偏小 → 多为卡通插画/概念隐喻图
            dims = get_image_dims(actual_path)
            if dims:
                w, h = dims
                if max(w, h) < DECORATIVE_MAX_DIM and len(data) < DECORATIVE_MAX_BYTES:
                    decorative_note = " [LIKELY_DECORATIVE]"

        print(f"{display_fname} | {tag} | {len(data)} bytes | {loc[:80]}{resize_note}{decorative_note}")
        idx += 1

    if idx == 0:
        print("(未发现任何 resource/image 内容图)")

    # 统计原文 Slate 纯文本字符数（剥离嵌套 HTML 标签与常见实体）
    slate_texts = re.findall(r'<span data-slate-string="true">(.*?)</span>', html, re.DOTALL)
    full_text = ''
    for t in slate_texts:
        cleaned = re.sub(r'<[^>]+>', '', t)
        cleaned = cleaned.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        full_text += cleaned
    print(f"SLATE_CHARS: {len(full_text)}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Extract content images from a geektime .mhtml file")
    p.add_argument("source_file", help="绝对路径，指向 .mhtml 文件")
    p.add_argument("--out", default="/tmp/geektime_imgs", help="输出目录（默认 /tmp/geektime_imgs）")
    args = p.parse_args()
    return extract(args.source_file, args.out)


if __name__ == "__main__":
    sys.exit(main())
