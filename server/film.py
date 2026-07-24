#!/usr/bin/env python3
"""
server/film.py -- 一键成片:镜头规划 + 全景飞行镜头渲染。

这不是照片幻灯片。我们知道每张照片在全景里的 yaw(水平方位角),所以镜头可以真的
"飞过去":在全景里平移到照片所在的那个方位 -> 照片在那儿浮现 -> 再飞向下一张 ->
走进下一个空间。谁都能做幻灯片,只有我们能做空间驱动的自动剪辑。

本文件只产出**背景飞行视频**(全景里的运镜)。照片浮现/字幕由合成层叠上去,
shots.json 里每个镜头都带了 photo/caption/startS,叠图的人照着时间轴贴即可。

三块:
  1. plan_shots()        -- 一串节点 -> 一条镜头清单(establish/fly/reveal/transition)
  2. render_shot_frames()-- 单个镜头 -> 一串 jpg 帧(复用 tools/slice.py 的投影数学)
  3. frames_to_video()   -- 帧序列 -> mp4(h264/yuv420p/crf20),编完就删帧

跑法:
    .venv/bin/python -m server.film --demo --out /tmp/psm_film
    .venv/bin/python -m server.film --demo --out /tmp/psm_short --nodes 2 --per-node 2
    .venv/bin/python -m server.film --selfcheck        # 和 tools/slice.py 对拍,验证投影没跑偏

零新依赖(numpy/Pillow/ffmpeg 都是现成的),不改 tools/ 下任何脚本。
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# 只用于 --selfcheck 对拍:证明本文件的快路径和全仓库共用的那把尺子是同一把
from tools.slice import equirect_to_perspective  # noqa: E402

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
TOUR_JS = os.path.join(REPO_ROOT, "tour.js")

# ---------------------------------------------------------------------------
# 运镜参数(改这一段就能调整片子的节奏和味道)
# ---------------------------------------------------------------------------

# 背景取 85 度视场,比照片本身的 70 度(tools/slice.py 的 FOV)宽一圈,
# 这样照片叠上来时四周还留着它被拍下的那个空间,而不是把空间挤没了。
FILM_FOV = 85.0

ESTABLISH_S = 3.4          # 进入一个空间的定场镜头
ESTABLISH_FIRST_S = 4.0    # 全片第一个定场,给观众多一点时间进入
ESTABLISH_SWEEP = 46.0     # 定场环视的角度跨度(慢)
ESTABLISH_LEAD = 11.0      # 定场结束时距离第一张照片还差这么多度,留给下一个 fly 起手
FLY_MIN_S, FLY_MAX_S = 1.2, 2.5   # 飞行时长按转角大小在这个区间里插值
REVEAL_S = 2.8             # 照片浮现:镜头几乎不动,留给照片和字幕
REVEAL_HERO_S = 3.2        # 每个空间的第一张照片多停一会儿
REVEAL_DRIFT = 1.8         # 浮现时的微弱漂移(度),别让画面死住
TRANSITION_S = 1.1         # 空间之间的切换
FADE_S = 0.36              # 切换处的黑场淡入淡出

# 呼吸感:每个镜头内 pitch 走一个完整的正弦周期(起止都回到 0,拼接处不会跳)
BREATH_DEG = {"establish": 1.4, "fly": 1.6, "reveal": 0.35, "transition": 1.2}

# 浮现时把背景压暗到这个亮度,照片叠上去才跳得出来(shots.json 里会记 bgDim,
# 合成层知道背景已经压过了,别再压第二次)
REVEAL_DIM = 0.72

MAX_TOTAL_S = 85.0         # 总片长上限,超了就自动少选几张照片
MIN_PER_NODE = 1
TRY_PER_NODE = (5, 4, 3, 2, 1)


# ---------------------------------------------------------------------------
# 角度与缓动
# ---------------------------------------------------------------------------

def shortest_delta(a, b):
    """从 a 转到 b 的最短弧(度),结果落在 (-180, 180]。

    0/360 环绕的坑就堵在这一行:从 350 度飞到 10 度是 +20 度,不是 -340 度。
    """
    return (b - a + 180.0) % 360.0 - 180.0


def circ_dist(a, b):
    """两个方位角之间的圆周距离(度,0..180)。"""
    return abs(shortest_delta(a, b))


def _ease_in_out(t):
    """三次缓入缓出:起步慢、中段快、落点稳。飞行镜头不能匀速,匀速像监控探头。"""
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def _ease_slow(t):
    """定场用的平滑步进:比 ease_in_out 更平,整段都慢悠悠的。"""
    return t * t * (3.0 - 2.0 * t)


def _ease_for(shot_type, t):
    if shot_type == "establish":
        return _ease_slow(t)
    if shot_type == "reveal":
        return t          # 浮现只有一点点漂移,线性就够,加缓动反而看得出来"停住了"
    return _ease_in_out(t)


# ---------------------------------------------------------------------------
# 1. 镜头脚本规划
# ---------------------------------------------------------------------------

def _pick_photos(photos, k):
    """从一个节点的照片里挑 k 张,要求:方位铺得开 + 置信度高。

    全挑同一个墙角的照片,镜头就基本不动了,那我们独有的空间信息就白瞎了。
    所以先按置信度选一张种子,之后每次选"离已选的都最远"的那张(贪心最远点采样)。
    """
    cand = [p for p in photos if p.get("yaw") is not None]
    if not cand:
        return []
    k = max(MIN_PER_NODE, min(k, len(cand)))

    seed = max(cand, key=lambda p: (p.get("confidence") or 0.0))
    chosen = [seed]
    rest = [p for p in cand if p is not seed]
    while len(chosen) < k and rest:
        best = max(
            rest,
            key=lambda p: (
                min(circ_dist(p["yaw"], c["yaw"]) for c in chosen),
                p.get("confidence") or 0.0,
            ),
        )
        chosen.append(best)
        rest = [p for p in rest if p is not best]
    return chosen


def _order_sweep(picked):
    """把选中的照片排成"一路扫过去"的顺序。

    做法:按 yaw 排好,找出圆周上最大的那段空白,从空白之后那张开始。
    这样相邻两张之间的转角都不大,整个节点就是一次干净的单向环视,
    而不是镜头在房间里来回横跳。
    """
    if len(picked) <= 2:
        return sorted(picked, key=lambda p: p["yaw"] % 360.0)
    ordered = sorted(picked, key=lambda p: p["yaw"] % 360.0)
    n = len(ordered)
    gaps = []
    for i in range(n):
        a = ordered[i]["yaw"] % 360.0
        b = ordered[(i + 1) % n]["yaw"] % 360.0
        gaps.append(((b - a) % 360.0, i))
    _, gi = max(gaps)          # 最大空白发生在 ordered[gi] -> ordered[gi+1] 之间
    start = (gi + 1) % n
    return ordered[start:] + ordered[:start]


def _fly_duration(deg):
    """转角越大飞得越久,但别超过 FLY_MAX_S,不然观众等得难受。"""
    frac = min(1.0, max(0.0, deg / 180.0))
    return FLY_MIN_S + frac * (FLY_MAX_S - FLY_MIN_S)


def _plan_with_k(nodes, fps, k):
    """按"每个节点挑 k 张照片"排一条完整镜头清单。"""
    shots = []
    cursor = 0  # 累计帧数,保证 shots.json 的时间轴和拼出来的视频逐帧对齐

    def push(shot, dur_s):
        nonlocal cursor
        nf = max(1, int(round(dur_s * fps)))
        shot["frames"] = nf
        shot["startFrame"] = cursor
        shot["startS"] = round(cursor / fps, 3)
        shot["durationS"] = round(nf / fps, 3)
        shot["endS"] = round((cursor + nf) / fps, 3)
        shot["fromYaw"] = round(shot["fromYaw"] % 360.0, 2)
        shot["toYaw"] = round(shot["toYaw"] % 360.0, 2)
        cursor += nf
        shots.append(shot)

    for ni, node in enumerate(nodes):
        picked = _order_sweep(_pick_photos(node.get("photos") or [], k))
        if not picked:
            continue
        nid = node.get("id") or f"node{ni + 1}"
        nname = node.get("name") or nid
        first_yaw = picked[0]["yaw"]

        # 定场:从第一张照片的"前面"一段慢慢环视过来,落点正好差 ESTABLISH_LEAD 度,
        # 于是下一个 fly 是很自然的接续,而不是硬切。
        push({
            "type": "establish",
            "nodeId": nid,
            "nodeName": nname,
            "nodeTime": node.get("time"),
            "fromYaw": first_yaw - ESTABLISH_SWEEP,
            "toYaw": first_yaw - ESTABLISH_LEAD,
            "fromPitch": 1.2,
            "toPitch": 0.0,
            "fadeInS": FADE_S,
            "fadeOutS": 0.0,
            "bgDim": 1.0,
            "caption": node.get("sub") or nname,
            "label": f"{node.get('time') or ''} {nname}".strip(),
        }, ESTABLISH_FIRST_S if ni == 0 else ESTABLISH_S)

        cur_yaw = first_yaw - ESTABLISH_LEAD
        cur_pitch = 0.0

        for pi, photo in enumerate(picked):
            pyaw = photo["yaw"]
            ppitch = float(photo.get("pitch") or 0.0)
            deg = circ_dist(cur_yaw, pyaw)

            # 飞:平移到照片所在的方位。photo 也挂在 fly 上,合成层可以提前预载图片。
            push({
                "type": "fly",
                "nodeId": nid,
                "nodeName": nname,
                "fromYaw": cur_yaw,
                "toYaw": pyaw,
                "fromPitch": cur_pitch,
                "toPitch": ppitch,
                "fadeInS": 0.0,
                "fadeOutS": 0.0,
                "bgDim": 1.0,
                "turnDeg": round(deg, 1),
                "photo": photo.get("src"),
                "caption": photo.get("caption"),
            }, _fly_duration(deg))

            # 浮现:停在这个方位上,只留一丝漂移。照片和字幕在这一段叠上来。
            push({
                "type": "reveal",
                "nodeId": nid,
                "nodeName": nname,
                "nodeTime": node.get("time"),
                "fromYaw": pyaw - REVEAL_DRIFT / 2.0,
                "toYaw": pyaw + REVEAL_DRIFT / 2.0,
                "fromPitch": ppitch,
                "toPitch": ppitch,
                "fadeInS": 0.0,
                "fadeOutS": 0.0,
                "bgDim": REVEAL_DIM,
                "photo": photo.get("src"),
                "photoYaw": round(pyaw % 360.0, 2),
                "photoPitch": ppitch,
                "confidence": photo.get("confidence"),
                "caption": photo.get("caption"),
                "label": f"{node.get('time') or ''} {nname}".strip(),
            }, REVEAL_HERO_S if pi == 0 else REVEAL_S)

            cur_yaw = pyaw + REVEAL_DRIFT / 2.0
            cur_pitch = ppitch

        # 切换:朝着通往下一个空间的那个方位甩过去,然后淡出黑场。
        # exitYaw 由调用方按 tour.js 的 links 填(哪个方向是门),没有就随便往前甩一点。
        is_last = ni == len(nodes) - 1
        exit_yaw = node.get("exitYaw")
        if exit_yaw is None:
            exit_yaw = cur_yaw + 35.0
        nxt = nodes[ni + 1] if not is_last else None
        push({
            "type": "transition",
            "nodeId": nid,
            "nodeName": nname,
            "fromYaw": cur_yaw,
            "toYaw": exit_yaw,
            "fromPitch": cur_pitch,
            "toPitch": 0.0,
            "fadeInS": 0.0,
            "fadeOutS": FADE_S,
            "bgDim": 1.0,
            "toNodeId": (nxt or {}).get("id"),
            "toNodeName": (nxt or {}).get("name"),
            "isOutro": is_last,
        }, TRANSITION_S)

    return shots


def plan_shots(nodes, fps=30, per_node=None, max_total_s=MAX_TOTAL_S):
    """节点列表 -> 镜头清单。

    nodes: [{id, name, time, panorama, photos:[{src, yaw, pitch, caption, confidence}], exitYaw?}]
    返回:  [{type, nodeId, fromYaw, toYaw, durationS, frames, startS, endS, photo?, caption?}, ...]

    每个节点挑几张照片是自动定的:从多到少试,取第一个不超过 max_total_s 的方案。
    宁可少放几张照片,也不能让片子拖到 90 秒以外——没人看得下去。
    """
    if per_node:
        return _plan_with_k(nodes, fps, per_node)

    fallback = None
    for k in TRY_PER_NODE:
        shots = _plan_with_k(nodes, fps, k)
        if not shots:
            continue
        fallback = shots
        if shots[-1]["endS"] <= max_total_s:
            return shots
    return fallback or []


# ---------------------------------------------------------------------------
# 2. 全景飞行渲染
# ---------------------------------------------------------------------------

_PANO_CACHE = {}   # 全景原图,一张 4096x2048 就是 24MB,只留最近两张
_GRID_CACHE = {}   # 采样网格,按 (fov, pitch量化, 输出尺寸, 全景尺寸) 缓存
_LUT_CACHE = {}    # 亮度缩放查表,避免每帧做浮点乘法

RENDER_STATS = {
    "frames": 0, "projectMs": 0.0, "encodeMs": 0.0,
    "gridBuilds": 0, "gridMs": 0.0,
}

PITCH_QUANT = 0.5  # pitch 量化到 0.5 度:肉眼看不出差别,但网格缓存能命中


def _load_pano(path):
    arr = _PANO_CACHE.get(path)
    if arr is None:
        with Image.open(path) as img:
            arr = np.asarray(img.convert("RGB"))
        if len(_PANO_CACHE) >= 2:
            _PANO_CACHE.pop(next(iter(_PANO_CACHE)))
        _PANO_CACHE[path] = arr
    return arr


def _build_grid(fov_deg, pitch_deg, out_w, out_h, ew, eh):
    """预先算好 yaw=0 时的采样网格。这是整个渲染能跑起来的关键。

    投影数学逐行照抄 tools/slice.py 的 equirect_to_perspective(同一套 yaw/pitch 约定),
    唯一的改动是把 yaw 固定成 0。因为:

        yaw 是绕竖轴的旋转,对 equirect 来说等价于"经度整体加一个常数",
        也就是采样列整体平移一个固定像素数,而采样行(纬度)完全不变。

    所以同一个镜头里只有 yaw 在变时,arctan2/arcsin 这些贵操作只需要算一次,
    每帧只剩一次加法 + 取模 + 取整。2700 帧才跑得完,不然真要跑到天亮。
    """
    t0 = time.time()
    fov = math.radians(fov_deg)
    phi = math.radians(pitch_deg)

    aspect = out_h / out_w
    w_len = math.tan(fov / 2.0)
    h_len = w_len * aspect

    xs = (2 * (np.arange(out_w) + 0.5) / out_w - 1) * w_len
    ys = (1 - 2 * (np.arange(out_h) + 0.5) / out_h) * h_len
    xv, yv = np.meshgrid(xs, ys)
    zv = np.ones_like(xv)

    norm = np.sqrt(xv ** 2 + yv ** 2 + zv ** 2)
    xv, yv, zv = xv / norm, yv / norm, zv / norm

    y1 = yv * math.cos(phi) + zv * math.sin(phi)
    z1 = -yv * math.sin(phi) + zv * math.cos(phi)
    x1 = xv

    # theta = 0,所以 x2/z2 就是 x1/z1
    lon = np.arctan2(x1, z1)
    lat = np.arcsin(np.clip(y1, -1.0, 1.0))

    src_x0 = (lon / (2 * math.pi)) * ew
    src_y = (0.5 - lat / math.pi) * eh
    src_y = np.clip(src_y, 0, eh - 1).astype(np.int64)

    # 展平成一维,并把行号预乘成扁平偏移,每帧只要加上列号就能一次 take 取完
    row_off = (src_y * ew).ravel()
    grid = (row_off, src_x0.ravel())

    RENDER_STATS["gridBuilds"] += 1
    RENDER_STATS["gridMs"] += (time.time() - t0) * 1000.0
    return grid


def _grid_for(fov_deg, pitch_deg, out_w, out_h, ew, eh):
    pq = round(pitch_deg / PITCH_QUANT) * PITCH_QUANT
    key = (round(fov_deg, 3), pq, out_w, out_h, ew, eh)
    grid = _GRID_CACHE.get(key)
    if grid is None:
        grid = _build_grid(fov_deg, pq, out_w, out_h, ew, eh)
        if len(_GRID_CACHE) >= 24:      # 一份网格约 11MB,别无限涨
            _GRID_CACHE.pop(next(iter(_GRID_CACHE)))
        _GRID_CACHE[key] = grid
    return grid


def project(pano, fov_deg, yaw_deg, pitch_deg, out_w, out_h):
    """全景 -> 指定朝向的透视图。走网格缓存的快路径,结果和 slice.py 一致。"""
    eh, ew = pano.shape[:2]
    row_off, src_x0 = _grid_for(fov_deg, pitch_deg, out_w, out_h, ew, eh)
    shift = (yaw_deg / 360.0) * ew
    src_x = np.mod(src_x0 + shift, ew).astype(np.int64)
    idx = row_off + src_x
    return pano.reshape(-1, 3).take(idx, axis=0).reshape(out_h, out_w, 3)


def _scale_lut(scale):
    """亮度缩放查表:uint8 直接查表比转 float 再乘快一个数量级。"""
    s = round(max(0.0, min(1.0, scale)), 3)
    lut = _LUT_CACHE.get(s)
    if lut is None:
        lut = np.clip(np.arange(256) * s + 0.5, 0, 255).astype(np.uint8)
        _LUT_CACHE[s] = lut
    return lut


def _brightness(shot, i, n, fps):
    """这一帧的整体亮度:浮现时的压暗 + 切换处的黑场,乘在一起。"""
    t = i / (n - 1) if n > 1 else 1.0
    scale = 1.0

    dim = float(shot.get("bgDim") or 1.0)
    if dim < 0.999:
        # 压暗不能是台阶,前 30% 渐入、后 20% 渐出,和前后镜头接得上
        ramp = min(1.0, t / 0.3, max(0.0, 1.0 - t) / 0.2)
        scale *= 1.0 - (1.0 - dim) * ramp

    fi = int(round(float(shot.get("fadeInS") or 0.0) * fps))
    if fi > 0 and i < fi:
        scale *= i / float(fi)
    fo = int(round(float(shot.get("fadeOutS") or 0.0) * fps))
    if fo > 0 and i >= n - fo:
        scale *= max(0.0, (n - 1 - i)) / float(fo)

    return scale


def render_shot_frames(pano_path, shot, out_dir, fps=30, size=(1280, 720),
                       fov_deg=FILM_FOV, quality=88, start_index=1):
    """把一个镜头渲成一串 jpg 帧,返回帧文件路径列表。

    yaw 走最短弧 + 缓动;pitch 在插值之上叠一个完整周期的正弦"呼吸"(起止都回到 0,
    所以镜头之间拼起来不会跳)。同一个镜头里 fov/尺寸不变,采样网格全靠缓存复用。
    """
    os.makedirs(out_dir, exist_ok=True)
    pano = _load_pano(pano_path)
    out_w, out_h = size

    n = int(shot.get("frames") or max(1, round(float(shot["durationS"]) * fps)))
    y0 = float(shot["fromYaw"])
    d_yaw = shortest_delta(y0, float(shot["toYaw"]))
    p0 = float(shot.get("fromPitch") or 0.0)
    p1 = float(shot.get("toPitch") or 0.0)
    breath = BREATH_DEG.get(shot.get("type"), 1.2)
    stype = shot.get("type") or "fly"

    paths = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 1.0
        e = _ease_for(stype, t)
        yaw = y0 + d_yaw * e
        pitch = p0 + (p1 - p0) * e + breath * math.sin(2.0 * math.pi * t)

        t0 = time.time()
        frame = project(pano, fov_deg, yaw, pitch, out_w, out_h)
        scale = _brightness(shot, i, n, fps)
        if scale < 0.999:
            frame = _scale_lut(scale)[frame]
        RENDER_STATS["projectMs"] += (time.time() - t0) * 1000.0

        dest = os.path.join(out_dir, f"{start_index + i:05d}.jpg")
        t1 = time.time()
        Image.fromarray(frame).save(dest, quality=quality)
        RENDER_STATS["encodeMs"] += (time.time() - t1) * 1000.0
        RENDER_STATS["frames"] += 1
        paths.append(dest)

    return paths


# ---------------------------------------------------------------------------
# 3. 帧序列 -> mp4
# ---------------------------------------------------------------------------

def frames_to_video(frame_dir, out_path, fps=30, crf=20, cleanup=True, pattern="%05d.jpg"):
    """ffmpeg 把帧序列编成 mp4(h264 / yuv420p / crf20),编完删帧(磁盘紧张)。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-framerate", str(fps),
        "-i", os.path.join(frame_dir, pattern),
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"ffmpeg 编码失败: {r.stderr[-800:]}")
    if cleanup:
        shutil.rmtree(frame_dir, ignore_errors=True)
    return out_path


def concat_videos(clip_paths, out_path, list_path=None):
    """把一堆同参数的 mp4 首尾接起来。用 concat demuxer + 流拷贝,不重编码。"""
    list_path = list_path or os.path.join(
        os.path.dirname(os.path.abspath(out_path)), "_concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write("file '%s'\n" % os.path.abspath(p).replace("'", r"'\''"))
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", "-movflags", "+faststart", out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    os.remove(list_path)
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"ffmpeg 拼接失败: {r.stderr[-800:]}")
    return out_path


def probe_duration(path):
    """读 mp4 真实时长(秒)。不许靠估算说"生成成功",一律以 ffprobe 为准。"""
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return round(float(r.stdout.strip()), 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 成片编排
# ---------------------------------------------------------------------------

def _pano_path(node):
    p = node.get("panoramaPath") or node.get("panorama") or ""
    return p if os.path.isabs(p) else os.path.join(REPO_ROOT, p)


def render_film(nodes, out_dir, fps=30, size=(1280, 720), per_node=None,
                max_total_s=MAX_TOTAL_S, fov_deg=FILM_FOV, keep_frames=False,
                dim_on_reveal=True, crf=20, verbose=True):
    """节点 -> shots.json + 每个镜头的 mp4 + 拼好的 flythrough.mp4。

    一个镜头渲完就立刻编码、立刻删帧,所以磁盘峰值只是一个镜头的帧(十几 MB),
    不会先摊 2700 张 jpg 出来。
    """
    os.makedirs(out_dir, exist_ok=True)
    clips_dir = os.path.join(out_dir, "shots")
    os.makedirs(clips_dir, exist_ok=True)

    shots = plan_shots(nodes, fps=fps, per_node=per_node, max_total_s=max_total_s)
    if not shots:
        raise RuntimeError("排不出任何镜头:节点里没有带 yaw 的照片")
    if not dim_on_reveal:
        for s in shots:
            s["bgDim"] = 1.0

    by_id = {}
    for i, nd in enumerate(nodes):
        by_id[nd.get("id") or f"node{i + 1}"] = nd

    for k in RENDER_STATS:
        RENDER_STATS[k] = 0 if isinstance(RENDER_STATS[k], int) else 0.0

    t_all = time.time()
    clips = []
    for si, shot in enumerate(shots):
        node = by_id.get(shot["nodeId"])
        pano = _pano_path(node)
        if not os.path.exists(pano):
            raise RuntimeError(f"全景图不存在: {pano}")

        frame_dir = os.path.join(out_dir, "_frames", f"{si + 1:03d}")
        t0 = time.time()
        render_shot_frames(pano, shot, frame_dir, fps=fps, size=size, fov_deg=fov_deg)
        clip = os.path.join(clips_dir, f"{si + 1:03d}_{shot['type']}_{shot['nodeId']}.mp4")
        frames_to_video(frame_dir, clip, fps=fps, crf=crf, cleanup=not keep_frames)
        dt = time.time() - t0

        shot["clip"] = os.path.relpath(clip, out_dir)
        clips.append(clip)
        if verbose:
            print(f"  [{si + 1:>2}/{len(shots)}] {shot['type']:<10} {shot['nodeId']:<8} "
                  f"{shot['fromYaw']:>6.1f}->{shot['toYaw']:>6.1f}  "
                  f"{shot['durationS']:>4.1f}s {shot['frames']:>3}帧  用时 {dt:>5.1f}s")

    fly = os.path.join(out_dir, "flythrough.mp4")
    concat_videos(clips, fly)
    shutil.rmtree(os.path.join(out_dir, "_frames"), ignore_errors=True)

    total_s = time.time() - t_all
    n_frames = RENDER_STATS["frames"] or 1
    summary = {
        "flythrough": fly,
        "flythroughDurationS": probe_duration(fly),
        "flythroughBytes": os.path.getsize(fly),
        "shotsJson": os.path.join(out_dir, "shots.json"),
        "shotCount": len(shots),
        "plannedDurationS": shots[-1]["endS"],
        "frames": n_frames,
        "fps": fps,
        "size": list(size),
        "fov": fov_deg,
        "msPerFrameProject": round(RENDER_STATS["projectMs"] / n_frames, 2),
        "msPerFrameJpeg": round(RENDER_STATS["encodeMs"] / n_frames, 2),
        "msPerFrameTotalWall": round(total_s * 1000.0 / n_frames, 2),
        "gridBuilds": RENDER_STATS["gridBuilds"],
        "gridMsTotal": round(RENDER_STATS["gridMs"], 1),
        "renderSecondsTotal": round(total_s, 1),
        "photoCount": sum(1 for s in shots if s["type"] == "reveal"),
        "nodeCount": len({s["nodeId"] for s in shots}),
    }

    doc = {
        "meta": {
            "generator": "server/film.py",
            "fps": fps, "width": size[0], "height": size[1], "fov": fov_deg,
            "durationS": shots[-1]["endS"],
            "note": "背景飞行视频;reveal 段已按 bgDim 压暗,合成层直接叠照片即可,别重复压暗",
        },
        "summary": {k: v for k, v in summary.items() if k != "shotsJson"},
        "shots": shots,
    }
    with open(summary["shotsJson"], "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    return summary


# ---------------------------------------------------------------------------
# demo 数据:直接吃 tour.js
# ---------------------------------------------------------------------------

def load_tour(path=TOUR_JS):
    """从 tour.js 里抠出 window.TOUR 的 JSON 部分。

    tour.js 是给浏览器用 <script> 加载的,不是 .json,但赋值右边就是标准 JSON,
    掐头(window.TOUR = )去尾(;)之后直接 json.loads。

    注意别用 find("window.TOUR"):文件顶部的中文注释里也提到了 window.TOUR,
    会一头扎进注释里。必须匹配"赋值"这个形状。
    """
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"window\.TOUR\s*=\s*\{", txt)
    if not m:
        raise RuntimeError(f"{path} 里找不到 window.TOUR = {{...}} 赋值")
    i = m.end() - 1
    j = txt.rindex("}")
    return json.loads(txt[i:j + 1])


def demo_nodes(limit=None):
    """tour.js -> 本模块要的节点结构,并把 links 里"通往下一站"的方位填成 exitYaw。"""
    tour = load_tour()
    nodes = tour.get("nodes") or []
    if limit:
        nodes = nodes[:limit]
    order = [n["id"] for n in nodes]
    links = {(l["from"], l["to"]): l.get("yaw") for l in (tour.get("links") or [])}

    out = []
    for i, nd in enumerate(nodes):
        exit_yaw = None
        if i + 1 < len(order):
            exit_yaw = links.get((order[i], order[i + 1]))
        out.append({
            "id": nd["id"],
            "name": nd.get("name"),
            "sub": nd.get("sub"),
            "time": nd.get("time"),
            "panorama": nd.get("panorama"),
            "panoramaPath": os.path.join(REPO_ROOT, nd.get("panorama") or ""),
            "exitYaw": exit_yaw,
            "photos": nd.get("photos") or [],
        })
    return out


# ---------------------------------------------------------------------------
# walkdemo:真实室内全景(Poly Haven CC0)
# ---------------------------------------------------------------------------

WALK_DIR = os.path.join(REPO_ROOT, "assets", "walkdemo")

# assets/walkdemo/<scene>_j1..j9.jpg 是从对应全景里切出来的裁切图,但没留下方位表。
# 这张表是用 solve_crop_pose() 逐张像素回解出来的(FOV 固定 70,和 tools/slice.py 一致),
# 四个场景解出来完全一致、归一化残差 0.019-0.161,所以直接固化下来,省得每次跑都重解。
# 想复核就跑:.venv/bin/python -m server.film --solve-walk
WALK_CROP_POSE = {
    1: (20.0, -8.0), 2: (60.0, 6.0), 3: (100.0, -3.0),
    4: (145.0, 10.0), 5: (185.0, 0.0), 6: (225.0, -12.0),
    7: (265.0, 7.0), 8: (305.0, -5.0), 9: (340.0, 4.0),
}

# 场景名照实写(Poly Haven 的 slug 是什么就是什么),不给它们编造婚礼剧情。
WALK_SCENES = [
    ("entrance_hall", "门厅"),
    ("comfy_cafe", "咖啡厅"),
    ("ballroom", "宴会厅"),
    ("chapel_day", "礼拜堂"),
]


def solve_crop_pose(pano, crop_path, fov_deg=70.0, coarse=(128, 96)):
    """回解一张裁切图是从全景的哪个方位切出来的。

    做法很土但很可靠:按候选 (yaw, pitch) 重新投影一遍,和裁切图比像素(先去均值,
    抵消曝光差),粗扫一遍再逐步精修。裁切图本来就是从这张全景切的,所以能对得很准。

    只用于准备 demo 数据(walkdemo 的裁切图没留方位表)。产品里照片的 yaw 是
    tools/match.py 用 CLIP 匹配出来的,不走这条路。

    返回 (归一化残差, yaw, pitch);残差越小越可信,>0.3 基本就是没匹配上。
    """
    w, h = coarse
    tgt = np.asarray(Image.open(crop_path).convert("RGB").resize((w, h), Image.BILINEAR))
    tgt = tgt.astype(np.float32)
    tgt -= tgt.mean()
    energy = max(float((tgt ** 2).mean()), 1e-6)

    def err(yaw, pitch):
        f = project(pano, fov_deg, yaw % 360.0, pitch, w, h).astype(np.float32)
        f -= f.mean()
        return float(np.mean((f - tgt) ** 2))

    best = min(((err(y, p), float(y), float(p))
                for y in np.arange(0, 360, 1.5) for p in (-12, -6, 0, 6, 12)))
    _, yaw, pitch = best
    for step in (2.0, 0.75, 0.25):
        best = min((err(yaw + dy, pitch + dp), (yaw + dy) % 360.0, pitch + dp)
                   for dy in (-step, 0.0, step) for dp in (-step * 2, 0.0, step * 2))
        _, yaw, pitch = best
    return best[0] / energy, yaw, pitch


def walk_nodes(limit=None, per_node=None, solve=False):
    """assets/walkdemo 的 4 个真实室内全景 -> 节点结构。

    照片就是 <scene>_j*.jpg 那些裁切图,方位取 WALK_CROP_POSE(或现场回解)。
    caption 只写方位,不编造"新郎敬酒"之类这些图里根本没有的内容。
    """
    scenes = WALK_SCENES[:limit] if limit else WALK_SCENES
    js = sorted(WALK_CROP_POSE)[:per_node] if per_node else sorted(WALK_CROP_POSE)

    nodes = []
    for slug, cn in scenes:
        pano = os.path.join(WALK_DIR, f"{slug}.jpg")
        photos = []
        for j in js:
            src = os.path.join(WALK_DIR, f"{slug}_j{j}.jpg")
            if not os.path.exists(src):
                continue
            if solve:
                resid, yaw, pitch = solve_crop_pose(_load_pano(pano), src)
                conf = round(max(0.0, 1.0 - resid), 4)
            else:
                yaw, pitch = WALK_CROP_POSE[j]
                conf, resid = 1.0, None
            photos.append({
                "src": os.path.relpath(src, REPO_ROOT),
                "yaw": yaw, "pitch": pitch, "confidence": conf,
                "by": "solved" if solve else "table",
                "residual": (round(resid, 4) if resid is not None else None),
                "caption": f"{cn} · 方位 {int(round(yaw)):03d}°",
            })
        nodes.append({
            "id": slug, "name": cn, "sub": cn, "time": None,
            "panorama": os.path.relpath(pano, REPO_ROOT),
            "panoramaPath": pano, "exitYaw": None, "photos": photos,
        })
    return nodes


# ---------------------------------------------------------------------------
# 自检:和 tools/slice.py 对拍
# ---------------------------------------------------------------------------

def selfcheck(pano_path=None, size=(640, 360), verbose=True):
    """本文件的快路径 vs tools/slice.py 的原始实现,逐像素比。

    两边数学等价,只差浮点舍入(快路径是先算 yaw=0 的经度再加常数),
    所以允许极少数落在整数边界上的像素差一列。差得多就是投影约定跑偏了,必须炸出来。
    """
    pano_path = pano_path or os.path.join(REPO_ROOT, "assets", "panos", "jieqin.jpg")
    pano = _load_pano(pano_path)
    w, h = size
    worst = 0.0
    for yaw, pitch in [(0, 0), (37.5, 0), (180, 0), (285.4, 0), (350, 7), (12, -10), (359.9, 2.0)]:
        ref = equirect_to_perspective(pano, FILM_FOV, yaw, pitch, w, h)
        fast = project(pano, FILM_FOV, yaw, pitch, w, h)
        diff = (ref.astype(np.int16) - fast.astype(np.int16))
        bad = float(np.mean(np.any(diff != 0, axis=2)))
        worst = max(worst, bad)
        if verbose:
            print(f"  yaw={yaw:>6} pitch={pitch:>5}  不同像素占比 {bad * 100:.4f}%  "
                  f"平均绝对差 {np.abs(diff).mean():.4f}")
    ok = worst < 0.01   # 允许千分之一量级的边界像素差异
    if verbose:
        print(f"  => {'通过' if ok else '不通过'}(最差 {worst * 100:.4f}%,阈值 1%)")
    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_size(s):
    w, h = s.lower().split("x")
    return (int(w), int(h))


def main():
    ap = argparse.ArgumentParser(description="空间记忆 一键成片:全景飞行镜头")
    ap.add_argument("--demo", action="store_true", help="用 tour.js 的婚礼旅程当输入")
    ap.add_argument("--demo-walk", action="store_true",
                    help="用 assets/walkdemo 的 4 个真实室内全景当输入(看画面用)")
    ap.add_argument("--solve-walk", action="store_true",
                    help="重新回解 walkdemo 裁切图的方位,复核 WALK_CROP_POSE 这张表")
    ap.add_argument("--out", default="/tmp/psm_film")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", type=_parse_size, default=(1280, 720))
    ap.add_argument("--fov", type=float, default=FILM_FOV)
    ap.add_argument("--nodes", type=int, default=None, help="只取前 N 个节点(短版验证用)")
    ap.add_argument("--per-node", type=int, default=None, help="每个节点固定挑几张照片")
    ap.add_argument("--max-total", type=float, default=MAX_TOTAL_S, help="总片长上限(秒)")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--keep-frames", action="store_true", help="保留中间帧(默认编完就删)")
    ap.add_argument("--no-dim", action="store_true", help="浮现时不压暗背景")
    ap.add_argument("--plan-only", action="store_true", help="只排镜头写 shots.json,不渲染")
    ap.add_argument("--selfcheck", action="store_true", help="和 tools/slice.py 对拍验证投影")
    args = ap.parse_args()

    if args.selfcheck:
        print("== 投影自检(server/film.py 快路径 vs tools/slice.py) ==")
        ok = selfcheck()
        sys.exit(0 if ok else 1)

    if args.solve_walk:
        print("== 回解 walkdemo 裁切图方位(FOV=70) ==")
        bad = 0
        for slug, cn in WALK_SCENES:
            pano = _load_pano(os.path.join(WALK_DIR, f"{slug}.jpg"))
            cells = []
            for j in sorted(WALK_CROP_POSE):
                resid, yaw, pitch = solve_crop_pose(pano, os.path.join(WALK_DIR, f"{slug}_j{j}.jpg"))
                ty, tp = WALK_CROP_POSE[j]
                off = abs(shortest_delta(ty, yaw))
                if off > 2.0 or resid > 0.3:
                    bad += 1
                cells.append(f"j{j}:{yaw:5.1f}/{pitch:+5.1f} 残差{resid:.3f} 差{off:.1f}°")
            print(f"  {slug:<14}", "  ".join(cells[:5]))
            print(f"  {'':<14}", "  ".join(cells[5:]))
        print(f"  => 与固化表不符的有 {bad} 张")
        sys.exit(0 if bad == 0 else 1)

    if not (args.demo or args.demo_walk):
        ap.error("要 --demo(tour.js)或 --demo-walk(walkdemo 真实全景);"
                 "编程接口是 plan_shots()/render_film(),给服务端调用")

    nodes = walk_nodes(limit=args.nodes) if args.demo_walk else demo_nodes(limit=args.nodes)
    print(f"== 输入:{len(nodes)} 个节点,{sum(len(n['photos']) for n in nodes)} 张照片 ==")

    if args.plan_only:
        shots = plan_shots(nodes, fps=args.fps, per_node=args.per_node,
                           max_total_s=args.max_total)
        os.makedirs(args.out, exist_ok=True)
        dest = os.path.join(args.out, "shots.json")
        with open(dest, "w", encoding="utf-8") as f:
            json.dump({"meta": {"fps": args.fps, "durationS": shots[-1]["endS"]},
                       "shots": shots}, f, ensure_ascii=False, indent=2)
        for s in shots:
            print(f"  {s['startS']:>6.2f}s {s['type']:<10} {s['nodeId']:<8} "
                  f"{s['fromYaw']:>6.1f}->{s['toYaw']:>6.1f}  {s['durationS']}s  "
                  f"{s.get('caption') or ''}")
        print(f"== 共 {len(shots)} 个镜头,总长 {shots[-1]['endS']}s -> {dest} ==")
        return

    print("== 排镜头 + 渲染 ==")
    summary = render_film(
        nodes, args.out, fps=args.fps, size=args.size, per_node=args.per_node,
        max_total_s=args.max_total, fov_deg=args.fov, keep_frames=args.keep_frames,
        dim_on_reveal=not args.no_dim, crf=args.crf,
    )
    print("== 完成 ==")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
