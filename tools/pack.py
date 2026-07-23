#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pack.py -- 空间记忆离线打包器

把 viewer/index.html + tour.js + 所有引用的图片(panorama/照片)
打成单个自包含 HTML 文件 dist/offline.html：
  - tour.js 内联成 <script>window.TOUR = {...}</script>
  - 所有 panorama / photo.src 图片路径替换成完整的
    data:image/<mime>;base64,xxx (带前缀，裸 base64 会崩)
  - 可选 --max-width 把全景图打包前等比压缩到指定宽度(默认 4096)，
    用 macOS 自带的 sips 做缩放，零第三方 python 依赖。

用法:
  python3 tools/pack.py
  python3 tools/pack.py --max-width 2048
  python3 tools/pack.py --viewer viewer/index.html --tour tour.js --out dist/offline.html
"""

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOUR_JS_TAG_RE = re.compile(r'<script\s+src="\.\./tour\.js"\s*></script>')
PANORAMA_CONCAT = '"../" + node.panorama'
PHOTO_SRC_CONCAT = '"../" + photo.src'
MAP_IMAGE_CONCAT = '"../" + TOUR.map.image'


def die(msg):
    print("pack.py 失败: " + msg, file=sys.stderr)
    sys.exit(1)


def guess_mime(path):
    mime, _ = mimetypes.guess_type(path)
    return mime or "image/jpeg"


def maybe_downscale(abs_path, max_width, tmp_dir):
    """若图片宽度 > max_width，用 sips 等比压到 max_width，返回新路径；否则原样返回。"""
    probe = subprocess.run(
        ["sips", "-g", "pixelWidth", abs_path],
        capture_output=True, text=True
    )
    if probe.returncode != 0:
        print("  警告: sips 读取宽度失败，跳过压缩 -> " + abs_path, file=sys.stderr)
        return abs_path
    m = re.search(r"pixelWidth:\s*(\d+)", probe.stdout)
    if not m:
        return abs_path
    width = int(m.group(1))
    if width <= max_width:
        return abs_path

    out_path = os.path.join(tmp_dir, os.path.basename(abs_path))
    resize = subprocess.run(
        ["sips", "-Z", str(max_width), abs_path, "--out", out_path],
        capture_output=True, text=True
    )
    if resize.returncode != 0:
        print("  警告: sips 压缩失败，改用原图 -> " + abs_path, file=sys.stderr)
        return abs_path
    return out_path


def to_data_uri(rel_path, base_dir, max_width=None, tmp_dir=None):
    abs_path = os.path.normpath(os.path.join(base_dir, rel_path))
    if not os.path.isfile(abs_path):
        die("找不到图片: " + abs_path + "（tour.js 里引用的是 " + rel_path + "）")

    use_path = abs_path
    if max_width is not None:
        use_path = maybe_downscale(abs_path, max_width, tmp_dir)

    with open(use_path, "rb") as f:
        raw = f.read()
    mime = guess_mime(abs_path)
    b64 = base64.b64encode(raw).decode("ascii")
    return "data:" + mime + ";base64," + b64, len(raw)


def load_tour(tour_path):
    text = open(tour_path, "r", encoding="utf-8").read()
    m = re.search(r"window\.TOUR\s*=\s*(\{.*\})\s*;\s*$", text, re.DOTALL)
    if not m:
        die("tour.js 格式不认识，找不到 window.TOUR = {...}; （" + tour_path + "）")
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        die("tour.js 里的 JSON 解析失败: " + str(e))
    return data


def pack(viewer_path, tour_path, out_path, max_width):
    if not os.path.isfile(viewer_path):
        die("找不到 viewer: " + viewer_path)
    if not os.path.isfile(tour_path):
        die("找不到 tour.js: " + tour_path)

    tour = load_tour(tour_path)
    project_root = os.path.dirname(os.path.abspath(tour_path))

    stats = {"panoramas": 0, "photos": 0, "map_images": 0, "raw_bytes": 0}
    tmp_dir = tempfile.mkdtemp(prefix="psm-pack-")
    try:
        for node in tour.get("nodes", []):
            uri, n = to_data_uri(node["panorama"], project_root, max_width, tmp_dir)
            node["panorama"] = uri
            stats["panoramas"] += 1
            stats["raw_bytes"] += n

            for photo in node.get("photos", []):
                uri, n = to_data_uri(photo["src"], project_root)
                photo["src"] = uri
                stats["photos"] += 1
                stats["raw_bytes"] += n

        map_cfg = tour.get("map")
        if isinstance(map_cfg, dict) and map_cfg.get("image"):
            uri, n = to_data_uri(map_cfg["image"], project_root, max_width, tmp_dir)
            map_cfg["image"] = uri
            stats["map_images"] += 1
            stats["raw_bytes"] += n
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    tour_js_inline = "window.TOUR = " + json.dumps(tour, ensure_ascii=False) + ";"

    html = open(viewer_path, "r", encoding="utf-8").read()

    if not TOUR_JS_TAG_RE.search(html):
        die('viewer html 里没找到 <script src="../tour.js"></script>，数据契约变了？')
    html = TOUR_JS_TAG_RE.sub(
        lambda _m: "<script>\n" + tour_js_inline + "\n</script>",
        html, count=1
    )

    # index.html 在 viewer/ 目录下，运行时用 "../" 把相对路径拼回项目根目录读图。
    # 打包后图片已经是 data: URI，不能再拼 "../"，否则前缀被破坏直接崩。
    for needle in (PANORAMA_CONCAT, PHOTO_SRC_CONCAT, MAP_IMAGE_CONCAT):
        if needle not in html:
            die("viewer html 里没找到预期的拼接代码: " + needle + "（上游改过 index.html？pack.py 要跟着改）")
    html = html.replace(PANORAMA_CONCAT, "node.panorama")
    html = html.replace(PHOTO_SRC_CONCAT, "photo.src")
    html = html.replace(MAP_IMAGE_CONCAT, "TOUR.map.image")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return stats


def main():
    ap = argparse.ArgumentParser(description="空间记忆离线打包器")
    ap.add_argument("--viewer", default=os.path.join(ROOT, "viewer", "index.html"))
    ap.add_argument("--tour", default=os.path.join(ROOT, "tour.js"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "offline.html"))
    ap.add_argument("--max-width", type=int, default=4096,
                     help="全景图打包前等比压缩到的最大宽度，默认 4096（不放大）")
    args = ap.parse_args()

    stats = pack(args.viewer, args.tour, args.out, args.max_width)

    out_size = os.path.getsize(args.out)
    print("打包完成 -> " + args.out)
    print("  全景: %d 张 / 照片: %d 张 / 底图: %d 张（源文件共 %.1f MB）" % (
        stats["panoramas"], stats["photos"], stats["map_images"], stats["raw_bytes"] / 1024 / 1024
    ))
    print("  输出大小: %.1f MB (%d bytes)" % (out_size / 1024 / 1024, out_size))


if __name__ == "__main__":
    main()
