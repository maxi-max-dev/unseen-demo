#!/usr/bin/env python3
"""
server/compose_server.py -- "上传即合成"本地服务。

用户在 upload.html 传一张全景(图/视频)+ 几张照片 -> 本地 AI 全自动:
  1. 全景标准化成 pano.jpg(视频抽第 1 帧)。
  2. 复用 tools/slice.py 的 equirect_to_perspective 把 pano 切成 12 张透视裁切图(FOV=70,
     yaw 0..330 每 30 度一张),用 CLIP(clip-ViT-B-32,复用 tools/slice.py 同款模型)编码;
     每张上传照片也编码,和 12 张裁切算余弦相似度,复用 tools/match.py 的 match_one() 逻辑
     挑最佳 yaw + 置信度(单全景=单节点,不需要跨节点判断)。
  3. subprocess 调 .venv-dap/bin/python tools/depth.py 跑 DAP 深度模型,产出 depth.png/depth.json。
  4. 写 manifest.json,前端 viewer/walk.html?compose=<manifestUrl> 直接读取渲染。

跑法: .venv/bin/python -m uvicorn server.compose_server:app --host 0.0.0.0 --port 8777
      (cwd 必须是仓库根目录,这样 REPO_ROOT 之外的相对路径假设才成立)

不改动 tools/ 下任何现有脚本,只 import 复用函数。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(REPO_ROOT, "server", "sessions")
DAP_PYTHON = os.path.join(REPO_ROOT, ".venv-dap", "bin", "python")
DEPTH_SCRIPT = os.path.join(REPO_ROOT, "tools", "depth.py")
DEPTH_ASSET_DIR = os.path.join(REPO_ROOT, "assets", "depth")
FFMPEG = "/opt/homebrew/bin/ffmpeg"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.slice import equirect_to_perspective, FOV, CROP_W, CROP_H, YAWS  # noqa: E402
from tools.match import match_one  # noqa: E402

os.makedirs(SESSIONS_DIR, exist_ok=True)

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

_session_lock = threading.Lock()
_clip_state = {}  # 启动时加载一次,别每次请求重加载


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("== 加载 CLIP (clip-ViT-B-32) ==", flush=True)
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    _clip_state["model"] = SentenceTransformer("clip-ViT-B-32")
    print(f"  CLIP 就绪, 耗时 {time.time()-t0:.1f}s", flush=True)
    yield
    _clip_state.clear()


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------- 工具函数
def next_session_id():
    """简单自增会话 id, 别用随机数/时间戳。"""
    with _session_lock:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        existing = [
            int(d) for d in os.listdir(SESSIONS_DIR)
            if d.isdigit() and os.path.isdir(os.path.join(SESSIONS_DIR, d))
        ]
        sid = str((max(existing) + 1) if existing else 1)
        os.makedirs(os.path.join(SESSIONS_DIR, sid))
        return sid


def guess_ext(filename, content_type):
    ext = os.path.splitext(filename or "")[1].lower()
    if ext:
        return ext
    if content_type == "image/png":
        return ".png"
    if content_type and content_type.startswith("video/"):
        return ".mp4"
    return ".jpg"


def is_video(filename, content_type):
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in VIDEO_EXTS:
        return True
    if content_type and content_type.startswith("video/"):
        return True
    return False


def save_panorama(raw_bytes, filename, content_type, session_dir):
    """落盘 + 标准化成 session_dir/pano.jpg。视频抽第 1 帧, 图片重编码成 jpg。"""
    ext = guess_ext(filename, content_type)
    raw_path = os.path.join(session_dir, "raw_panorama" + ext)
    with open(raw_path, "wb") as f:
        f.write(raw_bytes)

    pano_path = os.path.join(session_dir, "pano.jpg")
    if is_video(filename, content_type):
        cmd = [FFMPEG, "-y", "-i", raw_path, "-frames:v", "1", "-q:v", "2", pano_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(pano_path):
            raise RuntimeError(f"ffmpeg 抽帧失败: {r.stderr[-800:]}")
    else:
        img = Image.open(raw_path).convert("RGB")
        img.save(pano_path, quality=92)
    os.remove(raw_path)
    return pano_path


def clip_place_photos(pano_path, photo_paths):
    """CLIP 放置: 12 个 yaw 裁切 + 每张照片编码 + match_one 挑最佳 yaw/confidence。
    返回 (results, elapsed_s), results = [{yaw, confidence, sim}, ...] 与 photo_paths 一一对应。
    """
    model = _clip_state["model"]
    t0 = time.time()

    pano_img = Image.open(pano_path).convert("RGB")
    pano_np = np.asarray(pano_img)

    crops = []
    for yaw in YAWS:
        persp_np = equirect_to_perspective(
            pano_np, fov_deg=FOV, yaw_deg=yaw, pitch_deg=0, out_w=CROP_W, out_h=CROP_H,
        )
        crops.append(Image.fromarray(persp_np))

    crop_embs = model.encode(
        crops, batch_size=12, convert_to_numpy=True, normalize_embeddings=True,
    )
    crop_nodes = np.array(["pano"] * len(YAWS))
    crop_yaws = np.array(list(YAWS), dtype=np.int32)

    results = []
    if photo_paths:
        photo_imgs = [Image.open(p).convert("RGB") for p in photo_paths]
        photo_embs = model.encode(
            photo_imgs, batch_size=32, convert_to_numpy=True, normalize_embeddings=True,
        )
        for emb in photo_embs:
            sims = crop_embs @ emb
            _node, yaw, confidence, sim0 = match_one(sims, crop_nodes, crop_yaws)
            results.append({
                "yaw": round(float(yaw), 1),
                "confidence": round(float(confidence), 4),
                "sim": round(float(sim0), 4),
            })

    elapsed = time.time() - t0
    return results, elapsed


def run_depth(pano_path, session_dir, session_id):
    """subprocess 调 DAP, 输出挪进 session_dir/depth.png + depth.json。
    depth.py 固定把输出写到 assets/depth/<输入文件 basename>.*, 为避免多会话撞名,
    先把 pano 复制成一个带 session id 的临时输入名, 跑完再把结果搬进 session 目录、
    并删掉临时输入和 assets/depth/ 下的中间产物, 不污染仓库共享目录。
    返回 (elapsed_s, stdout_tail)。
    """
    t0 = time.time()
    tmp_name = f"_dap_in_{session_id}"
    tmp_input = os.path.join(session_dir, tmp_name + ".jpg")
    shutil.copy(pano_path, tmp_input)

    env = dict(os.environ)
    env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

    try:
        r = subprocess.run(
            [DAP_PYTHON, DEPTH_SCRIPT, tmp_input],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            raise RuntimeError(f"depth.py 退出码 {r.returncode}: {r.stderr[-1500:]}")

        src_png = os.path.join(DEPTH_ASSET_DIR, tmp_name + ".png")
        src_json = os.path.join(DEPTH_ASSET_DIR, tmp_name + ".json")
        if not (os.path.exists(src_png) and os.path.exists(src_json)):
            raise RuntimeError(f"depth.py 跑完但没找到输出文件: {src_png}")

        shutil.move(src_png, os.path.join(session_dir, "depth.png"))
        shutil.move(src_json, os.path.join(session_dir, "depth.json"))
        stdout_tail = r.stdout[-1500:]
    finally:
        if os.path.exists(tmp_input):
            os.remove(tmp_input)
        # 兜底清理: 就算中途出错也别把中间产物留在共享目录里
        for p in (
            os.path.join(DEPTH_ASSET_DIR, tmp_name + ".png"),
            os.path.join(DEPTH_ASSET_DIR, tmp_name + ".json"),
        ):
            if os.path.exists(p):
                os.remove(p)

    return time.time() - t0, stdout_tail


# ---------------------------------------------------------------- 路由(注意: 必须定义在
# app.mount("/", ...) 之前, 否则根挂载会先吃掉所有路径匹配, POST /compose 永远到不了这里)
@app.post("/compose")
async def compose(panorama: UploadFile = File(None), photos: list[UploadFile] = File(default=[])):
    if panorama is None:
        return JSONResponse({"ok": False, "error": "缺少 panorama 字段(全景图或全景视频)"})

    session_id = None
    try:
        session_id = next_session_id()
        session_dir = os.path.join(SESSIONS_DIR, session_id)
        photos_dir = os.path.join(session_dir, "photos")
        os.makedirs(photos_dir, exist_ok=True)

        print(f"== [{session_id}] 收到全景 {panorama.filename} ({panorama.content_type}) ==", flush=True)
        pano_bytes = await panorama.read()
        pano_path = save_panorama(pano_bytes, panorama.filename, panorama.content_type, session_dir)

        photo_files = [p for p in (photos or []) if p is not None and p.filename]
        photo_paths = []
        captions = []
        for i, p in enumerate(photo_files):
            ext = guess_ext(p.filename, p.content_type)
            if ext not in IMAGE_EXTS:
                ext = ".jpg"
            dest = os.path.join(photos_dir, f"{i+1:03d}{ext}")
            data = await p.read()
            with open(dest, "wb") as f:
                f.write(data)
            # 统一重编码成可靠的 jpg/png(防止奇怪格式/exif 方向问题拖垮前端 <img>)
            try:
                img = Image.open(dest).convert("RGB")
                img.save(dest, quality=90)
            except Exception:
                pass
            photo_paths.append(dest)
            captions.append(f"照片{i+1}")

        print(f"== [{session_id}] 上传 {len(photo_paths)} 张照片, 开始 CLIP 放置 ==", flush=True)
        clip_results, clip_elapsed = clip_place_photos(pano_path, photo_paths)
        print(f"   CLIP 放置耗时 {clip_elapsed:.2f}s", flush=True)

        print(f"== [{session_id}] 开始 DAP 深度 ==", flush=True)
        depth_elapsed, depth_log = run_depth(pano_path, session_dir, session_id)
        print(f"   DAP 深度耗时 {depth_elapsed:.2f}s", flush=True)

        photos_manifest = []
        for i, dest in enumerate(photo_paths):
            rel = os.path.relpath(dest, session_dir).replace(os.sep, "/")
            r = clip_results[i]
            photos_manifest.append({
                "src": rel,
                "yaw": r["yaw"],
                "pitch": 0,
                "confidence": r["confidence"],
                "by": "auto",
                "caption": captions[i],
            })

        manifest = {
            "panorama": "pano.jpg",
            "depth": "depth.png",
            "depthJson": "depth.json",
            "title": "我的空间",
            "photos": photos_manifest,
        }
        manifest_path = os.path.join(session_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        print(f"== [{session_id}] 合成完成 ==", flush=True)
        return JSONResponse({
            "ok": True,
            "session": session_id,
            "manifestUrl": f"/sessions/{session_id}/manifest.json",
            "viewUrl": f"/viewer/walk.html?compose=/sessions/{session_id}/manifest.json",
        })

    except Exception as e:
        print(f"== [{session_id}] 合成失败: {e} ==", flush=True)
        return JSONResponse({"ok": False, "error": str(e), "session": session_id})


# ---------------------------------------------------------------- 静态服务(必须最后挂载)
app.mount("/sessions", StaticFiles(directory=SESSIONS_DIR), name="sessions")
app.mount("/", StaticFiles(directory=REPO_ROOT, html=True), name="root")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8777)
