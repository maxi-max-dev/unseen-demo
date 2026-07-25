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
import ipaddress
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import quote

import numpy as np
from fastapi import APIRouter, Body, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPACES_DIR = os.path.join(REPO_ROOT, "server", "spaces")
DAP_PYTHON = os.path.join(REPO_ROOT, ".venv-dap", "bin", "python")
DEPTH_SCRIPT = os.path.join(REPO_ROOT, "tools", "depth.py")
DEPTH_ASSET_DIR = os.path.join(REPO_ROOT, "assets", "depth")
PUBLIC_URL_FILE = os.path.join(REPO_ROOT, "server", "public_url.txt")
FFMPEG = "/opt/homebrew/bin/ffmpeg"
CLOUD_JOIN_BASE = (
    os.environ.get("PSM_CLOUD_JOIN_BASE")
    or "https://unseen-demo.vercel.app/web/join.html"
).strip() or "https://unseen-demo.vercel.app/web/join.html"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.slice import equirect_to_perspective, FOV, CROP_W, CROP_H, YAWS  # noqa: E402
from tools.match import match_one  # noqa: E402

# ---------------------------------------------------------------- 常量
SCHEMA = "psm-space/1"
EXHIBITION_SCHEMA = "unseen-exhibition/1"
EXHIBITION_VIEWS = ("walk", "photos", "tasks", "contributors")
DEFAULT_EXHIBITION_VIEWS = ("walk", "photos", "tasks", "contributors")

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
#   当初加 margin 的理由: confidence 是 CLIP 给【自己刚做的决定】打的分, 有循环论证的嫌疑,
#   它只回答"我有多喜欢这个 yaw"。margin 问的是"最佳匹配比平均水平突出多少", 在 ballroom
#   这张全景上外来照片的 margin 确实塌了下去(见上面两组区间), 于是当时把它当成了
#   "这张照片到底属不属于这个空间"的判据。
#
# ⚠️ 2026-07-25 换全景复测: 上面那句话【不成立】, 别再照抄。
#   换成三张全新的 Poly Haven 全景(billiard_hall / church_museum / combination_room),
#   建 s20 到 s26 重跑同样的标注实验(s20+s21 共 24 张本空间 vs 12 张外来), 实测:
#
#     判据            本空间区间        外来区间          结论
#     confidence     0.7016 ~ 0.9973   0.7087 ~ 0.7921   外来【全部】低于 0.82 门槛
#     margin         0.0332 ~ 0.2038   0.0370 ~ 0.1045   两组区间几乎完全重叠
#
#   最扎眼的一条: s20 里 margin 最高的【外来】照片是 0.1045(p16), 比每一张本空间重损照片
#   (最高 0.0678)都高。判别力量化(全集 AUC): confidence 0.927, margin 0.830;
#   只看难分的那一段(本空间重损档 8 张 vs 外来 12 张): confidence 0.781, margin 0.510,
#   也就是 margin 在真正需要它拿主意的地方等于抛硬币。
#
#   这一轮 margin 的实际贡献是 0: 12 张外来照片【全部】是被 confidence 拦下的, 没有一张
#   是"conf 过了、被 margin 拦下"; 同时它也没误伤任何一张本空间照片。它是惰性的, 不是有效的。
#
#   所以下面这组阈值现在的如实表述是: 拦外来照片靠的是 confidence >= 0.82,
#   margin >= 0.055 是一道低成本的冗余闸, 在 ballroom 上有效、在新全景上空转,
#   【不要】把它当成场景无关的"归属判据"。换场景/换全景/换 CLIP 权重都必须重新标定,
#   0.055 这个数只在 clip-ViT-B-32 + 12 张裁切 bank 这条管线上有意义。
#
#   ballroom 那一轮的验收结论(保留作为历史): 实测 23/24, 外来照片入侵 0/15 全部拦下
#   (这是唯一要命的失败模式), 代价是 1 张本空间照片(margin 0.0423)被推给新人确认,
#   错在安全的那一侧, 点一下就收下。新全景那一轮: 外来入侵 0/12, 本空间自动入选 19/24。
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


def _clean_meta(date=None, place=None, cover=None, private=None):
    """把建空间时那几个【可选】的展示字段规整成固定形状。

    全部可选:一个都不传就是四个空值(private 空值 = False), 老的
    create_space(title, couple) 调用行为一字不差。
    """
    return {
        "date": (date or "").strip(),      # 形如 "2026-07-26", 只当字符串存, 后端不解析
        "place": (place or "").strip(),
        # cover 可能是前端压到 640px 的 base64 dataURL(几十上百 KB), 也可能是
        # 模板封面的根相对路径。这里原样存, 不截断(截断 dataURL 等于把图弄坏)。
        # 撑爆列表响应的问题在 list_spaces 里解决, 见那边的注释。
        "cover": (cover or "").strip(),
        # 有的前端会把布尔值当字符串发过来("false" 在 Python 里是 True), 这里挡一下
        "private": (private.strip().lower() not in ("", "false", "0", "no")
                    if isinstance(private, str) else bool(private)),
    }


def _default_collection(now=None):
    return {
        "status": "open",
        "updatedAt": float(now if now is not None else time.time()),
    }


def _normal_collection(raw):
    """把老空间补成明确的收集状态, 只改返回副本时也能安全使用。"""
    out = _default_collection()
    if isinstance(raw, dict):
        if raw.get("status") in ("open", "closed"):
            out["status"] = raw["status"]
        if isinstance(raw.get("updatedAt"), (int, float)):
            out["updatedAt"] = float(raw["updatedAt"])
    return out


def _default_exhibition(now=None):
    return {
        "schema": EXHIBITION_SCHEMA,
        "status": "draft",
        "revision": 0,
        "entryView": "walk",
        "views": list(DEFAULT_EXHIBITION_VIEWS),
        "allowPov": True,
        "contributorVisibility": "name",
        "taskVisibility": "all",
        "updatedAt": float(now if now is not None else time.time()),
    }


def _normal_exhibition(raw):
    """归一老数据。公开展示只认这份白名单, 未知模块永远不会漏到前端。"""
    out = _default_exhibition()
    if not isinstance(raw, dict):
        return out
    views = []
    for view in raw.get("views") or []:
        if view in EXHIBITION_VIEWS and view not in views:
            views.append(view)
    if views:
        out["views"] = views
    entry = raw.get("entryView")
    out["entryView"] = entry if entry in out["views"] else out["views"][0]
    if raw.get("status") in ("draft", "published"):
        out["status"] = raw["status"]
    if isinstance(raw.get("revision"), int) and raw["revision"] >= 0:
        out["revision"] = raw["revision"]
    if isinstance(raw.get("allowPov"), bool):
        out["allowPov"] = raw["allowPov"]
    if raw.get("contributorVisibility") in ("name", "anonymous", "hidden"):
        out["contributorVisibility"] = raw["contributorVisibility"]
    if raw.get("taskVisibility") in ("hidden", "completed", "all"):
        out["taskVisibility"] = raw["taskVisibility"]
    if isinstance(raw.get("updatedAt"), (int, float)):
        out["updatedAt"] = float(raw["updatedAt"])
    return out


def set_collection_status(sid, status):
    if status not in ("open", "closed"):
        raise ValueError("收集状态只能是 open 或 closed")
    with space_txn(sid) as space:
        collection = _normal_collection(space.get("collection"))
        collection["status"] = status
        collection["updatedAt"] = time.time()
        space["collection"] = collection
        return copy.deepcopy(collection)


def set_exhibition(sid, payload):
    payload = payload if isinstance(payload, dict) else {}
    views = payload.get("views")
    if not isinstance(views, list):
        raise ValueError("展示模块必须是数组")
    unknown = [v for v in views if v not in EXHIBITION_VIEWS]
    if unknown:
        raise ValueError("包含不支持的展示模块")
    clean_views = []
    for view in views:
        if view not in clean_views:
            clean_views.append(view)
    if not clean_views:
        raise ValueError("至少保留一个展示模块")

    entry = payload.get("entryView") or clean_views[0]
    if entry not in clean_views:
        raise ValueError("默认入口必须属于已启用模块")
    contributor_visibility = payload.get("contributorVisibility", "name")
    if contributor_visibility not in ("name", "anonymous", "hidden"):
        raise ValueError("贡献者显示方式不支持")
    task_visibility = payload.get("taskVisibility", "all")
    if task_visibility not in ("hidden", "completed", "all"):
        raise ValueError("任务显示方式不支持")
    if contributor_visibility == "hidden" and "contributors" in clean_views:
        raise ValueError("贡献者整段隐藏时不能启用贡献者模块")
    if task_visibility == "hidden" and "tasks" in clean_views:
        raise ValueError("任务整段隐藏时不能启用任务模块")

    with space_txn(sid) as space:
        old = _normal_exhibition(space.get("exhibition"))
        exhibition = {
            "schema": EXHIBITION_SCHEMA,
            "status": "draft",
            "revision": old["revision"] + 1,
            "entryView": entry,
            "views": clean_views,
            "allowPov": bool(payload.get("allowPov", True)),
            "contributorVisibility": contributor_visibility,
            "taskVisibility": task_visibility,
            "updatedAt": time.time(),
        }
        space["exhibition"] = exhibition
        return copy.deepcopy(exhibition)


def create_space(title, couple, date=None, place=None, cover=None, private=None):
    """建一个新空间, 返回 sid。目录骨架一次建齐, 后面各处就不用到处 makedirs 了。

    date / place / cover / private 都是可选的展示字段, 只为了换台设备也还在
    (以前它们只躺在浏览器 localStorage 里)。不传就是空, 不影响任何已有行为。
    """
    with _LOCK:
        os.makedirs(SPACES_DIR, exist_ok=True)
        sid = _next_id("s", _listdir(SPACES_DIR))
        d = space_dir(sid)
        for sub in ("", "nodes", "photos", "thumbs", "tasks"):
            os.makedirs(os.path.join(d, sub), exist_ok=True)
        now = time.time()
        space = {
            "schema": SCHEMA,
            "id": sid,
            "title": (title or "").strip() or "我们的空间",
            "couple": (couple or "").strip(),
            "createdAt": now,
            "published": False,
            "collection": _default_collection(now),
            "exhibition": _default_exhibition(now),
            "nodes": [],
            "tasks": [],
            "photos": [],
            "contributors": [],
        }
        space.update(_clean_meta(date, place, cover, private))
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
            # 封面处理:cover 可能是一整张 base64 dataURL, 一个空间就几十上百 KB。
            # 列表接口会把所有空间拼在一起返回, 原样带上去几十个空间就是几 MB,
            # 所以列表里【只给短的】(模板封面那种根相对路径), dataURL 一律不带,
            # 只用 hasCover 告诉前端"有封面, 想要完整的去详情接口拿"。
            cover = sp.get("cover") or ""
            light_cover = cover if (cover and not cover.startswith("data:")
                                    and len(cover) <= 512) else ""
            out.append({
                "id": sp["id"],
                "title": sp.get("title", ""),
                "couple": sp.get("couple", ""),
                "photoCount": len(sp.get("photos", [])),
                # ⚠️ photoCount 是【收到的总张数】, 含被拒和待审的, 含义和值都不许改(别处在用)。
                # 想说"空间里有几张照片"要用下面这个 selectedCount = auto_ok + approved。
                # 实测 s20 的 18 张里真正在空间里的只有 8 张, s21 的 18 张里有 6 张是新人
                # 亲手点了"不要"的 —— 首屏拿 photoCount 写"18 张照片"就是穿帮。
                "selectedCount": sum(1 for p in sp.get("photos", [])
                                     if p.get("state") in SELECTED_STATES),
                "taskCount": sum(1 for t in sp.get("tasks", []) if t.get("status") == "open"),
                # 下面几个是加法, 老前端不认就当没看见, 不影响上面任何字段
                "date": sp.get("date", ""),
                "place": sp.get("place", ""),
                "cover": light_cover,
                "hasCover": bool(cover),
                "private": bool(sp.get("private", False)),
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
def _selected_yaws(space, node_id):
    """这个节点下【已入选】照片的 yaw 列表 —— 覆盖率的唯一真值来源。
    待审/被拒的照片不算数, 它们还没出现在空间里。"""
    return [
        float(p["yaw"]) for p in space.get("photos", [])
        if p.get("nodeId") == node_id
        and p.get("state") in SELECTED_STATES
        and p.get("yaw") is not None
    ]


def _coverage_mask(yaws, half_width_deg=20.0):
    """把一组照片 yaw 摊成 360 格的"哪些方位已经有照片"掩码, 每张覆盖 ±half_width。

    ⚠️ 这是"三把尺子"里的【第二把】(覆盖尺, 一张照片只算 ±20°)。
    另外两把在 _task_accepts_yaw(认领尺)和 _gap_brief/_slice_brief_image(文案尺)那儿,
    三者口径不同是【有意的】, 完整说明见 _task_accepts_yaw 上方那段"三把尺子"注释,
    改任何一把之前先读那段。
    """
    hw = int(round(half_width_deg))
    covered = np.zeros(360, dtype=bool)
    for y in yaws:
        c = int(round(y)) % 360
        covered[(np.arange(c - hw, c + hw + 1)) % 360] = True
    return covered


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
    yaws = _selected_yaws(space, node_id)

    # 零照片: 整圈都是空的。这时候不该只发一个 360° 的巨型任务(没法指挥人往哪拍),
    # 而是均匀撒 3 个方向, 让第一批宾客把骨架先撑起来。
    # 区间取 [c-60, c+59] 而不是 [c-60, c+60]: 三段刚好铺满一圈且互不重叠,
    # 否则它们会在边界上互相判定成"已经有任务盯着了"而被去重掉。
    if not yaws:
        return [
            {"start": (c - 60) % 360, "end": (c + 59) % 360, "center": c, "width": 120, "empty": True}
            for c in (0, 120, 240)
        ][:max_tasks]

    covered = _coverage_mask(yaws, half_width_deg)

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
    """gap 任务的人话文案。用方位词而不是角度 —— 宾客不会看着 210° 去转身。

    ⚠️ 这是"三把尺子"里的【第三把】(文案尺, 取区间【中点】, 通缉令切图 _slice_brief_image
    用的也是这个 center)。它比认领尺窄得多: 文案喊的是中点一个方向, 认领收的是整个区间。
    完整说明见 _task_accepts_yaw 上方那段"三把尺子"注释。
    """
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


def _close_stale_gap_tasks(space, node_id, half_width_deg=20.0, min_gap_deg=40.0):
    """缺口已经被补上的 gap 任务, 关掉它。

    ⚠️ 2026-07-25 修的 P0: 以前任务【只创建从不关闭】。实测 s20 的任务墙一直挂着
    「还缺这 2 张」+50 分悬赏, 而那两个区间里其实已经躺着 4 张入选照片,
    find_coverage_gaps 早就返回 [] 了 —— 宾客被指挥去拍一个根本不缺的方向。

    判定口径和【发任务时】用的是同一把尺子: 任务区间里还没被照片覆盖的格子
    不足 min_gap_deg 度, 就说明它已经不构成一个"缺口"了(发任务时也是宽度不够
    min_gap_deg 就不发), 于是关掉。

    只关系统按缺口自动发的那些(type == "gap" 且 createdBy == "system"),
    新人手写的心愿任务(type == "wish" / createdBy == "couple")一律不碰 ——
    心愿任务没有 yawRange, 也不该被覆盖率左右。

    状态用 "closed": 这个取值前端早就认(host.html 显示"已关闭"并排到最后,
    join.html / scene.html 都按 status !== "open" 当已完成处理), 不会把前端弄崩。
    返回被关掉的任务列表。
    """
    covered = _coverage_mask(_selected_yaws(space, node_id), half_width_deg)
    closed = []
    for t in space.get("tasks", []):
        if (t.get("nodeId") != node_id or t.get("type") != "gap"
                or t.get("status") != "open" or t.get("createdBy") != "system"):
            continue
        rng = t.get("yawRange")
        if not rng or len(rng) != 2:
            continue        # 没方位要求的, 没法用覆盖率判定, 留着
        still_missing = int((_arc_mask(rng[0], rng[1]) & ~covered).sum())
        if still_missing >= min_gap_deg:
            continue        # 这一片是真还缺, 别关
        t["status"] = "closed"
        t["closedAt"] = time.time()
        t["closedReason"] = f"这个方向已经有照片了,还差 {still_missing}°,系统自动结束"
        closed.append(t)
    return closed


def sync_gap_tasks(sid, space, node_id, half_width_deg=20.0, min_gap_deg=40.0, max_tasks=3):
    """把 find_coverage_gaps 算出的缺口变成真的 gap 任务(切通缉令图 + 落进 space["tasks"])。

    四条约束:
      - 缺口已经补上的 open gap 任务, 先关掉(_close_stale_gap_tasks);
      - 一个节点上同时最多 max_tasks 个 open 的 gap 任务;
      - 已经存在覆盖同一区间的 open 任务, 不重复发;
      - 覆盖率变化后调用即可(传全景后 / 上传后 / 审核后), 幂等。

    直接改传进来的 space(不落盘), 调用方负责 save。返回新建的任务列表。
    """
    node = next((n for n in space.get("nodes", []) if n["id"] == node_id), None)
    if node is None:
        return []

    # 先关过期的, 再算还缺哪儿 —— 顺序反了的话, 名额会被那些其实已经补上的任务白占着。
    for t in _close_stale_gap_tasks(space, node_id, half_width_deg, min_gap_deg):
        print(f"== [space {sid}] 缺口已补上, 关掉任务 {t['id']} {t.get('yawRange')} ==", flush=True)

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
    margin = 最佳相似度 减去 所有裁切的平均相似度, 意思是"最佳匹配比平均水平突出多少"。
    ⚠️ 它不是可靠的"这张到底属不属于这个空间"判据: 2026-07-25 换全景复测里本空间和外来
    两组的 margin 区间几乎完全重叠(难分段 AUC 0.510, 约等于抛硬币), 真正拦住外来照片的是
    confidence。详见文件顶部 CONF_MIN/MARGIN_MIN 上方的实测数据注释。
    """
    all_nodes = space.get("nodes", [])
    if not all_nodes:
        raise RuntimeError("这个空间还没有全景节点,请新人先传一张全景")
    nodes = [n for n in all_nodes if node_id is None or n["id"] == node_id]
    if not nodes:
        # ⚠️ 2026-07-25 修的 P2: 这一句以前不分情况一律说"这个空间还没有全景节点",
        # 于是客户端塞一个根本不存在的 nodeId 时, 一个明明有 2 张全景的空间会告诉宾客
        # "还没有全景节点,请新人先传一张全景" —— 一句会原样显示在宾客手机上的谎话。
        # 现在两种情况分开说, 上面那句只留给真的一个节点都没有的空间。
        raise RuntimeError(f"这个空间里没有叫「{node_id}」的位置,换个位置再试一次")

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


# ---------------------------------------------------------------- 三把尺子(读完再改任何一把)
# 同一件事"这个方向到底算不算有照片了", 全系统有三处在量, 口径【不一样】, 是有意的:
#
#   ① 认领尺  _task_accepts_yaw: 照片 yaw 落进任务【整个 yawRange】就算完成。
#              空空间发的第一批任务区间宽 120°(find_coverage_gaps 的 empty 分支),
#              也就是站在原地转 120° 内随便哪个方向拍都算补上了这一条。
#   ② 覆盖尺  _coverage_mask: 一张照片只覆盖 ±20°(共 41 格), 缺口/关任务全按这把量。
#   ③ 文案尺  _gap_brief + _slice_brief_image: 任务说的那句话和那张通缉令图, 取的是
#              区间【中点】一个方向。宾客看到的是"转向正前方"和一张正前方的图。
#
# 于是必然出现两种看着矛盾的现象(都不是 bug, 是三把尺子的算术结果):
#   A. 任务显示"已完成", 而它区间的中间还空着 —— 照片落在区间边缘, 只覆盖了 ±20°。
#   B. 明明按图拍了, 缺口还在 —— 120° 的区间要三张 ±20° 的照片才铺满。
#
# 【2026-07-25 的判断: 不收窄认领尺, 只把口径写清楚。】理由三条:
#   1. 现象 A 最后系统自己会兜住, 缺口【不会被吞掉】, 只是那 50 分发早了。
#      本轮在 s10010 的 n1 上实测(数字都是接口原样返回的):
#        · 空空间发的 t2 区间 [60,179](120° 宽), 一张 yaw=134.9 的照片就把它变成 filled,
#          而这张照片按覆盖尺只盖住了 [115,155] 这 41 格, 区间里还空着 79 格;
#        · 【当场并没有】补发新任务 —— n1 的 open gap 名额(max_tasks=3)那时被 t1/t3 占满,
#          新算出来的缺口跟它俩重叠, 被去重规则挡掉了;
#        · 等 t1/t3 也被填掉、名额空出来之后, 下一次 sync_gap_tasks 立刻按覆盖尺补发了
#          三条更窄的: t7 [156,234]、t8 [36,114]、t9 [276,354](各 79°), 正好盯着还空的三段。
#      所以准确说法是"补发会延后到名额空出来", 不是"当场补发"。
#   2. 收窄的代价【落在宾客头上】: 认领判据一旦改成"中点 ±20°", 空空间那批 120° 的
#      任务就只有 41/120 = 34% 的方向能拿到悬赏, 其余 66% 会收到一句"没算完成",
#      而宾客明明是照着任务文案转身拍的。这是把系统内部的尺子差额转嫁成宾客的挫败感,
#      现场演示最怕的就是这个。
#   3. 真要统一, 该动的是【发任务那一端】而不是认领端: 让 find_coverage_gaps 把
#      120° 的空区间直接切成三条 ±20° 的窄任务, 三把尺子自然就对齐了, 而且宾客
#      拿到的指令更具体。那是产品改动, 不是收口 bug, 不该在这一轮顺手做。
# 已知残留风险(如实记下): 一张落在区间边缘的照片会拿满 50 分悬赏, 而它只补上了这段
# 缺口的三分之一。悬赏发多了, 但没有人被少发, 也没有缺口被吞掉。
def _task_accepts_yaw(task, yaw):
    """这张照片的方位, 够不够格算完成这个任务(只管方位, 不管在哪个节点拍的)。

    ⚠️ yawRange 是【圆环】区间, 可能跨 0 度(例如 [300, 59] 表示 300→360→59),
    所以必须走 yaw_in_range(它处理了绕回), 千万别写成 start <= yaw <= end。
    心愿任务(wish)没有 yawRange, 本来就不挑方位, 一律放行。
    yawRange 在但照片没算出 yaw: 没法核对, 不给认领。

    ⚠️ 单独用它当认领闸门是【不够】的, 它不看节点。调用方一律走 _task_accepts_photo。
    """
    rng = task.get("yawRange")
    if not rng or len(rng) != 2:
        return True
    return yaw is not None and yaw_in_range(yaw, rng)


def _task_is_located(task):
    """这个任务挑不挑"在哪儿拍" —— 也就是它有没有一个具体的方位要求。

    判据用 yawRange 而不是 type: 有 yawRange 的任务(系统按缺口发的 gap)天生绑死
    "某个节点的某一段圆环", 换个节点它就没有意义了。
    心愿任务(wish)的 nodeId 是建任务时随手记的第一个节点(见 create_wish_task),
    【不是】位置要求 —— "我想要一张我妈笑起来的照片"在哪个房间拍都算数,
    拿它的 nodeId 去卡人就是误伤。所以这里只认 yawRange。
    """
    rng = task.get("yawRange")
    return bool(rng) and len(rng) == 2


def _task_accepts_photo(task, photo):
    """认领闸门: 这张照片够不够格算完成这个任务。返回 (行不行, 不行的原因)。

    原因取值 None / "node" / "yaw", 调用方拿它挑该说哪句人话。

    ⚠️ 2026-07-25 收口: 以前这里只比方位, 不比节点, 结果是【跨节点冒领】——
    客户端明确带 taskId 的那条分支上, 从 n2 拍的照片可以去认领 n1 的任务,
    只要 yaw 恰好落进 n1 那个任务的区间里(圆环角度和节点无关, 两个房间的 110° 一样是 110°)。
    实测复现(s10001/p7): n2 的照片 yaw=105.1 认领了 n1 的 t5(区间 [66,145]),
    返回 nodeId=n2、taskFilled=t5、50 分照发, 而同一时刻后端自己算出来的 n1 那段缺口
    依然空着 —— "系统指挥人把没拍到的方位补齐"这个核心卖点原地失效。
    自动判定那条分支一直有节点校验(t["nodeId"] == photo["nodeId"]), 唯独指定 taskId
    这条没有, 而它恰好是宾客点任务上传时走的那条路。
    """
    if not _task_is_located(task):
        return True, None                       # 心愿任务: 不挑位置也不挑方位
    want_node, got_node = task.get("nodeId"), photo.get("nodeId")
    if want_node and got_node and want_node != got_node:
        return False, "node"
    if not _task_accepts_yaw(task, photo.get("yaw")):
        return False, "yaw"
    return True, None


def _range_direction(rng):
    """把一个圆环区间说成人话方位(取环形中点)。跨 0 度也对: [300,59] 的中点是 359.5°。"""
    if not rng or len(rng) != 2:
        return ""
    s, e = float(rng[0]) % 360, float(rng[1]) % 360
    return yaw_to_direction((s + ((e - s) % 360) / 2.0) % 360)


def _node_name(space, node_id):
    """节点的人话名字(新人建节点时起的, 比如"大厅")。没有就退回节点 id, 再没有就空串。"""
    if not node_id:
        return ""
    n = next((n for n in space.get("nodes", []) if n.get("id") == node_id), None)
    return ((n.get("name") or "").strip() or node_id) if n else node_id


def _photo_landing(photo):
    """这张照片【此刻真实】在哪儿, 一句人话(不带句号, 调用方自己接标点)。

    ⚠️ 2026-07-25 修的 P1: 这句话以前写死成"照片已经收下并放进空间里了", 而
    _mismatch_note 是在状态判断【之前】跑的, 于是一张被判 needs_review 的低置信度照片
    也会拿到这句 —— 它此刻在新人的待审队列里, 根本不在空间里, 还可能被拒掉。
    同一个文件里 recompute_contributors 的注释自己写着"待审 = 正在等新人过目,
    宾客端回执必须把话说清楚", 两处自相矛盾。现在按 photo["state"] 分支说实话。
    """
    st = photo.get("state")
    if st in SELECTED_STATES:
        return "照片已经收下并放进空间里了"
    if st == "needs_review":
        return "照片收下了,机器拿不准是不是在这儿拍的,正在等新人过目"
    if st in ("rejected", "quarantined"):
        return "这张照片没有被收进空间"
    return "照片收下了"


def _mismatch_note(space, task, photo, kind="yaw"):
    """认领对不上时(方位不符 kind="yaw" / 根本不在一个位置 kind="node"), 给宾客的如实说明。

    照片照收照定位, 只是不算完成这个任务 —— 既不静默丢弃, 也不假装成功。
    前端怎么显示不归这里管, 这里只负责把真相给出去(message 是可以直接念的人话)。
    字段只增不改: 老前端(server/join.html mismatchOf)读的 taskId/taskTitle/
    wantDirection/wantYawRange/photoDirection/photoYaw/message 全部原样保留。
    """
    want_yaw = task.get("yaw")
    want_dir = (yaw_to_direction(want_yaw) if want_yaw is not None
                else _range_direction(task.get("yawRange")))
    got = photo.get("yaw")
    got_dir = yaw_to_direction(got) if got is not None else ""
    title = task.get("title") or "这个任务"
    landing = _photo_landing(photo)
    want_node, got_node = task.get("nodeId"), photo.get("nodeId")
    want_place, got_place = _node_name(space, want_node), _node_name(space, got_node)

    if kind == "node":
        # 位置对不上。方位说得再准也没用, 先把"不是同一个地方"讲清楚。
        where = f"是在「{got_place}」拍的" if got_place else "是在另一个位置拍的"
        want_where = f"要的是「{want_place}」那边" if want_place else "要的是另一个位置"
        msg = (f"这张照片系统认出来{where},而「{title}」{want_where},"
               f"不是同一个地方,所以这次没算完成它。{landing}。"
               + (f"想拿这份悬赏的话,走回「{want_place}」再拍一张。" if want_place else ""))
    elif got is None:
        msg = (f"系统没能认出这张照片是朝哪个方向拍的,所以这次没算完成「{title}」。"
               f"{landing}。")
    else:
        msg = (f"这张照片系统认出来是朝{got_dir}拍的(约 {got:.0f}°),"
               f"而「{title}」要的是{want_dir},所以这次没算完成它。"
               f"{landing}。想拿这份悬赏的话,站在原地转向{want_dir}再补一张。")
    return {
        "taskId": task.get("id"),
        "taskTitle": task.get("title") or "",
        "wantDirection": want_dir,
        "wantYawRange": task.get("yawRange"),
        "photoDirection": got_dir,
        "photoYaw": got,
        # 下面五个是 7/25 新增的, 老前端不认就当没看见(它只读上面那几个 + message)
        "kind": kind,                       # "node" = 位置不符, "yaw" = 方位不符
        "wantNodeId": want_node,
        "wantNodeName": want_place,
        "photoNodeId": got_node,
        "photoNodeName": got_place,
        "photoState": photo.get("state"),
        "message": msg,
    }


def _task_unavailable_note(task_id, task, photo, kind):
    """客户端指定的任务不存在,或者已经不能再认领时,给宾客一份结构化实话。

    kind 只取 "missing" / "status"。照片仍然照常定位和分流,只是这次不能冒充完成
    那个任务。调用方会清掉 photo.taskId,再允许它按真实节点和方位顺手补上别的 open
    缺口,所以回执里必须保留 taskMismatch,前端才能把两件事同时说清楚。

    ⚠️ 2026-07-25 第三轮收口: kind="status" 现在【只】给 closed(缺口已经补齐、
    任务本身没了)。"任务已经被别人填过"不再走这里 —— 那不是错误,是婚礼现场的常态,
    见 _task_extra_note。下面那句 else 只是防御性兜底(理论上到不了),口吻也一并改成
    平铺直叙,不许再出现"不能重复领取悬赏"这种把宾客当贼的话。
    """
    landing = _photo_landing(photo)
    status = task.get("status") if task else None
    title = (task.get("title") or "这个任务") if task else "这个任务"
    if kind == "missing":
        msg = f"这份任务已经失效了,所以这次没算完成它。{landing}。"
    elif status == "closed":
        msg = f"「{title}」对应的方向已经补齐了,不用再认领。{landing}。"
    else:
        msg = f"「{title}」现在不接受新的认领了。{landing}。"
    return {
        "taskId": task_id,
        "taskTitle": (task.get("title") or "") if task else "",
        "kind": kind,
        "taskStatus": status,
        "photoState": photo.get("state"),
        "message": msg,
    }


def _task_extra_note(task, photo, batch_filled=None, mine=False):
    """任务【已经被填过】之后又来一张照片时的如实说明。这不是 taskMismatch,宾客没做错事。

    ⚠️ 2026-07-25 第三轮收口, 修的是上一轮自己修出来的 P0。上一轮把"任务已经 filled"
    当成了【拒绝后续照片】的理由, 于是最常见的三种正常行为全被当成了作弊:
      1. 宾客页自己写着"可以一次选好几张", 一次交 3 张给同一个任务时, 第 1 张把任务填掉,
         后 2 张立刻撞上【刚刚由它们自己造成的】filled 状态, 回执给的是
         "已经被认领了,不能重复领取悬赏"。一屏上同时出现"这个任务被你补上了 🎉"和
         两句指控, 自相矛盾;
      2. 两个宾客拍同一个方向 —— 婚礼现场同一个方向被两个人拍是常态, 不是攻击;
      3. 心愿任务天生该收很多张, 却变成了先到先得, 第二个人被拒。
    正确的模型: 状态只决定【悬赏发几份】, 不决定【照片收不收】, 更不该用指控的口吻说话。
    照片照常收下、照常归位、照常说好话, 只是同一份悬赏不重复发。

    kind 两取值, 前端可以用两种口吻渲染:
      "same_batch"     同一次上传里的后续张(是宾客自己刚刚填上的)。一个字都不提悬赏 ——
                       他没跟任何人抢, 提"不重复发"只会凭空制造一次挫败感;
      "already_filled" 这个方向别人先补上了(mine=True 时是他自己上一次补的)。
                       温和说明一句"这份悬赏之前发出去了", 让他知道为什么这张没加分。
    字段形状刻意和 _task_unavailable_note / _mismatch_note 对齐(taskId / taskTitle /
    kind / taskStatus / photoState / message), 前端一套渲染代码就能吃下三种。
    """
    tid = task.get("id")
    title = task.get("title") or "这个任务"
    wish = not _task_is_located(task)
    same_batch = bool(batch_filled) and tid in batch_filled

    if same_batch:
        kind = "same_batch"
        msg = ("这几张是同一次交的,都收下了,一起放进这份心愿里。" if wish
               else "这几张是同一次交的,都收下了,一起放进这个方向。")
    else:
        kind = "already_filled"
        if wish:
            msg = (f"「{title}」你之前已经交过照片了,这张也收下了,一起放进空间。"
                   if mine else
                   f"「{title}」已经有人响应过了,你这张也收下了,一起放进空间。"
                   "这份悬赏之前发出去了,不会再发第二份。")
        elif mine:
            msg = "这个方向你之前已经补上了,这张也收下了,一起放进空间。"
        else:
            msg = ("这个方向已经有人补上了,你这张也收下了,一起放进空间。"
                   "这份悬赏之前发出去了,不会再发第二份。")
    return {
        "taskId": tid,
        "taskTitle": task.get("title") or "",
        "kind": kind,
        "taskStatus": task.get("status", "open"),
        "taskType": task.get("type"),
        "bountyPaid": False,        # 这张没有再拿一份悬赏, 前端别显示加分动画
        "photoState": photo.get("state"),
        "message": msg,
    }


def apply_task_fill(space, photo, batch_filled=None):
    """照片真进空间之后, 判定它完成了哪个任务。返回【这一张真的拿到了悬赏】的 task id。

    只有【已入选】的照片才算数 —— 待审的照片先不动任务状态, 等新人 approve 了再算,
    不然一张机器都拿不准的照片就能把悬赏关掉, 任务系统就废了。

    ⚠️ 2026-07-25 修的 P0: 认领【必须校验方位】。以前拿客户端给的 taskId 就直接写
    filledBy、发悬赏, 从不看照片到底朝哪拍。实测在一个只有一张全景的空间里点
    t1「正前方」(区间 [300,59]), 传一张系统自己算出 yaw=193.9「正后方」的照片,
    t1 照样变 filled、照样给分、墙上照样显示已认领, 而正前方至今零照片 ——
    "系统指挥人把没拍到的方位补齐"这个核心卖点就断在这一行上(s20 历史数据里 13 处)。
    现在方位不符就不算完成那个任务, 但照片照常收下照常定位, 并把原因写进
    photo["taskMismatch"], 由上传接口原样带回给宾客。

    ⚠️ 2026-07-25 第二轮收口: 上面那道闸只比了【方位】, 没比【节点】, 于是同一个 P0
    换个姿势就复活了 —— 从 n2 拍的照片照样能认领 n1 的任务(见 _task_accepts_photo)。
    闸门现在统一走 _task_accepts_photo(节点 + 方位一起校验), 心愿任务不受影响。

    ⚠️ 2026-07-25 第三轮: 上一轮那道状态闸【修过头了】, 误伤了最常见的正常行为(一次交
    好几张 / 两个宾客拍同一个方向 / 心愿任务收第二张), 复现和根因见 _task_extra_note。
    现在的口径 ——
      · "任务已经被填过"【不是】拒绝照片的理由: 照片照常收下、照常归位、照常记 taskId,
        只是不重复发同一份悬赏, 回执走中性的 photo["taskNote"](不是指控式的 taskMismatch);
      · 只有 closed(缺口已经被系统判定补齐、任务本身没了)才继续挡住认领;
      · 心愿任务永远停在 open, 后来的照片继续收,但一条心愿只发一份悬赏。
        contributor 是宾客自己填写的名字,按名字发多份会被改昵称无限刷分。
    batch_filled 是【同一次上传里前面几张已经填掉的 task id 集合】, 只用来挑该说哪句话:
    自己刚填上的和别人先填上的, 得用两种口吻。
    """
    photo.pop("taskMismatch", None)     # 每次重算, 别留上一轮的陈旧结论
    photo.pop("taskNote", None)
    requested_task_id = photo.get("taskId")
    task = _find_task(space, requested_task_id) if requested_task_id else None

    # 野 taskId 不能静默残留,也不能冒充成别的任务成功。照片照常收下,如果它按真实
    # 节点和方位正好补上另一个 open 缺口,下面的自动判定仍会如实返回那个任务。
    if requested_task_id and task is None:
        photo["taskMismatch"] = _task_unavailable_note(
            requested_task_id, None, photo, kind="missing")
        photo["taskId"] = None

    # closed = 这一段方位已经被别的照片铺满、系统自己把任务关掉了, 缺口不存在了,
    # 再挂着"认领"就是骗人。这一条【必须留着】。filled 不在这里挡 —— 它是正常情况,
    # 走下面的悬赏口径。legacy 任务没 status 时按 open 处理。
    if task is not None and task.get("status", "open") == "closed":
        photo["taskMismatch"] = _task_unavailable_note(
            requested_task_id, task, photo, kind="status")
        photo["taskId"] = None
        task = None

    # 客户端说"这张是来完成 t1 的", 但照片实际可能压根不在 t1 那个节点、
    # 或者方向根本不在 t1 要的区间里。对不上就撤销这次认领(taskId 清掉), 下面照样走
    # 自动判定 —— 万一它正好补上了【它自己所在节点】的别的缺口, 那份悬赏是它该得的。
    if task is not None:
        ok, why = _task_accepts_photo(task, photo)
        if not ok:
            photo["taskMismatch"] = _mismatch_note(space, task, photo, kind=why)
            photo["taskId"] = None
            task = None

    if photo.get("state") not in SELECTED_STATES:
        return None

    # 没指定 taskId(或者指定的那个节点/方位对不上)就自动判定:
    # 照片 yaw 落进【同一个节点】某个 open 的 gap 任务的 yawRange 里
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
    wish = not _task_is_located(task)
    status = task.get("status", "open")

    # 心愿任务("我想要一张我妈的笑"这种)没有"填满"这回事: 新人开口要的就是很多张,
    # 状态一律留在 open, 它才不会从任务墙的"还缺"里消失、让后来的人连按钮都看不到。
    # 老数据里已经被填成 filled 的心愿任务, 下次有人交照片时顺手改回来。
    if wish and status != "open":
        task["status"] = status = "open"

    # ---- 悬赏口径:一条任务只发一份,状态不决定后续照片收不收 ----
    # gap 和 wish 的后续照片都照收照放,但 filledBy 只留一位获奖人。
    # 心愿不能按 contributor 名字“每人一份”:名字来自无认证表单,同一个人改一次昵称
    # 就会被当成新人再领一份。要做多人悬赏必须先有不可随手更换的身份凭据,当前没有。
    credited = False
    if not task["filledBy"] and status != "closed":
        task["filledBy"].append(who)
        credited = True
    if not wish and status == "open":
        task["status"] = "filled"

    if not credited:
        # 照片已经归位了(taskId 就在上面写好了), 只是这一张没有再拿一份悬赏。
        # 用中性的 taskNote 说明, 别用 taskMismatch —— 那个字段名本身就带着"你错了"。
        photo["taskNote"] = _task_extra_note(
            task, photo, batch_filled=batch_filled, mine=(who in task["filledBy"]))
        return None
    return task["id"]


def _overlapping_open_task(space, task):
    """这一片方位是不是已经有【另一条 open 的 gap 任务】盯着了。有就返回那一条。

    判据和 sync_gap_tasks 里发任务时的去重完全一致(同节点 + open 的 gap + 区间重叠),
    一把尺子, 免得两处判断打架。
    """
    rng = task.get("yawRange")
    if not rng or len(rng) != 2:
        return None
    for t in space.get("tasks", []):
        if (t is task or t.get("nodeId") != task.get("nodeId")
                or t.get("type") != "gap" or t.get("status") != "open"):
            continue
        if _ranges_overlap(rng, t.get("yawRange")):
            return t
    return None


def _release_task_fill(space, photo):
    """这张照片【不再算数】了(新人拒了它), 把它填过的任务退回去。返回被退回的 task id。

    ⚠️ 2026-07-25 修的 P2: reject 分支以前只改 photo["state"], 一个字都不碰任务。
    实测(s10001): 把 p6 拒掉之后 t3 依然是 filled / filledBy=["复验-擦边哥"],
    而 recompute_contributors 按 status in ("filled","closed") 照发 50 分, 于是贡献榜上
    出现「复验-擦边哥 · 0 张 · 50 分」—— 一张照片都没进空间的人挂着 50 分的悬赏。
    更要命的是缺口: _close_stale_gap_tasks 只看 status=="open", filled 的一律不看,
    所以这条任务永远不会回到任务墙上, 那个方向从此没人再去补。

    退回的口径 —— filledBy 里存的是【获奖人名】不是照片 id, 所以真值要从照片反推:
    "还入选着、且 taskId 指着这个任务"的照片, 才有资格支撑这份悬赏。
      · 原获奖人还有别的入选照片 -> 继续保留;
      · 原获奖人没有了、但有合法后续照片 -> 最早留下的人接棒;
      · 一张合法照片都不剩 -> filledBy 清空, gap 重新开放,心愿继续保持 open。
    照片自己的 taskId 【故意不清】: 它是"这张当初认领的是哪一条"的记录, 新人反悔再点通过时,
    apply_task_fill 会拿它重新校验一遍(节点 + 方位)再决定给不给分。
    """
    tid = photo.get("taskId")
    task = _find_task(space, tid) if tid else None
    if task is None:
        return None
    still = []
    for p in space.get("photos", []):
        if p is photo or p.get("taskId") != tid or p.get("state") not in SELECTED_STATES:
            continue
        name = p.get("contributor") or "匿名宾客"
        if name not in still:
            still.append(name)
    # 原获奖人还有合法照片就继续保留。否则最早留下的合法后续照片接棒,
    # 不能出现方向已经有人补上、悬赏却凭空蒸发的状态。
    winner = next((w for w in task.get("filledBy", []) if w in still), None)
    if winner is None and still:
        winner = still[0]
    task["filledBy"] = [winner] if winner else []

    # 心愿永远继续收照片,但悬赏仍只有上面那一位获奖人。
    if not _task_is_located(task):
        task["status"] = "open"
        task.pop("closedAt", None)
        task.pop("closedReason", None)
        return task["id"]

    if winner:
        task["status"] = "filled"
        task.pop("closedAt", None)
        task.pop("closedReason", None)
    elif task.get("status") in ("filled", "closed"):
        # ⚠️ 2026-07-25 修的 P1: 退回 open 之前必须先去重。以前这里无条件退回,
        # 而 sync_gap_tasks 的去重只在【新建】任务时做, 于是拒一张照片能造出两张重叠的
        # 悬赏卡。实测: t1[300,59] 被填上 -> 系统按新的覆盖版图补发了 t10[276,325] ->
        # 把那张照片拒掉 -> t1 原地退回 open, 此刻 t1 和 t10 区间重叠、各挂 +50,
        # 而 find_coverage_gaps 只认得出一个缺口。两张卡的文案是"转向正前方"和
        # "转向左前方", 人站在原地分不出这 30 度差别, 同一张照片能卖两次悬赏。
        # 已经有别的 open 任务盯着这一片, 就把这条关掉(缺口没被吞掉, 那条还在广播)。
        dup = _overlapping_open_task(space, task)
        if dup is not None:
            task["status"] = "closed"
            task["closedAt"] = time.time()
            task["closedReason"] = f"这一片已经有任务 {dup['id']} 盯着了,不重复发悬赏"
        else:
            task["status"] = "open"
            # 关闭理由是上一任状态留下的, 任务都重新开着了还挂着"已关闭"的说辞会穿帮
            task.pop("closedAt", None)
            task.pop("closedReason", None)
    return task["id"]


def recompute_contributors(space):
    """整表重算贡献榜, 而不是到处 +=。

    这样"拒了又通过""同一张照片被处理两次"都不会把积分算重 —— 积分永远等于
    当前数据的函数。规则: 每张入选照片 BASE_POINTS 分; 完成任务的人额外拿一次该任务 bounty。

    ⚠️ 榜单口径(踩过的坑, 改之前先看完这段):
    只统计 SELECTED_STATES = ("auto_ok", "approved"), 也就是【真的已经出现在空间里】的照片。
    needs_review / quarantined / rejected 一律不计分, 也不上榜。
    这是有意的: 榜单代表"这个空间里的画面有多少是你贡献的", 待审的照片还没进空间,
    先给分等于承诺了一件新人还没点头的事, 万一后面被拒还得倒扣。

    由此产生一个必然的现象, 不是 bug: 一位宾客传的照片【全部】落进 needs_review 队列时,
    他在榜上是不存在的(不是 0 分, 是压根没这一行), 要等新人在审核台点了通过、
    review_photos 把状态改成 approved 并重新调用本函数, 他才会出现。
    宾客端(web/join.html)的上传回执因此必须把话说清楚: 待审 = 照片已收到、正在等新人过目,
    不是没收到, 也不是被拒了; 榜上暂时没有你的名字是这个原因。
    回执文案归 web/join.html 管, 这里【只管统计】。要改"待审也上榜"就得连回执、
    积分倒扣、任务悬赏发放(apply_task_fill 同样只认 SELECTED_STATES)一起重新设计,
    别只动这一个函数。
    """
    tally = {}

    def bump(name, photos=0, points=0):
        rec = tally.setdefault(name, {"name": name, "photos": 0, "points": 0})
        rec["photos"] += photos
        rec["points"] += points

    for p in space.get("photos", []):
        if p.get("state") in SELECTED_STATES:
            bump(p.get("contributor") or "匿名宾客", photos=1, points=BASE_POINTS)

    # 悬赏按 filledBy 发,不按 status 发。心愿为了继续收照片会一直 open。
    # 但一条任务只认第一位获奖人,也顺手防住历史数据里重复名字造成的多发。
    for t in space.get("tasks", []):
        for who in (t.get("filledBy", [])[:1]):
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
        if _normal_collection(space.get("collection"))["status"] != "open":
            raise RuntimeError("这个空间已经暂停收集照片")
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
    # ⚠️ 中途炸了必须把这一批占的位子全清干净: 占位文件 + 半张残图 + 缩略图。
    # 不清的话磁盘上会留一个打不开的残骸, 还白白占掉一个照片编号
    # (踩过: 一张坏图在 photos/ 里留了个 19 字节的 p2.jpg, p2 这个号从此报废)。
    paths = []
    try:
        for pid, (fname, ctype, raw) in zip(pids, files):
            dest = os.path.join(photos_dir, pid + ".jpg")
            save_photo_and_thumb(raw, dest, os.path.join(thumbs_dir, pid + ".jpg"))
            paths.append(dest)

        t0 = time.time()
        # 点任务上传时,客户端传来的 nodeId 表示“任务希望你去哪里拍”,不是照片实际
        # 属于哪个节点。拿它限制 CLIP bank 会形成循环论证:先强制只搜任务节点,再拿
        # 这个必然相同的结果做节点闸。
        #
        # 带 taskId 的认领必须全节点独立匹配,否则客户端把任务自己的 nodeId 一起传来,
        # 就会先把照片硬塞进目标节点、再用这个必然相同的结果做节点闸,形成循环论证。
        #
        # 不带 taskId 的自由投稿保留 nodeId 这个旧契约:调用者明确选了房间时只在该房间
        # 的 bank 里定位。把它也改成全节点会改变 margin 的比较集合,等效改了双判据行为,
        # 没重新标定之前不能顺手扩大。
        match_node_id = None if task_id else node_id
        placed = place_photos(
            sid, {"nodes": nodes_snapshot}, paths, node_id=match_node_id)
        clip_s = time.time() - t0
    except Exception:
        # 这时候还没往 space["photos"] 里写任何一条记录, 所以把文件删掉 = 编号也一起放回去
        for pid in pids:
            for junk in (os.path.join(photos_dir, pid + ".jpg"),
                         os.path.join(thumbs_dir, pid + ".jpg")):
                if os.path.exists(junk):
                    os.remove(junk)
        raise

    # 3) 回锁里落记录 + 分流 + 任务判定 + 积分
    out = []
    with space_txn(sid) as space:
        touched_nodes = set()
        # 这一次上传里已经被填上的 task id。宾客页自己写着"可以一次选好几张",
        # 一次交 3 张给同一个任务是常态: 第 1 张把任务填上, 后面两张撞上的是
        # 【它们自己刚造成的】filled 状态, 回执必须换一种口吻说(见 _task_extra_note),
        # 不能拿"已经被认领了"去指控一个什么都没做错的人。
        batch_filled = set()
        for pid, r in zip(pids, placed):
            conf = r["confidence"]
            margin = r.get("margin", 0.0)
            # 两个判据都要过。差哪个就在 reason 里说清楚差哪个 —— 新人在审核台上
            # 看到的是人话理由, 不是一个孤零零的数字。
            #
            # ⚠️ 数值和门槛【一律用 4 位小数】, 而且两边用同一个精度。踩过的坑:
            # 原来数值印 2 位、门槛直接印 0.82, 于是 conf=0.8198 的照片打印成
            # "匹配度只有 0.82(低于 0.82)", 观众会以为系统坏了。3 位也救不了
            # (0.8198 四舍五入还是 0.820, 跟 0.82 看着一样), 4 位才彻底不自相矛盾。
            # confidence/margin 落盘时就是 round(x, 4), 所以 4 位是无损的。
            if conf >= CONF_MIN and margin >= MARGIN_MIN:
                state = "auto_ok"
                reason = f"匹配度 {conf:.4f}、辨识度 {margin:.4f},两项都达标,自动入选"
            elif conf < CONF_MIN and margin < MARGIN_MIN:
                state = "needs_review"
                reason = (f"匹配度 {conf:.4f} 偏低(门槛 {CONF_MIN:.4f}),"
                          f"辨识度 {margin:.4f} 也偏低(门槛 {MARGIN_MIN:.4f}),"
                          f"这张很可能不是在这个空间拍的,请你看一眼")
            elif margin < MARGIN_MIN:
                state = "needs_review"
                reason = (f"匹配度 {conf:.4f} 够高,但辨识度只有 {margin:.4f}"
                          f"(低于门槛 {MARGIN_MIN:.4f}):"
                          f"它跟这个空间哪个方向都差不多像,机器拿不准是不是这儿拍的")
            else:
                state = "needs_review"
                reason = (f"辨识度 {margin:.4f} 够,但匹配度只有 {conf:.4f}"
                          f"(低于门槛 {CONF_MIN:.4f}),"
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
            rewarded = apply_task_fill(space, photo, batch_filled=batch_filled)
            if rewarded:
                batch_filled.add(rewarded)
            rewarded_task = _find_task(space, rewarded) if rewarded else None
            # taskFilled 保持老接口语义:只表示一个有方位的 gap 任务真的完成了。
            # 心愿会一直 open,不能复用 taskFilled 再让前端说“任务被你补上了”。
            filled = rewarded if rewarded_task and _task_is_located(rewarded_task) else None
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
                # 新字段只做加法:这张是否拿到一份任务悬赏。心愿首次响应时
                # taskFilled 为 null、taskRewarded 为任务 id,老消费者不会误判任务完成。
                "taskRewarded": rewarded,
                "bountyPaid": bool(rewarded),
                # 宾客点了某个任务, 但照片的方位对不上 -> 这里如实说明为什么没算完成。
                # 老前端不认这个字段就当没看见(照片本身照常收下), 认的话可以直接念 message。
                "taskMismatch": photo.get("taskMismatch"),
                # 照片【归位了但没再拿一份悬赏】时的中性说明(同一次交的后续张 / 这个方向
                # 别人先补上了 / 心愿任务他之前交过)。和 taskMismatch 是两件事:
                # 那个是"对不上", 这个是"对上了, 只是悬赏不重复发", 口吻必须不一样。
                # 老前端不认它就当没看见 —— 这时 taskFilled 是 null、taskMismatch 也是 null,
                # 它会按普通入选照片渲染("已进入空间 ✅"), 不会说出自相矛盾的话。
                "taskNote": photo.get("taskNote"),
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

    reject 是 approve 的镜像, 三件事一件都不能少: 把它填过的任务退回去
    (_release_task_fill, 顺带收回悬赏)、重算积分、重算覆盖盲区 ——
    照片退出空间, 它当初补上的那段缺口就又空了, 必须重新广播出去。
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
                # 状态先改再退任务: _release_task_fill 按"还入选着的照片"反推 filledBy,
                # 这张自己得先不是入选状态(它另外也会被按对象身份跳过, 两道保险)。
                _release_task_fill(space, p)
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
    # total 是收到的总张数(含待审/被拒), selectedCount 才是【真的出现在空间里】的张数。
    # 两个数字不是一回事, 首屏要显示"这个空间有几张照片"用 selectedCount。
    stats["selectedCount"] = stats["autoOk"] + stats["approved"]
    return stats


def get_space(sid, role="host"):
    """role=guest 只返回已入选的照片(宾客看不到别人被拒的/待审的);
    role=host 全返回, 外加一份统计, 前端拿它显示"本次自动处理 12 张, 需要你看的只有 2 张"。"""
    with space_txn(sid, write=False) as space:
        data = copy.deepcopy(space)
    # 详情接口给全:cover 就算是几十 KB 的 dataURL 也原样返回(列表接口才省)。
    # 这里只补在返回的副本上, 不回写磁盘, 老空间的 space.json 一个字节都不动。
    for k, dflt in (("date", ""), ("place", ""), ("cover", ""), ("private", False)):
        data.setdefault(k, dflt)
    data["collection"] = _normal_collection(data.get("collection"))
    data["exhibition"] = _normal_exhibition(data.get("exhibition"))
    data["hasCover"] = bool(data.get("cover"))
    data["reportAvailable"] = os.path.exists(os.path.join(space_dir(sid), "report.json"))
    # 两种 role 都给 selectedCount(= 真的出现在空间里的照片数), 前端不用自己数、
    # 也不用拿 photos.length 猜(host 拿到的 photos 里还混着待审和被拒的)。
    data["selectedCount"] = sum(
        1 for p in space.get("photos", []) if p.get("state") in SELECTED_STATES)
    # 老数据里的心愿曾被首张照片写成 filled,宾客页因此把上传按钮藏掉,
    # 正常路径永远没有机会触发 apply_task_fill 的迁移。读接口时先把返回副本归一成 open,
    # 让后来的人仍能响应；下一次真实上传会把同样状态写回磁盘。
    for task in data.get("tasks", []):
        if not _task_is_located(task):
            task["status"] = "open"
    if role == "guest":
        data["photos"] = [p for p in data["photos"] if p.get("state") in SELECTED_STATES]
    else:
        data["stats"] = space_stats(space)
    return data


def publish_space(sid):
    with space_txn(sid) as space:
        space["published"] = True
        exhibition = _normal_exhibition(space.get("exhibition"))
        exhibition["status"] = "published"
        exhibition["updatedAt"] = time.time()
        space["exhibition"] = exhibition
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
    """尚未上云的空间使用本机宾客页。宾客扫码直接进 H5,不注册不装 app。"""
    return f"{public_base()}/server/join.html?space={sid}"


def canonical_guest_url(sid, space):
    """同一个空间只给一种入口:已上云走云宾客页,否则走本机宾客页。"""
    if space.get("ossSpaceJson"):
        return f"{CLOUD_JOIN_BASE}?s={quote(str(sid), safe='')}"
    return guest_url(sid)


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


def _guest_safe(msg):
    """这句话能不能直接摆到宾客手机上。

    放行条件: 是中文短句、不带路径、不带英文异常名。我们自己 raise 的那些
    ("空间 s99 不存在""这个空间还没有全景节点,请新人先传一张全景")本来就是人话,
    照原样给出去比换成套话有用得多; 系统异常的原文一律拦下。
    """
    if not msg or len(msg) > 80 or "\n" in msg:
        return False
    if any(bad in msg for bad in ("/", "\\", ":", "Error", "error", "Exception", "Traceback")):
        return False
    return any("一" <= ch <= "鿿" for ch in msg)


def _fail_user(e, fallback, tag):
    """给前端的错误一律中文人话:不带路径、不带异常类名、不带堆栈。

    ⚠️ 这是演示大屏上的硬穿帮点(踩过): PIL 的原始异常
    "cannot identify image file '/Users/xxx/code/.../photos/p2.jpg'" 被原样吐给
    join.html, 宾客手机上直接显示英文报错 + 主办电脑的用户名和目录结构。
    完整异常照旧打进服务端日志(带堆栈), 排查能力一点没丢。
    """
    print(f"== [space] {tag}出错: {type(e).__name__}: {e} ==", flush=True)
    traceback.print_exc()
    msg = str(e)
    if isinstance(e, UnidentifiedImageError) or "cannot identify image file" in msg:
        return _fail("这张图片打不开,换一张试试")
    return _fail(msg if _guest_safe(msg) else fallback)


@router.post("/space")
def api_create_space(payload: dict = Body(default={})):
    try:
        # title / couple 是老契约, 一字不动。
        # date / place / cover / private 全是可选加法:老调用只传 {title, couple} 时
        # payload.get() 全拿到 None, _clean_meta 把它们变成空值, 结果和以前一模一样。
        sid = create_space(
            payload.get("title"), payload.get("couple"),
            date=payload.get("date"), place=payload.get("place"),
            cover=payload.get("cover"), private=payload.get("private"),
        )
        return {"ok": True, "spaceId": sid}
    except Exception as e:
        return _fail_user(e, "空间没建成,稍后再试一次", "建空间")


@router.get("/spaces")
def api_list_spaces():
    try:
        return {"ok": True, "spaces": list_spaces()}
    except Exception as e:
        return _fail_user(e, "空间列表读不出来,刷新一下页面", "读空间列表")


@router.get("/space/{sid}")
def api_get_space(sid: str, role: str = "host"):
    try:
        return {"ok": True, "space": get_space(sid, role)}
    except FileNotFoundError as e:
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "读空间")
    except Exception as e:
        return _fail_user(e, "空间读不出来,刷新一下页面再试", "读空间")


@router.post("/space/{sid}/collection")
def api_collection(sid: str, payload: dict = Body(default={})):
    try:
        collection = set_collection_status(sid, payload.get("status"))
        return {"ok": True, "collection": collection}
    except FileNotFoundError as e:
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "改收集状态")
    except ValueError as e:
        return _fail(str(e))
    except Exception as e:
        return _fail_user(e, "收集状态没保存成功,再试一次", "改收集状态")


@router.post("/space/{sid}/exhibition")
def api_exhibition(sid: str, payload: dict = Body(default={})):
    try:
        exhibition = set_exhibition(sid, payload)
        return {"ok": True, "exhibition": exhibition}
    except FileNotFoundError as e:
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "保存展览")
    except ValueError as e:
        return _fail(str(e))
    except Exception as e:
        return _fail_user(e, "展览设置没保存成功,再试一次", "保存展览")


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
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "传全景")
    except Exception as e:
        return _fail_user(e, "这张全景没能处理,换一张再试试", "传全景")


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
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "宾客上传")
    except Exception as e:
        return _fail_user(e, "照片没能收下,换一张再试试", "宾客上传")


@router.post("/space/{sid}/task")
def api_create_task(sid: str, payload: dict = Body(default={})):
    try:
        task = create_wish_task(
            sid, payload.get("title"), payload.get("brief"), payload.get("bounty"),
        )
        return {"ok": True, "task": task}
    except FileNotFoundError as e:
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "发心愿任务")
    except Exception as e:
        return _fail_user(e, "心愿任务没发出去,再试一次", "发心愿任务")


@router.post("/space/{sid}/review")
def api_review(sid: str, payload: dict = Body(default={})):
    try:
        n = review_photos(sid, payload.get("decisions") or [])
        return {"ok": True, "updated": n}
    except FileNotFoundError as e:
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "审核")
    except Exception as e:
        return _fail_user(e, "审核没保存成功,再试一次", "审核")


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
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "发布")
    except Exception as e:
        return _fail_user(e, "发布没成功,再试一次", "发布")


# ---------------------------------------------------------------- 发布到云 + 工人心跳
#
# 云发布为什么要走后台线程 + 轮询: 首次全量发布实测 98 秒(这台机器传杭州只有 ~27KB/s)。
# 同步返回会让新人后台的 fetch 干等一分半, 看着像卡死。所以 POST 只负责"点火",
# 进度写在内存里, 前端 GET 轮询画进度条。
_cloud_state = {}          # sid -> {running, done, total, key, result, error, at}
_cloud_lock = threading.Lock()
_worker_processes = {}      # sid -> Popen, 只负责本次服务进程启动的工人
_worker_lock = threading.Lock()


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
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "云发布点火")
    except Exception as e:
        return _fail_user(e, "云发布没起来,再试一次", "云发布点火")


@router.get("/space/{sid}/publish-cloud")
def api_publish_cloud_state(sid: str):
    """轮询云发布进度。state 里有 running/done/total/result/error。"""
    return {"ok": True, "state": _cloud_get(sid)}


def worker_status(sid):
    path = os.path.join(space_dir(sid), ".worker.json")
    try:
        with open(path, encoding="utf-8") as f:
            hb = json.load(f)
        age = time.time() - float(hb.get("at") or 0)
        return {"running": age < 60, "ageS": round(age, 1),
                "pid": hb.get("pid"), "note": hb.get("note") or ""}
    except Exception:
        return {"running": False, "ageS": None, "pid": None, "note": ""}


def start_worker(sid):
    """给 Studio 一个真正的一键开工入口。标准输出丢弃, 避免云配置落进日志。"""
    with space_txn(sid, write=False):
        pass
    current = worker_status(sid)
    if current["running"]:
        return False, current.get("pid")

    python = os.path.join(REPO_ROOT, ".venv", "bin", "python")
    if not os.path.exists(python):
        raise RuntimeError("本地运行环境不完整")
    with _worker_lock:
        proc = _worker_processes.get(sid)
        if proc is not None and proc.poll() is None:
            return False, proc.pid
        proc = subprocess.Popen(
            [python, "-m", "server.worker", sid, "--interval", "5"],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _worker_processes[sid] = proc
        return True, proc.pid


@router.get("/space/{sid}/worker-status")
def api_worker_status(sid: str):
    """后台工人还活着吗? —— 工人(server/worker.py)每轮往空间目录写一次 .worker.json,
    60 秒内有心跳就算在跑。忘了起工人的话宾客传的照片永远不会出现, 这一格必须显眼。"""
    try:
        with space_txn(sid, write=False):
            pass
        return {"ok": True, **worker_status(sid)}
    except FileNotFoundError as e:
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "读工人状态")
    except Exception as e:
        return _fail_user(e, "工人状态读不出来,刷新一下页面", "读工人状态")


@router.post("/space/{sid}/worker/start")
def api_worker_start(
    sid: str,
    request: Request,
    payload: dict = Body(default={}),
):
    """工人会占用一份 CLIP 内存,只允许从这台主办方电脑点火。"""
    try:
        client_host = request.client.host if request.client else ""
        if not ipaddress.ip_address(client_host).is_loopback:
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "只能在主办方电脑上启动处理工人"},
            )
    except ValueError:
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "只能在主办方电脑上启动处理工人"},
        )
    try:
        started, pid = start_worker(sid)
        return {"ok": True, "started": started, "pid": pid}
    except FileNotFoundError as e:
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "启动工人")
    except Exception as e:
        return _fail_user(e, "处理电脑没能启动,检查本地环境", "启动工人")


@router.get("/space/{sid}/joinurl")
def api_joinurl(sid: str):
    try:
        with space_txn(sid, write=False) as space:
            url = canonical_guest_url(sid, space)
        return {"ok": True, "url": url}
    except FileNotFoundError as e:
        return _fail_user(e, "找不到这个空间,链接可能已经过期了", "生成宾客链接")
    except Exception as e:
        return _fail_user(e, "宾客链接没生成出来,刷新一下页面", "生成宾客链接")


os.makedirs(SPACES_DIR, exist_ok=True)
