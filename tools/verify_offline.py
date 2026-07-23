#!/usr/bin/env python3
"""校验 dist/offline.html 里没有残留的外链/相对路径图片引用，全是 data: 内联，
且内联图片计数对得上预期(全景数 + 照片数 + 1 张地图底图，从 tour.js 动态推算，不再硬编码)。"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOUR_JS = os.path.join(ROOT, "tour.js")


def load_tour(path=TOUR_JS):
    """跟 match.py 的 apply_matches() 用同一种解法读 tour.js: 定位 "window.TOUR = " 标记,
    去掉结尾的 ";", 剩下的部分就是合法 JSON。"""
    text = open(path, encoding="utf-8").read()
    marker = "window.TOUR = "
    idx = text.index(marker)
    body = text[idx + len(marker):].rstrip()
    if body.endswith(";"):
        body = body[:-1]
    return json.loads(body)


def expected_data_uri_count(tour):
    """全景(nodes[].panorama 去重后的张数) + 照片(nodes[].photos 之和) + 1 张地图底图。
    改 tour.js 里的节点/照片数量或加减地图底图时, 这个数会自动跟着变, 不用再手改。"""
    panorama_count = len({n["panorama"] for n in tour["nodes"] if n.get("panorama")})
    photo_count = sum(len(n.get("photos", [])) for n in tour["nodes"])
    map_count = 1 if tour.get("map", {}).get("image") else 0
    return panorama_count + photo_count + map_count


EXPECTED_DATA_URI_COUNT = expected_data_uri_count(load_tour())

path = sys.argv[1] if len(sys.argv) > 1 else "dist/offline.html"
html = open(path, encoding="utf-8").read()

bad_ext_src = re.findall(r'(?:src|panorama|image)\s*[:=]\s*["\']https?://[^"\']*', html)
bad_rel_asset = re.findall(r'["\'](?:\.\./)?assets/[^"\']*\.(?:jpg|jpeg|png)["\']', html)
bad_script_tag = re.findall(r'<script\s+src="\.\./tour\.js"', html)
data_uri_count = len(re.findall(r'data:image/[a-zA-Z+]+;base64,', html))

problems = bad_ext_src + bad_rel_asset + bad_script_tag
if problems:
    print("FAIL 残留引用未清理: %s" % problems[:5])
    sys.exit(1)
if data_uri_count != EXPECTED_DATA_URI_COUNT:
    print("FAIL data: 内联图片计数 = %d，预期 %d（不匹配，检查 tour.js 或 pack.py 是否漏打包了什么）" % (
        data_uri_count, EXPECTED_DATA_URI_COUNT
    ))
    sys.exit(1)
print("PASS 无 http(s):// / 相对路径图片残留，data: 内联图片计数 = %d（预期 %d，匹配）" % (
    data_uri_count, EXPECTED_DATA_URI_COUNT
))
