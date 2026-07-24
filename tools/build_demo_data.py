#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把真实空间数据烘成六幕演示页要用的静态数据 + 资产。

为什么要这个脚本:
  1. server/spaces/ 整个被 .gitignore 掉了 —— 线上(Vercel/Pages)根本没有那些照片,
     演示页直接引用本机路径的话, 手机上打开就是一片裂图。
  2. 演示页的每一个数字都必须能追回到真实的 space.json, 不许手打。
     所以数字在这里"导出"而不是在 HTML 里"写死", 谁都能重跑这个脚本核对。

产物:
  web/demo-data.js      window.DEMO_DATA = {...}   (用 <script> 加载, 绕开 file:// 的 fetch 限制)
  web/demo-assets/      演示页真正引用的那几十 KB 图片

用法:  python3 tools/build_demo_data.py
"""

import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPACES = os.path.join(ROOT, "server", "spaces")
OUT_DIR = os.path.join(ROOT, "web", "demo-assets")
OUT_JS = os.path.join(ROOT, "web", "demo-data.js")

# 用哪个空间: s4 是"阈值验证空间", 是唯一一个整批照片都跑过【当前双判据】的空间
# (s1-s3 里有一部分是老阈值 0.45 时代判的, 拿来讲现在的判据会失真)。
SPACE_ID = "s4"

# 这几个"投稿人"是上一轮压测/并发测试留下的名字("延迟测试""你大爷"这种)。
# 记录本身是真的, 只是名字不是人名。演示里把它们统一显示成"匿名宾客"
# —— 只改显示的署名, 不动方位/分数/状态任何一个数字。
NAME_BLOCKLIST = {"泛音测", "泛音测试", "延迟测试", "你大爷", "阿伟测试"}
ANON = "匿名宾客"


def clean_name(name):
    n = (name or "").strip()
    if not n or n in NAME_BLOCKLIST or n.startswith("并发"):
        return ANON
    return n


def die(msg):
    print("✗ " + msg, file=sys.stderr)
    sys.exit(1)


def read_thresholds():
    """阈值从 server/space.py 里读, 不在这里重打一遍 —— 那边改了这边自动跟。"""
    src = open(os.path.join(ROOT, "server", "space.py"), encoding="utf-8").read()
    out = {}
    for key in ("CONF_MIN", "MARGIN_MIN"):
        m = re.search(key + r'\s*=\s*float\(os\.environ\.get\("[^"]+",\s*"([\d.]+)"\)\)', src)
        if not m:
            die("在 server/space.py 里找不到 %s, 判据可能被改过, 停下来别猜" % key)
        out[key] = float(m.group(1))
    return out


def sips(src, dst, long_edge=None):
    """用系统自带 sips 缩图, 不引第三方依赖。long_edge=None 就是直接拷。"""
    if long_edge is None:
        shutil.copyfile(src, dst)
        return
    subprocess.run(
        ["sips", "-Z", str(long_edge), src, "--out", dst],
        check=True, capture_output=True,
    )


def yaw_in_range(yaw, rng):
    """任务的方位区间可能跨 0/360 (比如 [300, 59]), 别切成两段判。"""
    if not rng or yaw is None:
        return False
    a, b = float(rng[0]), float(rng[1])
    y = float(yaw) % 360
    if a <= b:
        return a <= y <= b
    return y >= a or y <= b


def bearing_word(yaw):
    words = ["正前方", "右前方", "右侧", "右后方", "正后方", "左后方", "左侧", "左前方"]
    return words[int(((float(yaw) % 360) + 22.5) // 45) % 8]


def main():
    space_path = os.path.join(SPACES, SPACE_ID, "space.json")
    if not os.path.exists(space_path):
        die("找不到 %s —— 本机空间数据没了, 演示数据不能凭空造" % space_path)
    sp = json.load(open(space_path, encoding="utf-8"))
    th = read_thresholds()
    sdir = os.path.join(SPACES, SPACE_ID)

    photos = sp.get("photos", [])
    tasks = sp.get("tasks", [])
    node = sp["nodes"][0]

    # ── 统计: 全部从 photos 数组数出来 ────────────────────────────────
    auto = [p for p in photos if p.get("state") == "auto_ok"]
    review = [p for p in photos if p.get("state") == "needs_review"]
    approved = [p for p in photos if p.get("state") == "approved"]
    rejected = [p for p in photos if p.get("state") == "rejected"]
    stats = {
        "total": len(photos),
        "auto": len(auto),
        "review": len(review),
        "approved": len(approved),
        "rejected": len(rejected),
        "tasksTotal": len(tasks),
        "tasksOpen": len([t for t in tasks if t.get("status") == "open"]),
        "tasksFilled": len([t for t in tasks if t.get("status") == "filled"]),
        "confMin": th["CONF_MIN"],
        "marginMin": th["MARGIN_MIN"],
    }

    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 全景: 4096 宽 2MB 太肉, 手机上等不起, 缩到 2048 ────────────────
    pano_src = os.path.join(sdir, node["panorama"])
    if not os.path.exists(pano_src):
        die("全景不在: %s" % pano_src)
    sips(pano_src, os.path.join(OUT_DIR, "pano.jpg"), long_edge=2048)

    def copy_photo(pid):
        for sub, name in (("thumbs", pid + ".jpg"), ("photos", pid + ".jpg")):
            src = os.path.join(sdir, sub, name)
            if os.path.exists(src):
                sips(src, os.path.join(OUT_DIR, "ph_" + pid + ".jpg"), long_edge=480)
                return "demo-assets/ph_%s.jpg" % pid
        return None

    def copy_task_img(t):
        rel = t.get("briefImage")
        if not rel:
            return None
        src = os.path.join(sdir, rel)
        if not os.path.exists(src):
            return None
        sips(src, os.path.join(OUT_DIR, "task_%s.jpg" % t["id"]), long_edge=640)
        return "demo-assets/task_%s.jpg" % t["id"]

    def pack_photo(p):
        return {
            "id": p["id"],
            "img": copy_photo(p["id"]),
            "yaw": round(float(p.get("yaw") or 0), 1),
            "confidence": p.get("confidence"),
            "margin": p.get("margin"),
            "state": p.get("state"),
            "reason": p.get("reason"),
            "contributor": clean_name(p.get("contributor")),
            "taskId": p.get("taskId"),
            "bearing": bearing_word(p.get("yaw") or 0),
        }

    all_photos = [pack_photo(p) for p in photos]

    # ── 第②幕主角: 一张【任务方位对得上】的自动入选照片 ────────────────
    # 对不上就别拿来演"照片飞回它的方位", 评委一算就露馅。
    hero = None
    for p in photos:
        if p.get("state") != "auto_ok":
            continue
        if clean_name(p.get("contributor")) == ANON:
            continue                      # 第②幕主角要有名有姓, 观众才认得出"某个人交的"
        t = next((x for x in tasks if x["id"] == p.get("taskId")), None)
        if t and yaw_in_range(p.get("yaw"), t.get("yawRange")):
            hero = {"photo": pack_photo(p), "task": {
                "id": t["id"], "title": t.get("title"), "brief": t.get("brief"),
                "yaw": t.get("yaw"), "yawRange": t.get("yawRange"),
                "bounty": t.get("bounty"), "img": copy_task_img(t),
            }}
            break
    if not hero:
        die("找不到一张方位落在任务区间内的自动入选照片 —— 数据不对, 别硬演")

    # ── 第④幕: 三个机位 (方位岔得越开越好看, 名字要能见人) ──────────────
    cands = [p for p in photos
             if p.get("state") == "auto_ok"
             and clean_name(p.get("contributor")) != ANON]
    cands.sort(key=lambda p: float(p.get("yaw") or 0))
    trio, used_yaw = [], []
    for p in cands:
        y = float(p.get("yaw") or 0)
        if all(min(abs(y - u), 360 - abs(y - u)) >= 40 for u in used_yaw):
            trio.append(pack_photo(p))
            used_yaw.append(y)
        if len(trio) == 3:
            break
    if len(trio) < 3:
        die("凑不出 3 个方位岔得开的机位, 第④幕演不了")

    # ── 第⑤幕: 通缉令墙 = 所有任务, 带真状态 ──────────────────────────
    wall = []
    for t in tasks:
        fills = [pack_photo(p) for p in photos if p.get("taskId") == t["id"]]
        wall.append({
            "id": t["id"], "type": t.get("type"), "title": t.get("title"),
            "brief": t.get("brief"), "yaw": t.get("yaw"), "yawRange": t.get("yawRange"),
            "bounty": t.get("bounty"), "status": t.get("status"),
            "filledBy": [clean_name(x) for x in (t.get("filledBy") or [])],
            "img": copy_task_img(t),
            "fills": fills,
            "bearing": bearing_word(t["yaw"]) if t.get("yaw") is not None else None,
        })

    data = {
        "generatedFrom": "server/spaces/%s/space.json" % SPACE_ID,
        "spaceId": SPACE_ID,
        "spaceTitle": sp.get("title"),
        "nodeName": node.get("name"),
        "nodeTime": node.get("time"),
        "pano": "demo-assets/pano.jpg",
        "stats": stats,
        "photos": all_photos,
        "hero": hero,
        "trio": trio,
        "wall": wall,
        "needsReview": [pack_photo(p) for p in review],
        # 交接书 §4 的标定盘: 这组数字来自 paircheck/阈值标定那一轮, 不是本空间数出来的,
        # 所以单独放一格并在页面上标明出处, 免得和上面的实时统计混成一锅。
        "calibration": {
            "note": "阈值标定实测(24 张标定集)",
            "total": 24, "correct": 23,
            "foreignTotal": 15, "foreignBlocked": 15,
            "confMin": th["CONF_MIN"], "marginMin": th["MARGIN_MIN"],
        },
    }

    # ── 出厂自检 ───────────────────────────────────────────────────
    # 页面在十几个地方直接对 photo.yaw 调 .toFixed()，靠的就是这里保证它一定是数。
    # 契约写在注释里没用, 在这儿卡住才有用: 数据不对就别生成, 别让页面到明早才炸。
    # (Codex 对审把这条报成 P0, 实测当前数据不可能触发, 但它指出的「契约只是口头的」是对的)
    def assert_num(where, val):
        if not isinstance(val, (int, float)):
            die("%s 的 yaw 不是数字 (%r) —— 页面会在 .toFixed() 上抛异常" % (where, val))

    for p in all_photos:
        assert_num("photos/" + str(p.get("id")), p.get("yaw"))
    for p in data["trio"] + data["needsReview"] + [hero["photo"]]:
        assert_num("演示主角/机位 " + str(p.get("id")), p.get("yaw"))
    for w in data["wall"]:
        for fpho in w["fills"]:
            assert_num("通缉令 %s 的填充照片 %s" % (w["id"], fpho.get("id")), fpho.get("yaw"))
    if len(data["trio"]) < 3:
        die("第④幕不足 3 个机位")
    if not os.path.exists(os.path.join(OUT_DIR, "pano.jpg")):
        die("全景没导出成功")

    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("// 由 tools/build_demo_data.py 从 %s 自动导出, 不要手改。\n" % data["generatedFrom"])
        f.write("// 重跑: python3 tools/build_demo_data.py\n")
        f.write("window.DEMO_DATA = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    n = len([x for x in os.listdir(OUT_DIR)])
    size = sum(os.path.getsize(os.path.join(OUT_DIR, x)) for x in os.listdir(OUT_DIR))
    print("✓ %s  (%d 张资产, %.1f MB)" % (OUT_JS, n, size / 1048576))
    print("  空间 %s · 照片 %d 张 = 自动 %d / 待看 %d / 已通过 %d / 已拒 %d"
          % (SPACE_ID, stats["total"], stats["auto"], stats["review"],
             stats["approved"], stats["rejected"]))
    print("  第②幕主角: %s (%s) → 任务 %s, 方位 %.1f°"
          % (hero["photo"]["id"], hero["photo"]["contributor"],
             hero["task"]["id"], hero["photo"]["yaw"]))
    print("  第④幕机位: " + ", ".join("%s %.0f°(%s)" % (p["id"], p["yaw"], p["contributor"])
                                        for p in trio))
    print("  通缉令墙: %d 个任务, %d 个还开着" % (stats["tasksTotal"], stats["tasksOpen"]))


if __name__ == "__main__":
    main()
