#!/usr/bin/env python3
"""
server/space.py -- 「空间记忆」闭环产品的数据层 + 全部 HTTP API。

和旧的 compose_server.py(一次性上传即合成)不同,这里是完整闭环:
    新人建空间 -> 传全景 -> 系统自动算出"哪个方位没照片"并发悬赏任务(gap)
    -> 新人自己写心愿任务(wish) -> 宾客扫码进 H5 传照片
    -> CLIP 定位 + 置信度分流(高的直接进空间, 低的进新人待审队列)
    -> 新人审核 -> 发布

本文件只提供一个 APIRouter, 不自己起服务器。整合方在 compose_server.py 里这样接:

    from server import space
    app.include_router(space.router)                       # 全部 /api/... 接口
    space.set_clip_model(_clip_state["model"])             # 复用已加载的 CLIP, 别加载两遍
    app.mount("/spaces", StaticFiles(directory=space.SPACES_DIR), name="spaces")
    # 注意: /spaces 挂载必须在 app.mount("/", ...) 之前, 否则根挂载会先吃掉路径。

数据落盘契约(字段名冻结, 见任务书):
    server/spaces/<sid>/space.json
    server/spaces/<sid>/nodes/<nid>/pano.jpg | depth.png | depth.json | crops.npz
    server/spaces/<sid>/photos/<pid>.jpg
    server/spaces/<sid>/thumbs/<pid>.jpg
    server/spaces/<sid>/tasks/<tid>.jpg          <- gap 任务的"通缉令"裁切图

两个核心函数(自检/整合方可以单独调):
    find_coverage_gaps(space, node_id, ...)  纯几何计算, 只算"圆环上哪几段没照片", 不落盘
    sync_gap_tasks(sid, space, node_id)      把上面算出的缺口变成真任务(切通缉令图 + 去重 + 限额)

零新依赖: 只用 numpy / Pillow / fastapi / sentence-transformers / 标准库。
不改动 tools/ 下任何脚本, 只 import 复用。
"""
import copy
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import numpy as np
from fastapi import APIRouter, Body, File, Form, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPACES_DIR = os.path.join(REPO_ROOT, "server", "spaces")
DAP_PYTHON = os.path.join(REPO_ROOT, ".venv-dap", "bin", "python")
DEPTH_SCRIPT = os.path.join(REPO_ROOT, "tools", "depth.py")
DEPTH_ASSET_DIR = os.path.join(REPO_ROOT, "assets", "depth")
PUBLIC_URL_FILE = os.path.join(REPO_ROOT, "server", "public_url.txt")
FFMPEG = "/opt/homebrew/bin/ffmpeg"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.slice import equirect_to_perspective, FOV, CROP_W, CROP_H, YAWS  # noqa: E402
from tools.match import match_one  # noqa: E402

# ---------------------------------------------------------------- 常量
SCHEMA = "psm-space/1"

# 置信度分流阈值: 两个判据【都】达标才自动入选, 差一个就进待审队列。
#
# ⚠️ 阈值是【在这条真实管线上】量出来的, 不是拍脑袋(2026-07-24, clip-ViT-B-32,
#   ballroom 全景的 12 张裁切 bank, 9 张本空间照片 vs 15 张外来照片):
#
#     ┌ 判据一 confidence(= match_one 插值后的 top-1 相似度)
#     │   本空间  0.8730 ~ 0.9544
#     │   外来    0.6116 ~ 0.8899   ← 两组【会重叠】, 单靠它挡不住外来照片
#     └ 判据二 margin(= top-1 相似度 减 全部裁切的平均相似度)
#         本空间  0.0423 ~ 0.1026
#         外来    0.0142 ~ 0.0528   ← 只有 1 张本空间照片掉进外来区间
#
#   为什么必须有 margin: confidence 是 CLIP 给【自己刚做的决定】打的分, 循环论证 ——
#   它只回答"我有多喜欢这个 yaw", 不回答"这张照片到底属不属于这个空间"。margin 问的是
#   "最佳匹配比平均水平突出多少": 外来照片跟哪个朝向都不太像, 于是 margin 塌下来。
#
#   按下面这组阈值实测 23/24: 外来照片入侵 0/15 全部拦下(这是唯一要命的失败模式),
#   代价是 1 张本空间照片(margin 0.0423)被推给新人确认 —— 错在安全的那一侧, 点一下就收下。
#   原契约值 0.45 实测会让 needs_review 永不触发, 外来照片不仅能进空间还能冒领悬赏任务。
CONF_MIN = float(os.environ.get("PSM_CONF_MIN", "0.82"))
MARGIN_MIN = float(os.environ.get("PSM_MARGIN_MIN", "0.055"))
BASE_POINTS = 10         # 每张入选照片的基础积分
GAP_BOUNTY = 50          # 系统自动发的空间任务悬赏
WISH_BOUNTY = 100        # 新人心愿任务默认悬赏
THUMB_LONG_EDGE = 480    # 缩略图长边

SELECTED_STATES = ("auto_ok", "approved")           # "已入选" = 真的出现在空间里
PHOTO_STATES = ("auto_ok", "needs_review", "approved", "rejected", "quarantined")

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# 以 0° 为正前方、顺时针递增(yaw 变大 = 往右转), 每 45° 一个方位词
DIRECTION_WORDS = ["正前方", "右前方", "右侧", "右后方", "正后方", "左后方", "左侧", "左前方"]

router = APIRouter(prefix="/api")

# space.json 读写全局锁。重活(CLIP 编码 / DAP 深度)一律放在锁外面跑,
# 锁里只做"读 json -> 改几个字段 -> 写回", 毫秒级, 不会把并发上传卡死。
_LOCK = threading.RLock()

_clip_state = {}    # {"model": SentenceTransformer}, 由 set_clip_model 注入或懒加载
_model_lock = threading.Lock()    # 懒加载 CLIP 的锁, 见 get_clip_model
_encode_lock = threading.Lock()   # CLIP 推理串行化的锁, 见 clip_encode ⚠️别去掉
_crop_cache = {}    # {(sid, nid): (embs, yaws)} 全景裁切图的 CLIP 编码, 别每张照片重切 12 次


# ================================================================ CLIP 模型
def set_clip_model(model):
    """让 compose_server 把已经加载好的 CLIP 注入进来, 避免重复加载(一次约 2-5 秒)。"""
    _clip_state["model"] = model


def get_clip_model():
    """拿模型; 没被注入过就自己懒加载一次(独立跑 selftest 时走这条路)。

    ⚠️ 必须加锁: 婚礼现场是"一堆宾客同时传照片", 没锁的话每个线程都会各加载一份模型
    —— 实测 4 线程并发时真的加载了 4 份(各 13.7s), 然后进程直接挂掉。
    双重检查: 锁外面先看一眼, 命中就不进锁, 热路径不付锁的代价。
    """
    if "model" not in _clip_state:
        with _model_lock:
            if "model" not in _clip_state:
                from sentence_transformers import SentenceTransformer
                t0 = time.time()
                print("== [space] 加载 CLIP (clip-ViT-B-32) ==", flush=True)
                _clip_state["model"] = SentenceTransformer("clip-ViT-B-32")
                print(f"   CLIP 就绪, 耗时 {time.time()-t0:.1f}s", flush=True)
    return _clip_state["model"]


def clip_encode(images, batch_size=32):
    """全模块唯一的 CLIP 推理入口 —— 必须串行。

    🚨 别把这个锁去掉, 也别绕过这个函数直接调 model.encode:
       PyTorch 的 MPS 后端不是线程安全的。实测(2026-07-24, 本机 M 芯片)4 个线程同时调
       model.encode(), 进程直接被 SIGSEGV 打死(退出码 139), 连异常都抛不出来 ——
       也就是说婚礼现场两个宾客同时按下上传, 服务器就没了。
       串行化的代价很小: 重活(全景切 12 张图并编码)已经被 crop 缓存吃掉了,
       这里每次只编码宾客那几张照片, 排队等一下完全可以接受。
    """
    model = get_clip_model()
    with _encode_lock:
        return model.encode(
            images, batch_size=batch_size, convert_to_numpy=True, normalize_embeddings=True,
        )


# ================================================================ 存储层
def space_dir(sid):
    return os.path.join(SPACES_DIR, sid)


def space_json_path(sid):
    return os.path.join(space_dir(sid), "space.json")


def _next_id(prefix, *pools):
    """简单自增 id: s1/s2、n1/n2、p1/p2、t1/t2。pools 里可以塞多个来源(json 里的 id + 磁盘上的文件名),
    取所有来源的最大编号 +1, 这样即使某一边缺了也不会撞号。"""
    biggest = 0
    for pool in pools:
        for raw in pool:
            s = str(raw)
            if s.startswith(prefix) and s[len(prefix):].isdigit():
                biggest = max(biggest, int(s[len(prefix):]))
    return f"{prefix}{biggest + 1}"


def _listdir(path):
    return os.listdir(path) if os.path.isdir(path) else []


def load_space(sid):
    """读 space.json。调用方自己负责加锁(或者用 space_txn)。"""
    path = space_json_path(sid)
    if not os.path.exists(path):
        raise FileNotFoundError(f"空间 {sid} 不存在")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_space(sid, space):
    """先写临时文件再 os.replace, 防止写一半断电/崩溃把 space.json 写坏。"""
    path = space_json_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(space, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class space_txn:
    """一次 space.json 的读-改-写事务:

        with space_txn(sid) as space:
            space["tasks"].append(...)      # 退出 with 时自动落盘

    出异常就不写回。锁是可重入的, 所以事务里再调用别的也用 space_txn 的函数不会自锁。
    """

    def __init__(self, sid, write=True):
        self.sid = sid
        self.write = write
        self.space = None

    def __enter__(self):
        _LOCK.acquire()
        try:
            self.space = load_space(self.sid)
        except Exception:
            _LOCK.release()
            raise
        return self.space

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None and self.write:
                save_space(self.sid, self.space)
        finally:
            _LOCK.release()
        return False


def create_space(title, couple):
    """建一个新空间, 返回 sid。目录骨架一次建齐, 后面各处就不用到处 makedirs 了。"""
    with _LOCK:
        os.makedirs(SPACES_DIR, exist_ok=True)
        sid = _next_id("s", _listdir(SPACES_DIR))
        d = space_dir(sid)
        for sub in ("", "nodes", "photos", "thumbs", "tasks"):
            os.makedirs(os.path.join(d, sub), exist_ok=True)
        space = {
            "schema": SCHEMA,
            "id": sid,
            "title": (title or "").strip() or "我们的空间",
            "couple": (couple or "").strip(),
            "createdAt": time.time(),
            "published": False,
            "nodes": [],
            "tasks": [],
            "photos": [],
            "contributors": [],
        }
        save_space(sid, space)
        return sid


def list_spaces():
    with _LOCK:
        out = []
        for sid in sorted(_listdir(SPACES_DIR), key=lambda s: (len(s), s)):
            if not os.path.exists(space_json_path(sid)):
                continue
            try:
                sp = load_space(sid)
            except Exception:
                continue
            out.append({
                "id": sp["id"],
                "title": sp.get("title", ""),
                "couple": sp.get("couple", ""),
                "photoCount": len(sp.get("photos", [])),
                "taskCount": sum(1 for t in sp.get("tasks", []) if t.get("status") == "open"),
            })
        return out


# ================================================================ 图片小工具
def guess_ext(filename, content_type):
    """来源: compose_server.py 同名函数(复制而非 import, 避免两个模块循环依赖)。"""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext:
        return ext
    if content_type == "image/png":
        return ".png"
    if content_type and content_type.startswith("video/"):
        return ".mp4"
    return ".jpg"


def is_video(filename, content_type):
    """来源: compose_server.py 同名函数。"""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in VIDEO_EXTS:
        return True
    if content_type and content_type.startswith("video/"):
        return True
    return False


def save_panorama(raw_bytes, filename, content_type, dest_dir):
    """落盘 + 标准化成 dest_dir/pano.jpg。视频抽第 1 帧, 图片重编码成 jpg。
    来源: compose_server.py 的 save_panorama(), 逻辑照搬, 只把输出目录参数化。"""
    os.makedirs(dest_dir, exist_ok=True)
    ext = guess_ext(filename, content_type)
    raw_path = os.path.join(dest_dir, "raw_panorama" + ext)
    with open(raw_path, "wb") as f:
        f.write(raw_bytes)

    pano_path = os.path.join(dest_dir, "pano.jpg")
    if is_video(filename, content_type):
        cmd = [FFMPEG, "-y", "-i", raw_path, "-frames:v", "1", "-q:v", "2", pano_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(pano_path):
            raise RuntimeError(f"ffmpeg 抽帧失败: {r.stderr[-800:]}")
    else:
        Image.open(raw_path).convert("RGB").save(pano_path, quality=92)
    os.remove(raw_path)
    return pano_path


def save_photo_and_thumb(raw_bytes, dest_path, thumb_path):
    """原图统一重编码成 jpg(挡住奇怪格式/EXIF 方向问题), 顺手出一张长边 480 的缩略图。"""
    with open(dest_path, "wb") as f:
        f.write(raw_bytes)
    img = Image.open(dest_path).convert("RGB")
    img.save(dest_path, quality=90)
    thumb = img.copy()
    thumb.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE))
    thumb.save(thumb_path, quality=85)


def run_depth(pano_path, out_dir, tag):
    """subprocess 调 DAP 深度模型, 输出挪进 out_dir/depth.png + depth.json。
    来源: compose_server.py 的 run_depth()。
    ⚠️ depth.py 固定把输出写到 assets/depth/<输入 basename>.*, 所以这里必须
    先把 pano 复制成一个带 id 的临时输入名, 跑完把结果搬走, 再把中间产物清干净,
    不然多空间/多节点会互相覆盖, 还会把共享目录塞满。
    返回 (elapsed_s, stdout_tail)。
    """
    t0 = time.time()
    tmp_name = f"_dap_in_{tag}"
    tmp_input = os.path.join(out_dir, tmp_name + ".jpg")
    shutil.copy(pano_path, tmp_input)

    env = dict(os.environ)
    env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

    try:
        r = subprocess.run(
            [DAP_PYTHON, DEPTH_SCRIPT, tmp_input],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=900,
        )
        if r.returncode != 0:
            raise RuntimeError(f"depth.py 退出码 {r.returncode}: {r.stderr[-1500:]}")

        src_png = os.path.join(DEPTH_ASSET_DIR, tmp_name + ".png")
        src_json = os.path.join(DEPTH_ASSET_DIR, tmp_name + ".json")
        if not (os.path.exists(src_png) and os.path.exists(src_json)):
            raise RuntimeError(f"depth.py 跑完但没找到输出文件: {src_png}")

        shutil.move(src_png, os.path.join(out_dir, "depth.png"))
        shutil.move(src_json, os.path.join(out_dir, "depth.json"))
        stdout_tail = r.stdout[-1500:]
    finally:
        if os.path.exists(tmp_input):
            os.remove(tmp_input)
        # 兜底清理: 就算中途炸了也别把中间产物留在共享目录里
        for p in (os.path.join(DEPTH_ASSET_DIR, tmp_name + ".png"),
                  os.path.join(DEPTH_ASSET_DIR, tmp_name + ".json")):
            if os.path.exists(p):
                os.remove(p)

    return time.time() - t0, stdout_tail


# ================================================================ 角度小工具
def yaw_to_direction(yaw):
    """把 yaw 换算成人话方位。0° = 正前方, 顺时针(yaw 变大 = 往右转), 每 45° 一档。"""
    idx = int(((float(yaw) % 360.0) + 22.5) // 45) % 8
    return DIRECTION_WORDS[idx]


def _arc_mask(start, end):
    """把圆环区间 [start, end](允许跨 0/360 环绕)画成 360 格的布尔掩码。"""
    mask = np.zeros(360, dtype=bool)
    s = int(round(start)) % 360
    e = int(round(end)) % 360
    width = (e - s) % 360 + 1
    mask[(np.arange(s, s + width)) % 360] = True
    return mask


def yaw_in_range(yaw, rng):
    """yaw 是否落在 [start, end] 里, 正确处理跨 0/360 的区间(比如 [350, 30])。"""
    if not rng or len(rng) != 2:
        return False
    s, e = float(rng[0]) % 360, float(rng[1]) % 360
    y = float(yaw) % 360
    if s <= e:
        return s <= y <= e
    return y >= s or y <= e     # 跨 0 度的情况


def _ranges_overlap(a, b):
    """两个圆环区间是否有重叠。直接用 360 格掩码算, 环绕情况天然正确, 不用分类讨论。"""
    if not a or not b:
        return False
    return bool((_arc_mask(a[0], a[1]) & _arc_mask(b[0], b[1])).any())


# ================================================================ 覆盖盲区算法
def find_coverage_gaps(space, node_id, half_width_deg=20.0, min_gap_deg=40.0, max_tasks=3):
    """算出这个节点的全景圆环上,哪几段方位还没有照片覆盖 —— 这是"系统指挥人拍照"的源头。

    做法:
      1. 取该节点下所有【已入选】(auto_ok / approved)照片的 yaw;
      2. 在 0~360 的圆环上, 每张照片覆盖 [yaw-half_width, yaw+half_width](跨 0/360 自动环绕);
      3. 找出连续未覆盖、且宽度 >= min_gap_deg 的区间;
      4. 按宽度从大到小取前 max_tasks 个。

    纯计算, 不落盘不切图 —— 切"通缉令"图、去重、写进 space["tasks"] 是 sync_gap_tasks 干的。

    返回 [{"start": int, "end": int, "center": int, "width": int, "empty": bool}, ...]
      start/end 是区间两端(闭区间, 可能 start > end 表示跨 0 度), center 是中点 yaw。
      empty=True 表示"这个节点一张照片都没有"这种特殊情况。
    """
    yaws = [
        float(p["yaw"]) for p in space.get("photos", [])
        if p.get("nodeId") == node_id
        and p.get("state") in SELECTED_STATES
        and p.get("yaw") is not None
    ]

    # 零照片: 整圈都是空的。这时候不该只发一个 360° 的巨型任务(没法指挥人往哪拍),
    # 而是均匀撒 3 个方向, 让第一批宾客把骨架先撑起来。
    # 区间取 [c-60, c+59] 而不是 [c-60, c+60]: 三段刚好铺满一圈且互不重叠,
    # 否则它们会在边界上互相判定成"已经有任务盯着了"而被去重掉。
    if not yaws:
        return [
            {"start": (c - 60) % 360, "end": (c + 59) % 360, "center": c, "width": 120, "empty": True}
            for c in (0, 120, 240)
        ][:max_tasks]

    hw = int(round(half_width_deg))
    covered = np.zeros(360, dtype=bool)
    for y in yaws:
        c = int(round(y)) % 360
        covered[(np.arange(c - hw, c + hw + 1)) % 360] = True

    if covered.all():
        return []   # 一圈全被覆盖, 没缺口

    # 从一个"已覆盖"的格子开始绕圈走, 这样跨 0/360 的缺口会被自然地当成一段连续区间收进来,
    # 不会被切成头尾两段。
    start_idx = int(np.argmax(covered))
    gaps = []
    cur = None
    for k in range(360):
        d = (start_idx + k) % 360
        if not covered[d]:
            if cur is None:
                cur = [d, d]
            else:
                cur[1] = d
        elif cur is not None:
            gaps.append(cur)
            cur = None
    if cur is not None:
        gaps.append(cur)

    out = []
    for s, e in gaps:
        width = (e - s) % 360 + 1
        if width < min_gap_deg:
            continue
        center = int(round(s + (width - 1) / 2.0)) % 360
        out.append({"start": s, "end": e, "center": center, "width": width, "empty": False})

    out.sort(key=lambda g: g["width"], reverse=True)
    return out[:max_tasks]


def _gap_brief(center, empty):
    """gap 任务的人话文案。用方位词而不是角度 —— 宾客不会看着 210° 去转身。"""
    d = yaw_to_direction(center)
    if empty:
        return f"这个空间还没有任何照片,站在原地朝{d}先拍一张,把这里撑起来"
    return f"站在原地转向{d},拍那个方向"


def _slice_brief_image(pano_path, yaw, out_path):
    """从全景里按指定方位切一张透视图当"通缉令"—— 宾客一眼就知道要拍哪儿。
    参数和 tools/slice.py 建 crop 时完全一致(FOV=70, pitch=0, 800x600), 一把尺子。"""
    pano_np = np.asarray(Image.open(pano_path).convert("RGB"))
    persp = equirect_to_perspective(
        pano_np, fov_deg=FOV, yaw_deg=float(yaw), pitch_deg=0, out_w=CROP_W, out_h=CROP_H,
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    Image.fromarray(persp).save(out_path, quality=90)
    return out_path


def sync_gap_tasks(sid, space, node_id, half_width_deg=20.0, min_gap_deg=40.0, max_tasks=3):
    """把 find_coverage_gaps 算出的缺口变成真的 gap 任务(切通缉令图 + 落进 space["tasks"])。

    三条约束:
      - 一个节点上同时最多 max_tasks 个 open 的 gap 任务;
      - 已经存在覆盖同一区间的 open 任务, 不重复发;
      - 覆盖率变化后调用即可(传全景后 / 上传后 / 审核后), 幂等。

    直接改传进来的 space(不落盘), 调用方负责 save。返回新建的任务列表。
    """
    node = next((n for n in space.get("nodes", []) if n["id"] == node_id), None)
    if node is None:
        return []

    open_gaps = [
        t for t in space.get("tasks", [])
        if t.get("nodeId") == node_id and t.get("type") == "gap" and t.get("status") == "open"
    ]
    # 空间从"一张照片都没有"变成有照片之后, 第一批任务的文案就过期了(还在喊"这个空间还没有
    # 任何照片")。顺手刷成正常的方位文案, 别让宾客看到自相矛盾的话。
    has_photos = any(
        p.get("nodeId") == node_id and p.get("state") in SELECTED_STATES
        for p in space.get("photos", [])
    )
    if has_photos:
        for t in space.get("tasks", []):
            # 已经 filled 的也要刷: 任务列表上并排摆着 5 张照片和一句"还没有任何照片"太穿帮了
            if (t.get("nodeId") == node_id and t.get("type") == "gap"
                    and t.get("brief", "").startswith("这个空间还没有任何照片")):
                t["brief"] = _gap_brief(t.get("yaw") or 0, False)

    room = max_tasks - len(open_gaps)
    if room <= 0:
        return []

    gaps = find_coverage_gaps(space, node_id, half_width_deg, min_gap_deg, max_tasks)
    pano_path = os.path.join(space_dir(sid), node["panorama"].replace("/", os.sep))

    created = []
    for gap in gaps:
        if room <= 0:
            break
        rng = [gap["start"], gap["end"]]
        # 去重: 已经有 open 任务盯着这一片了, 别再发一条
        if any(_ranges_overlap(rng, t.get("yawRange")) for t in open_gaps):
            continue

        tid = _next_id(
            "t",
            [t["id"] for t in space.get("tasks", [])],
            [os.path.splitext(f)[0] for f in _listdir(os.path.join(space_dir(sid), "tasks"))],
        )
        brief = _gap_brief(gap["center"], gap["empty"])
        brief_rel = f"tasks/{tid}.jpg"
        try:
            _slice_brief_image(pano_path, gap["center"], os.path.join(space_dir(sid), brief_rel))
        except Exception as e:
            # 切图失败不该阻断任务本身(宾客还能靠文字方位去拍), 但要把原因打出来
            print(f"== [space {sid}] 通缉令切图失败 {tid}: {e} ==", flush=True)
            brief_rel = None

        task = {
            "id": tid,
            "nodeId": node_id,
            "type": "gap",
            "title": "缺这个角度",
            "brief": brief,
            "yaw": gap["center"],
            "yawRange": rng,
            "briefImage": brief_rel,
            "bounty": GAP_BOUNTY,
            "status": "open",
            "filledBy": [],
            "createdBy": "system",
            "createdAt": time.time(),
        }
        space["tasks"].append(task)
        open_gaps.append(task)
        created.append(task)
        room -= 1

    return created


# ================================================================ CLIP 定位
def _node_crop_bank(sid, node):
    """拿这个节点全景的 12 个方向裁切图的 CLIP 编码。

    性能关键: 全景切 12 张 + 编码大约要 1 秒多, 但它只跟全景有关、跟上传的照片无关,
    所以按节点缓存(内存 + 磁盘 nodes/<nid>/crops.npz), 后面每张宾客照片只需编码它自己。
    """
    key = (sid, node["id"])
    if key in _crop_cache:
        return _crop_cache[key]

    node_dir = os.path.join(space_dir(sid), "nodes", node["id"])
    npz_path = os.path.join(node_dir, "crops.npz")
    if os.path.exists(npz_path):
        data = np.load(npz_path, allow_pickle=False)
        bank = (data["embeddings"], data["yaws"].astype(int))
        _crop_cache[key] = bank
        return bank

    pano_path = os.path.join(space_dir(sid), node["panorama"].replace("/", os.sep))
    pano_np = np.asarray(Image.open(pano_path).convert("RGB"))
    crops = [
        Image.fromarray(equirect_to_perspective(
            pano_np, fov_deg=FOV, yaw_deg=yaw, pitch_deg=0, out_w=CROP_W, out_h=CROP_H,
        ))
        for yaw in YAWS
    ]
    embs = clip_encode(crops, batch_size=12)
    yaws = np.array(list(YAWS), dtype=np.int32)

    os.makedirs(node_dir, exist_ok=True)
    np.savez(npz_path, embeddings=embs, yaws=yaws)
    bank = (embs, yaws.astype(int))
    _crop_cache[key] = bank
    return bank


def place_photos(sid, space, photo_paths, node_id=None):
    """CLIP 定位: 每张照片编码一次, 和【所有节点】的裁切图一起比, 相似度最高的那张裁切
    决定了照片属于哪个节点、朝哪个 yaw(挑选逻辑复用 tools/match.py 的 match_one)。
    node_id 不为空就只跟那个节点比(前端明确指定了在哪儿拍的)。

    返回 [{nodeId, yaw, confidence, sim, margin}, ...], 与 photo_paths 一一对应。
    margin = 最佳相似度 减去 所有裁切的平均相似度, 用来判"这张到底属不属于这个空间"
    (见文件顶部 CONF_MIN/MARGIN_MIN 的实测数据注释)。
    """
    nodes = [n for n in space.get("nodes", []) if node_id is None or n["id"] == node_id]
    if not nodes:
        raise RuntimeError("这个空间还没有全景节点,请新人先传一张全景")

    bank_embs, bank_nodes, bank_yaws = [], [], []
    for n in nodes:
        embs, yaws = _node_crop_bank(sid, n)
        bank_embs.append(embs)
        bank_nodes.extend([n["id"]] * len(yaws))
        bank_yaws.extend(list(yaws))
    bank_embs = np.concatenate(bank_embs, axis=0)
    bank_nodes = np.array(bank_nodes)
    bank_yaws = np.array(bank_yaws, dtype=np.int32)

    imgs = [Image.open(p).convert("RGB") for p in photo_paths]
    photo_embs = clip_encode(imgs, batch_size=32)

    results = []
    for emb in photo_embs:
        sims = bank_embs @ emb
        nid, yaw, confidence, sim0 = match_one(sims, bank_nodes, bank_yaws)
        # margin 拿 sim0(真实的 top-1)减平均, 不用 confidence ——
        # confidence 是 match_one 插值后的产物, 和 sims 不在同一个尺度上比才有意义。
        margin = float(sim0) - float(np.mean(sims))
        results.append({
            "nodeId": str(nid),
            "yaw": round(float(yaw), 1),
            "confidence": round(float(confidence), 4),
            "sim": round(float(sim0), 4),
            "margin": round(margin, 4),
        })
    return results


# ================================================================ 任务 / 积分
def _find_task(space, task_id):
    return next((t for t in space.get("tasks", []) if t["id"] == task_id), None)


def apply_task_fill(space, photo):
    """照片真进空间之后, 判定它完成了哪个任务。返回被填上的 task id, 没有就 None。

    只有【已入选】的照片才算数 —— 待审的照片先不动任务状态, 等新人 approve 了再算,
    不然一张机器都拿不准的照片就能把悬赏关掉, 任务系统就废了。
    """
    if photo.get("state") not in SELECTED_STATES:
        return None

    task = _find_task(space, photo["taskId"]) if photo.get("taskId") else None

    # 没指定 taskId 就自动判定: 照片 yaw 落进某个 open 的 gap 任务的 yawRange 里
    if task is None and photo.get("yaw") is not None:
        for t in space.get("tasks", []):
            if (t.get("type") == "gap" and t.get("status") == "open"
                    and t.get("nodeId") == photo.get("nodeId")
                    and yaw_in_range(photo["yaw"], t.get("yawRange"))):
                task = t
                break
    if task is None:
        return None

    photo["taskId"] = task["id"]
    who = photo.get("contributor") or "匿名宾客"
    if who not in task["filledBy"]:
        task["filledBy"].append(who)
    if task["status"] == "open":
        task["status"] = "filled"
    return task["id"]


def recompute_contributors(space):
    """整表重算贡献榜, 而不是到处 +=。

    这样"拒了又通过""同一张照片被处理两次"都不会把积分算重 —— 积分永远等于
    当前数据的函数。规则: 每张入选照片 BASE_POINTS 分; 完成任务的人额外拿一次该任务 bounty。
    """
    tally = {}

    def bump(name, photos=0, points=0):
        rec = tally.setdefault(name, {"name": name, "photos": 0, "points": 0})
        rec["photos"] += photos
        rec["points"] += points

    for p in space.get("photos", []):
        if p.get("state") in SELECTED_STATES:
            bump(p.get("contributor") or "匿名宾客", photos=1, points=BASE_POINTS)

    for t in space.get("tasks", []):
        if t.get("status") in ("filled", "closed"):
            for who in t.get("filledBy", []):
                bump(who, points=int(t.get("bounty") or 0))

    space["contributors"] = sorted(
        tally.values(), key=lambda c: (-c["points"], -c["photos"], c["name"])
    )
    return space["contributors"]


def create_wish_task(sid, title, brief, bounty=None):
    """新人自己写的心愿任务: 没有 yaw / yawRange / 通缉令图, 纯情感驱动。"""
    with space_txn(sid) as space:
        tid = _next_id("t", [t["id"] for t in space.get("tasks", [])],
                       [os.path.splitext(f)[0] for f in _listdir(os.path.join(space_dir(sid), "tasks"))])
        task = {
            "id": tid,
            "nodeId": space["nodes"][0]["id"] if space.get("nodes") else None,
            "type": "wish",
            "title": (title or "").strip() or "我想要一张照片",
            "brief": (brief or "").strip(),
            "yaw": None,
            "yawRange": None,
            "briefImage": None,
            "bounty": int(bounty) if bounty is not None else WISH_BOUNTY,
            "status": "open",
            "filledBy": [],
            "createdBy": "couple",
            "createdAt": time.time(),
        }
        space["tasks"].append(task)
        return task


# ================================================================ 业务动作
def add_node(sid, pano_bytes, filename, content_type, name, node_time):
    """传全景 = 新开一个节点: 存 pano.jpg -> 跑 DAP 深度 -> 立刻算覆盖盲区发 gap 任务。

    返回 (nodeId, 新生成的 gap 任务列表, 各阶段耗时 dict)。
    """
    # 1) 先在锁里把 node 记录占好(顺带占住目录, 保证 id 不会被并发请求撞掉)
    with space_txn(sid) as space:
        nodes_root = os.path.join(space_dir(sid), "nodes")
        os.makedirs(nodes_root, exist_ok=True)
        nid = _next_id("n", [n["id"] for n in space.get("nodes", [])], _listdir(nodes_root))
        node_dir = os.path.join(nodes_root, nid)
        os.makedirs(node_dir, exist_ok=True)
        space["nodes"].append({
            "id": nid,
            "name": (name or "").strip() or f"节点 {nid}",
            "time": (node_time or "").strip(),
            "panorama": f"nodes/{nid}/pano.jpg",
            "depth": None,
            "depthJson": None,
        })

    timings = {}
    node_dir = os.path.join(space_dir(sid), "nodes", nid)

    # 2) 重活放锁外面: 存全景 + 跑 DAP(几十秒), 别把别的宾客的上传卡死
    t0 = time.time()
    pano_path = save_panorama(pano_bytes, filename, content_type, node_dir)
    timings["pano_s"] = round(time.time() - t0, 2)

    depth_ok = True
    try:
        depth_s, _log = run_depth(pano_path, node_dir, f"{sid}_{nid}")
        timings["depth_s"] = round(depth_s, 2)
    except Exception as e:
        depth_ok = False
        timings["depth_s"] = None
        timings["depth_error"] = str(e)[:300]
        print(f"== [space {sid}/{nid}] DAP 深度失败(先不阻断建节点): {e} ==", flush=True)

    # 3) 回锁里补深度字段 + 算覆盖盲区发任务
    with space_txn(sid) as space:
        node = next(n for n in space["nodes"] if n["id"] == nid)
        if depth_ok:
            node["depth"] = f"nodes/{nid}/depth.png"
            node["depthJson"] = f"nodes/{nid}/depth.json"
        t0 = time.time()
        created = sync_gap_tasks(sid, space, nid)
        timings["gap_s"] = round(time.time() - t0, 2)
        created = copy.deepcopy(created)

    return nid, created, timings


def upload_photos(sid, files, contributor, task_id=None, node_id=None):
    """宾客上传。files = [(filename, content_type, bytes), ...]。

    流程: 占 id -> 存原图+缩略图 -> CLIP 定位 -> 置信度分流 -> 任务完成判定 -> 重算积分
        -> 重新扫一遍覆盖盲区(照片进来了, 缺口可能补上, 也可能露出新的)。

    返回 [{photoId, yaw, confidence, state, taskFilled, reason, nodeId, direction, thumb}, ...]
    """
    contributor = (contributor or "").strip() or "匿名宾客"
    if not files:
        return []

    d = space_dir(sid)
    photos_dir = os.path.join(d, "photos")
    thumbs_dir = os.path.join(d, "thumbs")
    os.makedirs(photos_dir, exist_ok=True)
    os.makedirs(thumbs_dir, exist_ok=True)

    # 1) 锁里只做两件快事: 拿节点快照 + 把 photo id 占住(建 0 字节占位文件防并发撞号)
    with space_txn(sid, write=False) as space:
        if not space.get("nodes"):
            raise RuntimeError("这个空间还没有全景节点,请新人先传一张全景")
        pids = []
        for _ in files:
            pid = _next_id("p", [p["id"] for p in space.get("photos", [])],
                           [os.path.splitext(f)[0] for f in _listdir(photos_dir)], pids)
            open(os.path.join(photos_dir, pid + ".jpg"), "ab").close()
            pids.append(pid)
        nodes_snapshot = copy.deepcopy(space["nodes"])

    # 2) 锁外面干重活: 落盘 + 缩略图 + CLIP 编码
    paths = []
    for pid, (fname, ctype, raw) in zip(pids, files):
        dest = os.path.join(photos_dir, pid + ".jpg")
        save_photo_and_thumb(raw, dest, os.path.join(thumbs_dir, pid + ".jpg"))
        paths.append(dest)

    t0 = time.time()
    placed = place_photos(sid, {"nodes": nodes_snapshot}, paths, node_id=node_id)
    clip_s = time.time() - t0

    # 3) 回锁里落记录 + 分流 + 任务判定 + 积分
    out = []
    with space_txn(sid) as space:
        touched_nodes = set()
        for pid, r in zip(pids, placed):
            conf = r["confidence"]
            margin = r.get("margin", 0.0)
            # 两个判据都要过。差哪个就在 reason 里说清楚差哪个 —— 新人在审核台上
            # 看到的是人话理由, 不是一个孤零零的数字。
            if conf >= CONF_MIN and margin >= MARGIN_MIN:
                state = "auto_ok"
                reason = f"匹配度 {conf:.2f}、辨识度 {margin:.3f},两项都达标,自动入选"
            elif conf < CONF_MIN and margin < MARGIN_MIN:
                state = "needs_review"
                reason = (f"匹配度 {conf:.2f} 偏低,辨识度 {margin:.3f} 也偏低 —— "
                          f"这张很可能不是在这个空间拍的,请你看一眼")
            elif margin < MARGIN_MIN:
                state = "needs_review"
                reason = (f"匹配度 {conf:.2f} 够高,但辨识度只有 {margin:.3f}(低于 {MARGIN_MIN}):"
                          f"它跟这个空间哪个方向都差不多像,机器拿不准是不是这儿拍的")
            else:
                state = "needs_review"
                reason = (f"辨识度 {margin:.3f} 够,但匹配度只有 {conf:.2f}(低于 {CONF_MIN}),"
                          f"方位可能不准,请你看一眼")

            photo = {
                "id": pid,
                "src": f"photos/{pid}.jpg",
                "thumb": f"thumbs/{pid}.jpg",
                "nodeId": r["nodeId"],
                "yaw": r["yaw"],
                "pitch": 0,
                "confidence": conf,
                "margin": margin,
                "state": state,
                "reason": reason,
                "contributor": contributor,
                "taskId": task_id or None,
                "uploadedAt": time.time(),
            }
            space["photos"].append(photo)
            filled = apply_task_fill(space, photo)
            touched_nodes.add(r["nodeId"])

            out.append({
                "photoId": pid,
                "nodeId": r["nodeId"],
                "yaw": r["yaw"],
                "direction": yaw_to_direction(r["yaw"]),
                "confidence": conf,
                "state": state,
                "reason": reason,
                "taskFilled": filled,
                "thumb": f"/spaces/{sid}/thumbs/{pid}.jpg",
            })

        recompute_contributors(space)
        for nid in touched_nodes:
            sync_gap_tasks(sid, space, nid)

    print(f"== [space {sid}] {len(files)} 张照片, CLIP 定位耗时 {clip_s:.2f}s ==", flush=True)
    return out


def review_photos(sid, decisions):
    """新人批量审核。decisions = [{photoId, action: approve|reject}]。

    approve 之后要做三件事: 补任务完成判定、补积分、**重算覆盖盲区**
    —— 因为照片入选了, 原来的缺口可能被补上, 也可能因为覆盖版图变了而露出新的缺口。
    """
    updated = 0
    with space_txn(sid) as space:
        by_id = {p["id"]: p for p in space.get("photos", [])}
        touched_nodes = set()
        for d in decisions or []:
            p = by_id.get(d.get("photoId"))
            if p is None:
                continue
            action = d.get("action")
            if action == "approve":
                p["state"] = "approved"
                p["reason"] = "新人手动通过"
                apply_task_fill(space, p)
            elif action == "reject":
                p["state"] = "rejected"
                p["reason"] = "新人手动拒绝"
            else:
                continue
            updated += 1
            if p.get("nodeId"):
                touched_nodes.add(p["nodeId"])

        recompute_contributors(space)
        for nid in touched_nodes:
            sync_gap_tasks(sid, space, nid)
    return updated


def space_stats(space):
    stats = {k: 0 for k in ("autoOk", "needsReview", "approved", "rejected", "quarantined")}
    name_map = {
        "auto_ok": "autoOk", "needs_review": "needsReview", "approved": "approved",
        "rejected": "rejected", "quarantined": "quarantined",
    }
    for p in space.get("photos", []):
        key = name_map.get(p.get("state"))
        if key:
            stats[key] += 1
    stats["total"] = len(space.get("photos", []))
    return stats


def get_space(sid, role="host"):
    """role=guest 只返回已入选的照片(宾客看不到别人被拒的/待审的);
    role=host 全返回, 外加一份统计, 前端拿它显示"本次自动处理 12 张, 需要你看的只有 2 张"。"""
    with space_txn(sid, write=False) as space:
        data = copy.deepcopy(space)
    if role == "guest":
        data["photos"] = [p for p in data["photos"] if p.get("state") in SELECTED_STATES]
    else:
        data["stats"] = space_stats(space)
    return data


def publish_space(sid):
    with space_txn(sid) as space:
        space["published"] = True
    return guest_url(sid)


# ================================================================ 发布时的机器验收(自检环)
#
# 自检环(server/verify.py)在这个产品里有两个角色:
#   ① 上传时当【筛选器】—— 已经做了: CLIP 置信度分流, 高的 auto_ok, 低的 needs_review。
#   ② 发布时当【验收员】—— 就是这一段: 新人按下"发布空间", 后台无人值守地把空间的页面
#      真跑一遍(结构闸 + 渲染闸 + 语义闸), 报告落 spaces/<sid>/report.json,
#      新人后台给一个"查看机器验收报告"的链接。全程 humanInLoop=false。
SELF_URL = os.environ.get("PSM_SELF_URL", "http://127.0.0.1:8777")

_verify_state = {}   # sid -> "running" | "done" | "error: ...", 只给日志和排查用


def set_self_url(url):
    """让 compose_server 把自己的地址告诉这里 —— 自检环要用无头浏览器访问本服务自己的页面。"""
    global SELF_URL
    SELF_URL = (url or SELF_URL).rstrip("/")


def build_verify_manifest(sid, node_id=None):
    """把 space.json 里指定节点的那一份内容, 派生成一份 manifest.json 落在空间目录下。

    为什么要派生: 结构闸(server/checks.py)读的是 <目录>/manifest.json 那套契约
    (panorama/depth/depthJson/photos, 路径相对该目录), 而空间用的是另一套 schema。
    与其把结构闸改成认两种格式, 不如在这里翻译一次 —— 结构闸一行都不用动。
    这份 manifest.json 是【派生产物】, 真值永远在 space.json 里, 删了下次发布会重新生成。

    返回 (node_id, manifest_path, 入选照片数)。
    """
    with space_txn(sid, write=False) as space:
        nodes = space.get("nodes") or []
        if not nodes:
            raise ValueError("这个空间还没有全景节点, 没法验收")
        node = None
        if node_id:
            node = next((n for n in nodes if n.get("id") == node_id), None)
        node = node or nodes[0]
        photos = [
            p for p in space.get("photos") or []
            if p.get("state") in SELECTED_STATES and (
                not p.get("nodeId") or p.get("nodeId") == node["id"])
        ]
        manifest = {
            "panorama": node.get("panorama"),
            "depth": node.get("depth"),
            "depthJson": node.get("depthJson"),
            "title": space.get("title") or "我们的空间",
            "photos": [{
                "src": p.get("src"),
                "yaw": p.get("yaw"),
                "pitch": p.get("pitch", 0),
                "confidence": p.get("confidence"),
                "by": "auto",
                "caption": (p.get("contributor") or "宾客") + " 交的",
            } for p in photos],
        }
    path = os.path.join(space_dir(sid), "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return node["id"], path, len(photos)


def run_publish_verify(sid, node_id=None, max_attempts=1):
    """同步跑一次发布验收, 返回 report。给 kick_publish_verify 在后台线程里调, 也能单独调来测。

    max_attempts 默认 1(不自愈): 空间的照片真值在 space.json 里, 自愈只会去改那份派生的
    manifest.json, 改了也不会回流, 等于白改。空间这边的"自愈"是另一条路 —— 置信度低的照片
    上传时就已经被拦成 needs_review 交给新人了, 压根进不到这里。
    """
    # 结构闸的置信度阈值用 verify.py 自己的默认值, 不跟这里的 CONF_MIN 走:
    # 新人手动 approve 的那些照片本来就是"机器拿不准、人说要"的, 拿分流阈值去卡它们,
    # 等于机器推翻新人的决定, 整个空间会被判不通过。
    from server.verify import verify_target   # 延迟 import: 让 selftest_space 不依赖整条自检环

    nid, _path, n_photos = build_verify_manifest(sid, node_id)
    page_url = "%s/viewer/walk.html?space=%s&node=%s" % (SELF_URL.rstrip("/"), sid, nid)
    print(f"== [{sid}] 发布验收开跑: {page_url} ({n_photos} 张入选照片) ==", flush=True)
    report = verify_target(
        space_dir(sid), page_url, label=sid, max_attempts=max_attempts,
        model=_clip_state.get("model"),
    )
    print(f"== [{sid}] 机器验收裁决: {report['verdict']} — {report['reason']} ==", flush=True)
    return report


def kick_publish_verify(sid, node_id=None):
    """后台线程跑验收。绝不能挡住 /publish 的返回 —— 新人按下发布就该立刻看到"已发布",
    验收是机器自己的事(要起无头 Chrome、截图、判图, 十几秒起步), 慢慢跑。"""
    def run():
        _verify_state[sid] = "running"
        try:
            run_publish_verify(sid)
            _verify_state[sid] = "done"
        except Exception as e:
            _verify_state[sid] = f"error: {type(e).__name__}: {e}"
            print(f"== [{sid}] 发布验收自己炸了: {type(e).__name__}: {e} ==", flush=True)

    threading.Thread(target=run, daemon=True, name=f"space-verify-{sid}").start()


# ================================================================ 宾客链接
def _lan_ip():
    """拿本机局域网 IP。UDP connect 不真的发包, 只是让内核挑一张出口网卡。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def public_base():
    """基址优先级: ① 环境变量 PSM_PUBLIC_URL ② server/public_url.txt(隧道地址) ③ 本机局域网 IP。"""
    env = (os.environ.get("PSM_PUBLIC_URL") or "").strip()
    if env:
        return env.rstrip("/")
    if os.path.exists(PUBLIC_URL_FILE):
        txt = open(PUBLIC_URL_FILE, encoding="utf-8").read().strip()
        if txt:
            return txt.rstrip("/")
    port = os.environ.get("PSM_PORT", "8777")
    return f"http://{_lan_ip()}:{port}"


def guest_url(sid):
    """给二维码用的宾客链接。宾客扫码直接进 H5, 不注册不装 app。"""
    return f"{public_base()}/server/join.html?space={sid}"


# ================================================================ HTTP 路由
#
# ⚠️ 这里所有接口都故意写成同步 def 而不是 async def。
# FastAPI 对同步接口会自动丢进线程池跑, 对 async 接口则直接在事件循环上跑。
# 本模块干的全是阻塞活(DAP 深度 20 秒 / CLIP 编码 / PIL 编解码), 写成 async 的话
# 新人传一张全景就会把整个事件循环占死 20 秒, 现场所有宾客的上传一起卡住 ——
# 而婚礼场景恰恰就是"一堆人同时传"。写成同步 def 之后它们各跑各的线程,
# 也正好和上面用的 threading.Lock 是同一套并发模型(async 里用 threading.Lock 才是错配)。
def _fail(msg, code=200):
    return JSONResponse({"ok": False, "error": str(msg)}, status_code=code)


@router.post("/space")
def api_create_space(payload: dict = Body(default={})):
    try:
        sid = create_space(payload.get("title"), payload.get("couple"))
        return {"ok": True, "spaceId": sid}
    except Exception as e:
        return _fail(f"建空间失败: {e}")


@router.get("/spaces")
def api_list_spaces():
    try:
        return {"ok": True, "spaces": list_spaces()}
    except Exception as e:
        return _fail(f"读空间列表失败: {e}")


@router.get("/space/{sid}")
def api_get_space(sid: str, role: str = "host"):
    try:
        return {"ok": True, "space": get_space(sid, role)}
    except FileNotFoundError as e:
        return _fail(e)
    except Exception as e:
        return _fail(f"读空间失败: {e}")


@router.post("/space/{sid}/node")
def api_add_node(
    sid: str,
    panorama: UploadFile = File(...),
    name: str = Form(""),
    node_time: str = Form("", alias="time"),   # 表单字段名就叫 time, 但不能遮住 time 模块
):
    try:
        raw = panorama.file.read()
        nid, tasks, timings = add_node(
            sid, raw, panorama.filename, panorama.content_type, name, node_time,
        )
        return {"ok": True, "nodeId": nid, "tasks": tasks, "timings": timings}
    except FileNotFoundError as e:
        return _fail(e)
    except Exception as e:
        return _fail(f"传全景失败: {e}")


@router.post("/space/{sid}/upload")
def api_upload(
    sid: str,
    photos: list[UploadFile] = File(default=[]),
    contributor: str = Form(""),
    taskId: str = Form(""),
    nodeId: str = Form(""),
):
    try:
        files = []
        for f in photos or []:
            if f is None or not f.filename:
                continue
            files.append((f.filename, f.content_type, f.file.read()))
        if not files:
            return _fail("没收到照片")
        results = upload_photos(
            sid, files, contributor, task_id=(taskId or None), node_id=(nodeId or None),
        )
        return {"ok": True, "results": results}
    except FileNotFoundError as e:
        return _fail(e)
    except Exception as e:
        return _fail(f"上传失败: {e}")


@router.post("/space/{sid}/task")
def api_create_task(sid: str, payload: dict = Body(default={})):
    try:
        task = create_wish_task(
            sid, payload.get("title"), payload.get("brief"), payload.get("bounty"),
        )
        return {"ok": True, "task": task}
    except FileNotFoundError as e:
        return _fail(e)
    except Exception as e:
        return _fail(f"发心愿任务失败: {e}")


@router.post("/space/{sid}/review")
def api_review(sid: str, payload: dict = Body(default={})):
    try:
        n = review_photos(sid, payload.get("decisions") or [])
        return {"ok": True, "updated": n}
    except FileNotFoundError as e:
        return _fail(e)
    except Exception as e:
        return _fail(f"审核失败: {e}")


@router.post("/space/{sid}/publish")
def api_publish(sid: str, payload: dict = Body(default={})):
    try:
        url = publish_space(sid)
        # 旧报告先删掉, 否则前端一轮询就拿到上一次的结论, 会以为这次的已经验完了
        old = os.path.join(space_dir(sid), "report.json")
        if os.path.exists(old):
            os.remove(old)
        # 后台跑机器验收, 不挡这次返回。没有全景节点之类的情况在线程里如实报错, 不影响发布本身。
        kick_publish_verify(sid)
        return {
            "ok": True, "published": True, "viewUrl": url,
            "reportUrl": f"/server/report.html?src=/spaces/{sid}/report.json",
        }
    except FileNotFoundError as e:
        return _fail(e)
    except Exception as e:
        return _fail(f"发布失败: {e}")


# ---------------------------------------------------------------- 发布到云 + 工人心跳
#
# 云发布为什么要走后台线程 + 轮询: 首次全量发布实测 98 秒(这台机器传杭州只有 ~27KB/s)。
# 同步返回会让新人后台的 fetch 干等一分半, 看着像卡死。所以 POST 只负责"点火",
# 进度写在内存里, 前端 GET 轮询画进度条。
_cloud_state = {}          # sid -> {running, done, total, key, result, error, at}
_cloud_lock = threading.Lock()


def _cloud_get(sid):
    with _cloud_lock:
        return dict(_cloud_state.get(sid) or {})


def _cloud_set(sid, **kw):
    with _cloud_lock:
        st = _cloud_state.setdefault(sid, {})
        st.update(kw)
        st["at"] = time.time()


def kick_publish_cloud(sid):
    """后台线程把空间推到 OSS。已经在跑就不重复点火(重复点火会互相抢带宽)。"""
    from server import publish       # 延迟导入: 让没配 OSS 凭据的人也能用本机模式

    st = _cloud_get(sid)
    if st.get("running"):
        return False

    def run():
        _cloud_set(sid, running=True, done=0, total=0, key="", result=None, error=None)
        try:
            def progress(done, total, key):
                _cloud_set(sid, done=done, total=total, key=key)
            r = publish.publish_space(sid, progress=progress)
            # public 那一整份没必要塞进状态里(几十 KB, 前端也不看), 去掉。
            r.pop("public", None)
            _cloud_set(sid, running=False, result=r, error=None)
            print(f"== [{sid}] 云发布完成: 上传 {r['uploaded']} 跳过 {r['skipped']} "
                  f"耗时 {r['elapsedS']}s → {r['spaceJson']} ==", flush=True)
        except Exception as e:
            _cloud_set(sid, running=False, error=f"{type(e).__name__}: {e}")
            print(f"== [{sid}] 云发布失败: {type(e).__name__}: {e} ==", flush=True)

    threading.Thread(target=run, daemon=True, name=f"space-cloud-{sid}").start()
    return True


@router.post("/space/{sid}/publish-cloud")
def api_publish_cloud(sid: str, payload: dict = Body(default={})):
    try:
        with space_txn(sid, write=False):
            pass        # 先确认空间在, 免得后台线程炸在一个不存在的 sid 上
        started = kick_publish_cloud(sid)
        return {"ok": True, "started": started, "state": _cloud_get(sid)}
    except FileNotFoundError as e:
        return _fail(e)
    except Exception as e:
        return _fail(f"云发布起不来: {e}")


@router.get("/space/{sid}/publish-cloud")
def api_publish_cloud_state(sid: str):
    """轮询云发布进度。state 里有 running/done/total/result/error。"""
    return {"ok": True, "state": _cloud_get(sid)}


@router.get("/space/{sid}/worker-status")
def api_worker_status(sid: str):
    """后台工人还活着吗? —— 工人(server/worker.py)每轮往空间目录写一次 .worker.json,
    60 秒内有心跳就算在跑。忘了起工人的话宾客传的照片永远不会出现, 这一格必须显眼。"""
    path = os.path.join(space_dir(sid), ".worker.json")
    try:
        with open(path, encoding="utf-8") as f:
            hb = json.load(f)
        age = time.time() - float(hb.get("at") or 0)
        return {"ok": True, "running": age < 60, "ageS": round(age, 1),
                "pid": hb.get("pid"), "note": hb.get("note") or ""}
    except Exception:
        return {"ok": True, "running": False, "ageS": None, "pid": None, "note": ""}


@router.get("/space/{sid}/joinurl")
def api_joinurl(sid: str):
    try:
        with space_txn(sid, write=False):
            pass    # 只是确认空间存在
        return {"ok": True, "url": guest_url(sid)}
    except FileNotFoundError as e:
        return _fail(e)
    except Exception as e:
        return _fail(f"生成宾客链接失败: {e}")


os.makedirs(SPACES_DIR, exist_ok=True)
