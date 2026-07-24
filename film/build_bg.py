#!/usr/bin/env python3
"""
film/build_bg.py -- 给【一键成片】准备背景飞行视频 + 镜头时间表。

这一层不做任何新数学,全部复用 server/film.py:
  plan_shots()  排镜头   render_film()  逐帧改 yaw 渲飞行 + 拼 mp4 + 写 shots.json

本文件只干一件事:决定"喂给 film.py 的节点长什么样"。有两套输入,用 --source 切:

  --source walk (默认)
      画面 = assets/walkdemo 的 4 张真实室内全景(Poly Haven CC0),
      照片 = 同一张全景切出来的 _j*.jpg 裁切图,方位取 film.WALK_CROP_POSE
             (那张表是像素回解出来的,不是编的,残差 0.019-0.161)。
      章节名/时刻/caption = tour.js 的婚礼剧本。
      >>> 这是交付用的那一版。说清楚:空间信息(yaw/pitch)是真的、逐像素可复核的;
          婚礼章节和 caption 是 demo 剧本,贴在 CC0 室内全景上。真实影石素材到位后
          换成 --source tour 即可,结构一模一样。

  --source tour
      完全吃 tour.js:画面 = assets/panos/*.jpg。
      技术上百分之百自洽,但那几张全景是 tools/fixtures.py 生成的标定图
      (彩色扇区 + 印着 000°/030° 的大字),放出来不像照片,只适合验数据链路。

跑法:
    .venv/bin/python film/build_bg.py                      # 默认 walk,720p
    .venv/bin/python film/build_bg.py --source tour
    .venv/bin/python film/build_bg.py --plan-only          # 只看排出来多长

产物:
    film/assets/flythrough.mp4   背景飞行视频(无声)
    film/assets/shots.json       镜头时间表,合成层照着贴照片和字幕
"""
import argparse
import json
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import film  # noqa: E402

FILM_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(FILM_DIR, "assets")

# 婚礼章节 -> 用哪张全景当这一章的空间。
# 挑的时候只看"像不像那个场合":门厅当新娘家、礼拜堂当仪式、宴会厅当宴席,
# 咖啡厅当出发前的等候。tour.js 里 chufa 那一节本来是车队,walkdemo 没有户外素材,
# 所以这一章的文案在下面单独换成了"等候"口径,免得画面和字幕对着干。
#
# 第五列 = 这一章有照片的方位:{裁切图编号: 文案}。编号 j 对应的方位角见
# film.WALK_CROP_POSE(j1=020° j2=060° j3=100° j4=145° j5=185° j6=225° j7=265° j8=305° j9=340°)。
#
# 四章的编号集合故意各不相同 —— 裁切图的方位表四张全景共用一份,四章要是都给满 9 张,
# 挑图算法(贪心最远点采样)会在四章挑出一模一样的 020°/100°/185°,四段镜头轨迹全同,
# 看着就不像"照片带着镜头走",反而像写死的脚本。真实场景里每个空间被拍的方向
# 本来就不一样,这里就照这个来。
#
# 文案按"方位角从小到大"的顺序读下来要合乎婚礼流程 —— 镜头是按方位单向扫过去的
# (film._order_sweep),所以画面顺序 = 方位顺序,不是这里的书写顺序。改文案后
# 跑一次 --plan-only 核对左边那列时间轴上的先后。
CHAPTERS = [
    # (tour.js 节点 id, 章节名, 时刻, walkdemo 场景 slug, {裁切图编号: 文案})
    ("jieqin", "接亲", "09:08", "entrance_hall", {
        1: "堵门红包", 2: "伴娘团合影", 4: "藏婚鞋",
        6: "敬茶改口", 7: "红包雨", 9: "伴娘拦门",
    }),
    # tour.js 里 chufa 那一节本来全是车队和路上,walkdemo 没有户外素材,
    # 所以这一章的文案换成"出门前等候"口径,免得画面和字幕对着干。
    ("chufa", "出发", "10:30", "comfy_cafe", {
        2: "喜糖分完了", 3: "出门前最后一张", 5: "长辈在门口",
        7: "回头看了一眼", 8: "帮着拎东西",
    }),
    ("yishi", "仪式", "12:18", "chapel_day", {
        1: "红毯入场", 3: "证婚致辞", 5: "交换戒指",
        6: "抛捧花", 9: "全场合影",
    }),
    ("yanxi", "宴席", "18:00", "ballroom", {
        2: "切蛋糕", 4: "挨桌敬酒", 5: "宾客碰杯",
        7: "父亲致辞", 8: "灯光秀", 9: "第一支舞",
    }),
]


def walk_wedding_nodes():
    """walkdemo 的真实全景 + 婚礼章节文案。"""
    nodes = []
    for nid, name, time_s, slug, texts in CHAPTERS:
        pano = os.path.join(film.WALK_DIR, f"{slug}.jpg")
        if not os.path.exists(pano):
            raise RuntimeError(f"全景不存在: {pano}")
        photos = []
        for j, caption in texts.items():
            src = os.path.join(film.WALK_DIR, f"{slug}_j{j}.jpg")
            if not os.path.exists(src):
                continue
            yaw, pitch = film.WALK_CROP_POSE[j]
            photos.append({
                "src": os.path.relpath(src, REPO_ROOT),
                "yaw": yaw,
                "pitch": pitch,
                # 方位是像素回解出来的,置信度按 film.py 那张表的口径记满;
                # 想现场复核就跑 python -m server.film --solve-walk
                "confidence": 1.0,
                "caption": caption,
            })
        nodes.append({
            "id": nid, "name": name, "sub": name, "time": time_s,
            "panorama": os.path.relpath(pano, REPO_ROOT),
            "panoramaPath": pano,
            "exitYaw": None,      # walkdemo 没有门的方位表,让 film.py 自己往前甩一点
            "photos": photos,
        })
    return nodes


def main():
    ap = argparse.ArgumentParser(description="一键成片:背景飞行视频")
    ap.add_argument("--source", choices=("walk", "tour"), default="walk")
    ap.add_argument("--out", default=ASSETS)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--per-node", type=int, default=3)
    ap.add_argument("--max-total", type=float, default=74.0)
    ap.add_argument("--crf", type=int, default=22)
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args()

    w, h = (int(x) for x in a.size.lower().split("x"))
    nodes = walk_wedding_nodes() if a.source == "walk" else film.demo_nodes()

    if a.plan_only:
        shots = film.plan_shots(nodes, fps=a.fps, per_node=a.per_node,
                                max_total_s=a.max_total)
        kinds = {}
        for s in shots:
            kinds[s["type"]] = kinds.get(s["type"], 0) + 1
        print(f"{len(shots)} 个镜头 / {shots[-1]['endS']}s / {kinds}")
        for s in shots:
            print(f"  {s['startS']:>6.2f}s {s['type']:<10} {s['nodeId']:<7} "
                  f"{s['fromYaw']:>6.1f}->{s['toYaw']:>6.1f}  {s.get('caption') or ''}")
        return

    os.makedirs(a.out, exist_ok=True)
    print(f"[build_bg] source={a.source} size={w}x{h} per_node={a.per_node}")
    summary = film.render_film(nodes, a.out, fps=a.fps, size=(w, h),
                               per_node=a.per_node, max_total_s=a.max_total,
                               crf=a.crf)
    # 单个镜头的分片留着没用(flythrough.mp4 已经拼好了),磁盘紧张,直接删
    shutil.rmtree(os.path.join(a.out, "shots"), ignore_errors=True)
    for s in json.load(open(os.path.join(a.out, "shots.json")))["shots"]:
        s.pop("clip", None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
