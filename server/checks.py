#!/usr/bin/env python3
"""
server/checks.py -- 自检环【第一闸: 确定性结构检查】。

不看画面、不问模型, 只用 numpy/Pillow/标准库把一个会话目录(server/sessions/<id>/)
里"能用眼睛之外的手段查出来的错"全部查一遍: manifest 字段齐不齐、文件在不在、
全景是不是 2:1、深度图是不是模型挂了、照片方位角合不合法、置信度够不够。

对外只有两个函数:
    run_structural(session_dir, conf_min=0.45) -> dict   # 报告契约里的 gates.structural
    low_confidence_photos(session_dir, conf_min=0.45) -> list[int]  # 低置信照片下标

返回结构固定为 {"ok": bool, "checks": [{"id","ok","detail"}, ...], "failed": [id, ...]},
checks 里那 6 项永远都在(哪怕 manifest 根本没读出来, 也逐项给出中文说明), 顺序固定,
编排器可以直接按 id 取。

致命 / 不致命的口径(编排器依赖这个语义, 别改):
  - 除 photo_confidence 外的 5 项任意一项挂 = 结构闸整体 ok=False, 页面不该往下走。
  - photo_confidence 挂只说明"某几张照片放得不太准", 不致命, 整体 ok 仍可为 True,
    但它会出现在 failed 列表里, 编排器据此触发自愈(重匹配/降级/丢弃那几张)。

跑法(仓库根目录):
    .venv/bin/python -m server.checks server/sessions/fixture

不改动 tools/ 下任何现有脚本, 零新依赖。
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image

# 六项 check 的 id 和顺序, 是报告契约的一部分, 只能是这 6 个, 不许增删改名
CHECK_IDS = (
    "manifest_fields",
    "assets_exist",
    "pano_ratio",
    "depth_sane",
    "photo_coords",
    "photo_confidence",
)

# 不致命的项: 挂了也不把整体 ok 拉下水, 只进 failed 让编排器去自愈
NON_FATAL = {"photo_confidence"}

# manifest 必须有的字段
REQUIRED_FIELDS = ("panorama", "depth", "depthJson", "photos")

# 全景/深度图的目标宽高比和容差: equirect 必须是 2:1, 允许 ±3% 的编码误差
TARGET_RATIO = 2.0
RATIO_TOL = 0.03


# ---------------------------------------------------------------- 小工具
def _is_finite_number(v):
    """是有限实数吗。布尔值虽然是 int 的子类, 但当角度用一定是脏数据, 直接判否。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return math.isfinite(float(v))


def _load_manifest(session_dir):
    """读 manifest.json。返回 (manifest_dict, 错误中文说明); 成功时错误说明为 None。"""
    path = os.path.join(session_dir, "manifest.json")
    if not os.path.isfile(path):
        return None, "manifest.json 不存在: %s" % path
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return None, "manifest.json 解析失败: %s" % e
    if not isinstance(manifest, dict):
        return None, "manifest.json 顶层不是对象, 实际是 %s" % type(manifest).__name__
    return manifest, None


def _photos_of(manifest):
    """取 photos 列表, 拿不到就给空列表, 后面的检查各自会报错, 这里不抛异常。"""
    photos = manifest.get("photos") if isinstance(manifest, dict) else None
    return photos if isinstance(photos, list) else []


def _label(i, photo):
    """照片在 detail 里的人话名字: 照片3(photos/003.jpg)。"""
    src = photo.get("src") if isinstance(photo, dict) else None
    return "照片%d(%s)" % (i + 1, src if isinstance(src, str) else "src 缺失")


def _open_size(path):
    """只读图片头拿宽高, 不解码像素(整张 4096x2048 解码太慢, 比例检查用不着)。"""
    with Image.open(path) as img:
        return img.size


def _ratio_ok(w, h):
    """宽高比是否落在 2:1 ±3% 内。"""
    if h <= 0:
        return False, 0.0
    ratio = w / float(h)
    return abs(ratio - TARGET_RATIO) <= TARGET_RATIO * RATIO_TOL, ratio


def _low_conf_indices(photos, conf_min):
    """置信度低于阈值(或压根没有置信度字段)的照片下标。低置信和缺字段一起算, 都得自愈。"""
    bad = []
    for i, p in enumerate(photos):
        conf = p.get("confidence") if isinstance(p, dict) else None
        if not _is_finite_number(conf) or float(conf) < conf_min:
            bad.append(i)
    return bad


# ---------------------------------------------------------------- 六项检查
def _check_manifest_fields(manifest):
    missing = [k for k in REQUIRED_FIELDS if k not in manifest or manifest[k] is None]
    if missing:
        return False, "manifest.json 缺字段: %s" % ", ".join(missing)
    if not isinstance(manifest["photos"], list):
        return False, "photos 字段不是数组, 实际是 %s" % type(manifest["photos"]).__name__
    return True, "manifest.json 解析成功, panorama/depth/depthJson/photos 四个字段齐全, photos 共 %d 张" % len(
        manifest["photos"]
    )


def _check_assets_exist(session_dir, manifest):
    """全景/深度图/深度 json/每张照片都要真存在; 图片还要真解码一次 --
    只判 exists 挡不住"传了一半的半截文件", 那种文件前端一样是黑屏。"""
    photos = _photos_of(manifest)
    image_targets = [("全景", manifest.get("panorama")), ("深度图", manifest.get("depth"))]
    for i, p in enumerate(photos):
        image_targets.append((_label(i, p), p.get("src") if isinstance(p, dict) else None))
    json_targets = [("深度 json", manifest.get("depthJson"))]

    problems = []
    decoded = 0
    for name, rel in image_targets + json_targets:
        if not isinstance(rel, str) or not rel:
            problems.append("%s 的路径字段缺失或不是字符串" % name)
            continue
        path = os.path.join(session_dir, rel)
        if not os.path.isfile(path):
            problems.append("%s 文件不存在(%s)" % (name, rel))

    if problems:
        return False, "资源检查发现 %d 个问题: %s" % (len(problems), "; ".join(problems[:6]))

    for name, rel in image_targets:
        path = os.path.join(session_dir, rel)
        try:
            with Image.open(path) as img:
                img.load()  # 真解码, 半截 jpg 会在这里炸
            decoded += 1
        except Exception as e:
            problems.append("%s 打不开或解码失败(%s): %s" % (name, rel, e))

    if problems:
        return False, "资源检查发现 %d 个问题: %s" % (len(problems), "; ".join(problems[:6]))
    return True, "全景 + 深度图 + 深度 json + %d 张照片全部存在, 其中 %d 张图片解码通过" % (
        len(photos), decoded,
    )


def _check_pano_ratio(session_dir, manifest):
    rel = manifest.get("panorama")
    if not isinstance(rel, str):
        return False, "manifest 里没有可用的 panorama 路径, 无法判比例"
    path = os.path.join(session_dir, rel)
    try:
        w, h = _open_size(path)
    except Exception as e:
        return False, "全景打不开, 无法判比例(%s): %s" % (rel, e)
    ok, ratio = _ratio_ok(w, h)
    if not ok:
        return False, "全景 %dx%d, 比例 %.2f, 超出 2:1 ±%d%%(允许 %.2f~%.2f), 不是标准 equirect" % (
            w, h, ratio, int(RATIO_TOL * 100),
            TARGET_RATIO * (1 - RATIO_TOL), TARGET_RATIO * (1 + RATIO_TOL),
        )
    return True, "全景 %dx%d, 比例 %.2f, 在 2:1 ±%d%% 内, 合格" % (w, h, ratio, int(RATIO_TOL * 100))


def _check_depth_sane(session_dir, manifest):
    """深度三查: json 里的 min/max 是不是正常数、depth.png 是不是 2:1、像素是不是全平。
    全平(所有像素一个值)基本等于 DAP 那步挂了或者输出被清零, 页面会变成一块贴纸。"""
    rel_json = manifest.get("depthJson")
    rel_png = manifest.get("depth")
    if not isinstance(rel_json, str) or not isinstance(rel_png, str):
        return False, "manifest 里 depth/depthJson 路径缺失, 无法判深度"

    try:
        with open(os.path.join(session_dir, rel_json), encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        return False, "深度 json 读不了(%s): %s" % (rel_json, e)
    if not isinstance(meta, dict):
        return False, "深度 json 顶层不是对象(%s)" % rel_json

    dmin, dmax = meta.get("min"), meta.get("max")
    if not _is_finite_number(dmin) or not _is_finite_number(dmax):
        return False, "深度 json 的 min/max 不是有限数(min=%r, max=%r), 模型输出里有 NaN/inf" % (dmin, dmax)
    if not float(dmin) < float(dmax):
        return False, "深度 json 的 min(%.6g) 没有小于 max(%.6g), 深度范围是空的" % (float(dmin), float(dmax))

    png_path = os.path.join(session_dir, rel_png)
    try:
        with Image.open(png_path) as img:
            w, h = img.size
            arr = np.asarray(img)
    except Exception as e:
        return False, "深度图打不开(%s): %s" % (rel_png, e)

    ok, ratio = _ratio_ok(w, h)
    if not ok:
        return False, "深度图 %dx%d, 比例 %.2f, 不接近 2:1, 和全景对不上" % (w, h, ratio)

    if arr.size == 0:
        return False, "深度图 %s 像素为空" % rel_png
    pmin, pmax = int(arr.min()), int(arr.max())
    if pmin == pmax:
        return False, "深度图 %dx%d 所有像素都是同一个值(%d), 深度全平 = 模型没出东西" % (w, h, pmin)

    return True, "深度范围 %.4g~%.4g(有限数), 深度图 %dx%d 比例 %.2f, 像素 %d~%d 不是全平, 合格" % (
        float(dmin), float(dmax), w, h, ratio, pmin, pmax,
    )


def _check_photo_coords(manifest):
    """yaw 必须在 [0,360)、pitch 在 [-90,90], 且都是有限数。
    越界的角度前端会把照片贴到球面外面或者天顶背面, 属于硬错。"""
    photos = _photos_of(manifest)
    problems = []
    for i, p in enumerate(photos):
        if not isinstance(p, dict):
            problems.append("照片%d 不是对象" % (i + 1))
            continue
        yaw, pitch = p.get("yaw"), p.get("pitch")
        if not _is_finite_number(yaw):
            problems.append("%s yaw 不是有限数(%r)" % (_label(i, p), yaw))
        elif not (0.0 <= float(yaw) < 360.0):
            problems.append("%s yaw=%.1f 超出 [0,360)" % (_label(i, p), float(yaw)))
        if not _is_finite_number(pitch):
            problems.append("%s pitch 不是有限数(%r)" % (_label(i, p), pitch))
        elif not (-90.0 <= float(pitch) <= 90.0):
            problems.append("%s pitch=%.1f 超出 [-90,90]" % (_label(i, p), float(pitch)))

    if problems:
        return False, "%d 张照片里有 %d 处方位角非法: %s" % (
            len(photos), len(problems), "; ".join(problems[:6]),
        )
    return True, "%d 张照片的 yaw/pitch 全部合法(yaw∈[0,360), pitch∈[-90,90])" % len(photos)


def _check_photo_confidence(manifest, conf_min):
    """置信度闸: 不致命, 但要点名到底是哪几张不达标, 编排器拿 failed 去触发自愈重匹配。"""
    photos = _photos_of(manifest)
    if not photos:
        return True, "没有照片, 置信度检查跳过"
    bad = _low_conf_indices(photos, conf_min)
    if bad:
        named = ", ".join(
            "%s 置信度 %s" % (
                _label(i, photos[i]),
                ("%.2f" % float(photos[i]["confidence"]))
                if isinstance(photos[i], dict) and _is_finite_number(photos[i].get("confidence"))
                else "缺失",
            )
            for i in bad
        )
        return False, "%d 张里有 %d 张低于阈值 %.2f: %s(不致命, 交给自愈重匹配)" % (
            len(photos), len(bad), conf_min, named,
        )
    confs = [float(p["confidence"]) for p in photos]
    worst = min(range(len(confs)), key=lambda i: confs[i])
    return True, "%d 张照片置信度全部 ≥ %.2f, 最低的是 %s(%.2f)" % (
        len(photos), conf_min, _label(worst, photos[worst]), confs[worst],
    )


# ---------------------------------------------------------------- 对外接口
def run_structural(session_dir, conf_min=0.45):
    """跑完六项结构检查, 返回报告契约里的 gates.structural 对象。

    任何一项内部抛异常都会被兜住变成 ok=False + 中文说明, 这个函数保证不往外抛,
    因为编排器指望它永远能产出一份报告。
    """
    results = {}

    manifest, load_err = _load_manifest(session_dir)
    if manifest is None:
        # manifest 都没读出来, 后面五项无从判起, 但契约要求六项都在, 逐项给出中文说明
        results["manifest_fields"] = (False, load_err)
        for cid in CHECK_IDS[1:]:
            results[cid] = (False, "manifest.json 没读出来, 本项无法判定(先修 manifest_fields)")
    else:
        runners = {
            "manifest_fields": lambda: _check_manifest_fields(manifest),
            "assets_exist": lambda: _check_assets_exist(session_dir, manifest),
            "pano_ratio": lambda: _check_pano_ratio(session_dir, manifest),
            "depth_sane": lambda: _check_depth_sane(session_dir, manifest),
            "photo_coords": lambda: _check_photo_coords(manifest),
            "photo_confidence": lambda: _check_photo_confidence(manifest, conf_min),
        }
        for cid in CHECK_IDS:
            try:
                results[cid] = runners[cid]()
            except Exception as e:
                results[cid] = (False, "检查 %s 时自己炸了: %s: %s" % (cid, type(e).__name__, e))

    checks = [{"id": cid, "ok": results[cid][0], "detail": results[cid][1]} for cid in CHECK_IDS]
    failed = [cid for cid in CHECK_IDS if not results[cid][0]]
    # 整体 ok 只看致命项: photo_confidence 挂了照样能出页面, 只是要走自愈
    ok = all(results[cid][0] for cid in CHECK_IDS if cid not in NON_FATAL)
    return {"ok": ok, "checks": checks, "failed": failed}


def low_confidence_photos(session_dir, conf_min=0.45):
    """返回 manifest.photos 里低置信照片的下标(自愈环节按下标回去重匹配)。
    manifest 读不出来就返回空列表 -- 那种情况轮不到自愈, 结构闸已经整体判死了。"""
    manifest, _err = _load_manifest(session_dir)
    if manifest is None:
        return []
    return _low_conf_indices(_photos_of(manifest), conf_min)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "server/sessions/fixture"
    print(json.dumps(run_structural(target), ensure_ascii=False, indent=2))
