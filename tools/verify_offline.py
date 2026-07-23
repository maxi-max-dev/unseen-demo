#!/usr/bin/env python3
"""校验 dist/offline.html 里没有残留的外链/相对路径图片引用，全是 data: 内联，
且内联图片计数对得上预期(3 全景 + 12 照片 + 1 地图底图 = 16)。"""
import re
import sys

# 全景(4) + 照片(16) + 地图底图(1)；7/23 婚礼旅程改版后从 16 变成 21
# (AdventureX 版是 3 全景 + 12 照片 + 1 地图 = 16)。
# 改 tour.js 里的节点/照片数量或加减地图底图时要跟着改这个数。
EXPECTED_DATA_URI_COUNT = 21

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
