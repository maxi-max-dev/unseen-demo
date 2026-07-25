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
import hmac
import ipaddress
import os
import posixpath
import re
import shutil
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from starlette.concurrency import run_in_threadpool

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
from server.verify import verify_session  # noqa: E402
from server import space as space_mod  # noqa: E402  闭环产品(新人建空间/宾客交照片)的数据层 + API

os.makedirs(SESSIONS_DIR, exist_ok=True)

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# 自检环回头要用无头浏览器访问本服务自己的页面, 所以要知道自己的地址
SELF_URL = os.environ.get("PSM_SELF_URL", "http://127.0.0.1:8777")
HOST_PIN = os.environ.get("UNSEEN_HOST_PIN", "1111")
HOST_COOKIE_NAME = "unseen_host_demo"
HOST_COOKIE_TTL_S = 8 * 60 * 60

_session_lock = threading.Lock()
_clip_state = {}  # 启动时加载一次,别每次请求重加载
_verify_stage = {}  # 会话 id -> 自检环当前跑到哪一闸, 给上传页那条进度条读


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("== 加载 CLIP (clip-ViT-B-32) ==", flush=True)
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    _clip_state["model"] = SentenceTransformer("clip-ViT-B-32")
    print(f"  CLIP 就绪, 耗时 {time.time()-t0:.1f}s", flush=True)
    # 闭环那套(server/space.py)复用同一份 CLIP —— 不注入的话它会自己再加载一份,
    # 白等十几秒不说, 两份模型同时在 MPS 上跑还容易把进程打死。
    space_mod.set_clip_model(_clip_state["model"])
    # 发布时后台跑自检环, 要用它自己的地址去访问自己的页面, 和这里的 SELF_URL 保持一致。
    space_mod.set_self_url(SELF_URL)
    print("  闭环 API(/api/space/...) 已就绪, CLIP 已注入", flush=True)
    yield
    _clip_state.clear()


app = FastAPI(lifespan=lifespan)

# 闭环产品的全部 /api/... 接口。必须在下面的 app.mount("/") 之前 include ——
# 挂载点是按注册顺序匹配的, 根挂载一旦排在前面就会把所有路径都吃掉。
app.include_router(space_mod.router)


def _is_loopback_client(request):
    host = (request.client.host if request.client else "").split("%", 1)[0]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _host_request_allowed(request):
    if _is_loopback_client(request):
        return True
    supplied = request.headers.get("x-unseen-host-pin", "")
    if supplied and hmac.compare_digest(supplied, HOST_PIN):
        return True
    raw_cookie = request.cookies.get(HOST_COOKIE_NAME, "")
    try:
        raw_time, signature = raw_cookie.split(".", 1)
        issued_at = int(raw_time)
    except (ValueError, TypeError):
        return False
    if issued_at > int(time.time()) + 60 or time.time() - issued_at > HOST_COOKIE_TTL_S:
        return False
    expected = hmac.new(
        HOST_PIN.encode("utf-8"),
        f"unseen-host:{issued_at}".encode("utf-8"),
        "sha256",
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _public_api_request(request):
    path = request.url.path
    if request.method == "POST" and path in ("/api/host/login", "/api/host/logout"):
        return True
    if request.method == "POST" and re.fullmatch(r"/api/space/s\d+/upload", path):
        return True
    return bool(
        request.method == "GET"
        and re.fullmatch(r"/api/space/s\d+", path)
        and request.query_params.get("role") == "guest"
    )


@app.post("/api/host/login")
async def api_host_login(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    supplied = str(payload.get("pin") or "") if isinstance(payload, dict) else ""
    if not hmac.compare_digest(supplied, HOST_PIN):
        return JSONResponse({"ok": False, "error": "主办方口令无效"}, status_code=403)
    issued_at = int(time.time())
    signature = hmac.new(
        HOST_PIN.encode("utf-8"),
        f"unseen-host:{issued_at}".encode("utf-8"),
        "sha256",
    ).hexdigest()
    response = JSONResponse({"ok": True})
    response.set_cookie(
        HOST_COOKIE_NAME,
        f"{issued_at}.{signature}",
        max_age=HOST_COOKIE_TTL_S,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return response


@app.post("/api/host/logout")
def api_host_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(HOST_COOKIE_NAME, path="/")
    return response


def _guest_asset_allowed(sid, rel):
    """非本机访客只能读取 guest API 已经会引用的公开素材。"""
    if not re.fullmatch(r"s\d+", sid or ""):
        return False
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
        return False
    try:
        with space_mod.space_txn(sid, write=False) as space:
            allowed = set()
            for node in space.get("nodes") or []:
                for field in ("panorama", "depth", "depthJson"):
                    value = str(node.get(field) or "").lstrip("/")
                    if value:
                        allowed.add(value)
            for photo in space.get("photos") or []:
                if photo.get("state") not in space_mod.SELECTED_STATES:
                    continue
                for field in ("src", "thumb"):
                    value = str(photo.get(field) or "").lstrip("/")
                    if value:
                        allowed.add(value)
            exhibition = space_mod._normal_exhibition(space.get("exhibition"))
            task_visibility = exhibition["taskVisibility"]
            if task_visibility != "hidden":
                for task in space.get("tasks") or []:
                    visible = (
                        task_visibility == "all"
                        or task.get("status") == "filled"
                        or bool(task.get("filledBy"))
                    )
                    value = str(task.get("briefImage") or "").lstrip("/")
                    if visible and value:
                        allowed.add(value)
            return rel in allowed
    except (FileNotFoundError, ValueError):
        return False


@app.middleware("http")
async def protect_space_assets(request: Request, call_next):
    """堵住根静态挂载的旁路，并给局域网宾客套上和 guest API 相同的素材白名单。"""
    # 根 StaticFiles 会先 normpath，再去磁盘找文件。鉴权如果只看原始 URL，
    # `/server//spaces`、`/server/./spaces`、`/server/x/../spaces` 就能在这里
    # 漏过去，随后被静态服务归一到本机真值目录。鉴权必须使用同等级归一结果。
    raw_path = str(request.scope.get("path") or request.url.path or "/")
    path = posixpath.normpath("/" + raw_path.replace("\\", "/").lstrip("/"))
    if path == "/server/spaces" or path.startswith("/server/spaces/"):
        return Response(status_code=404)
    host_allowed = _host_request_allowed(request)
    request.state.unseen_host_allowed = host_allowed
    if path.startswith("/api/") and not host_allowed and not _public_api_request(request):
        return JSONResponse(
            {"ok": False, "error": "主办方口令无效"},
            status_code=403,
        )
    if path.startswith("/spaces/") and not host_allowed:
        parts = path[len("/spaces/"):].split("/", 1)
        allowed = (
            len(parts) == 2
            and await run_in_threadpool(_guest_asset_allowed, parts[0], parts[1])
        )
        if not allowed:
            return Response(status_code=404)
    return await call_next(request)


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

    🚨 编码一律走 space.clip_encode(), 别改回 model.encode()。
       整合之后这里和闭环那套(宾客上传)用的是【同一个】CLIP 模型对象, 而 PyTorch 的 MPS
       后端不是线程安全的 —— 两边各自开线程同时 encode, 进程会直接被 SIGSEGV 打死(退出码 139)。
       space.clip_encode() 是全服务唯一的串行入口, 谁绕过它谁就把整台服务器带走。
    """
    t0 = time.time()

    pano_img = Image.open(pano_path).convert("RGB")
    pano_np = np.asarray(pano_img)

    crops = []
    for yaw in YAWS:
        persp_np = equirect_to_perspective(
            pano_np, fov_deg=FOV, yaw_deg=yaw, pitch_deg=0, out_w=CROP_W, out_h=CROP_H,
        )
        crops.append(Image.fromarray(persp_np))

    crop_embs = space_mod.clip_encode(crops, batch_size=12)
    crop_nodes = np.array(["pano"] * len(YAWS))
    crop_yaws = np.array(list(YAWS), dtype=np.int32)

    results = []
    if photo_paths:
        photo_imgs = [Image.open(p).convert("RGB") for p in photo_paths]
        photo_embs = space_mod.clip_encode(photo_imgs, batch_size=32)
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


# ---------------------------------------------------------------- 自检环
def session_path(session_id):
    """会话目录的绝对路径; 路径逃出 sessions/ 就返回 None(sid 是 URL 里传进来的, 不能信)。"""
    root = os.path.realpath(SESSIONS_DIR)
    path = os.path.realpath(os.path.join(SESSIONS_DIR, session_id))
    return path if path == root or path.startswith(root + os.sep) else None


def kick_verify(session_id, fault=None):
    """后台线程里跑一遍自检环。绝不能阻塞 /compose 的返回 —— 用户那边等的是"合成好了",
    验收是合成之后机器自己的事, 慢慢跑就行。CLIP 用启动时加载好的那份, 别再加载一遍。"""
    def run():
        try:
            _verify_stage[session_id] = "queued"
            report = verify_session(
                session_id, base_url=SELF_URL, model=_clip_state.get("model"),
                inject_fault_kind=fault,
                on_stage=lambda stage, n: _verify_stage.__setitem__(session_id, stage),
            )
            print(f"== [{session_id}] 自检环裁决: {report['verdict']} — {report['reason']} ==", flush=True)
        except Exception as e:
            print(f"== [{session_id}] 自检环自己炸了: {type(e).__name__}: {e} ==", flush=True)
        finally:
            _verify_stage.pop(session_id, None)

    threading.Thread(target=run, daemon=True, name=f"verify-{session_id}").start()


# ---------------------------------------------------------------- 路由(注意: 必须定义在
# app.mount("/", ...) 之前, 否则根挂载会先吃掉所有路径匹配, POST /compose 永远到不了这里)
@app.get("/verify/{sid}")
async def get_verify(sid: str):
    """有 report.json 就把报告整份给出去; 没有就说还在跑, 并带上跑到哪一闸了。"""
    session_dir = session_path(sid)
    if session_dir is None:
        return JSONResponse({"error": "非法会话 id"}, status_code=400)
    report_path = os.path.join(session_dir, "report.json")
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as f:
            return JSONResponse(json.load(f))
    return JSONResponse({"status": "running", "stage": _verify_stage.get(sid, "queued")})


@app.post("/verify/{sid}")
async def rerun_verify(sid: str, request: Request):
    """重跑一次自检环。body 可选 {"fault": "photo"|"depth"|"manifest"} 做演示投毒。
    先把旧报告删掉, 否则前端一轮询就拿到上一次的结论, 会以为新的已经跑完了。

    🚨 安全: fault 是【故意破坏数据】的开关(把深度图刷成纯灰、往清单里塞外来照片、
    把 yaw 改成越界值)。这台服务会用 --host 0.0.0.0 起, 还可能挂公网隧道, 所以
    HTTP 侧默认不认这个参数 —— 否则任何拿到地址的人一条 curl 就能把用户的空间弄成砖,
    而且 HTTP 侧根本没有还原入口(--restore 只在命令行有)。
    要演示投毒: 起服务时加 PSM_DEMO_FAULT=1, 或者直接用 CLI 跑 python -m server.verify。
    """
    session_dir = session_path(sid)
    if session_dir is None or not os.path.isdir(session_dir):
        return JSONResponse({"ok": False, "error": "会话不存在"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    fault = (body or {}).get("fault")
    if fault:
        if os.environ.get("PSM_DEMO_FAULT") != "1":
            return JSONResponse(
                {"ok": False, "error": "投毒演示未开启(需要 PSM_DEMO_FAULT=1),已拒绝"},
                status_code=403,
            )
        if fault not in ("photo", "depth", "manifest"):
            return JSONResponse({"ok": False, "error": f"未知的投毒类型: {fault}"},
                                status_code=400)

    report_path = os.path.join(session_dir, "report.json")
    if os.path.exists(report_path):
        os.remove(report_path)
    kick_verify(sid, fault=fault)
    return JSONResponse({"ok": True, "status": "running", "session": sid,
                         "verifyUrl": f"/verify/{sid}"})
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

        print(f"== [{session_id}] 合成完成, 后台启动自检环 ==", flush=True)
        kick_verify(session_id)  # 后台线程, 不挡这次返回

        return JSONResponse({
            "ok": True,
            "session": session_id,
            "manifestUrl": f"/sessions/{session_id}/manifest.json",
            "viewUrl": f"/viewer/walk.html?compose=/sessions/{session_id}/manifest.json",
            "reportUrl": f"/server/report.html?session={session_id}",
            "verifyUrl": f"/verify/{session_id}",
        })

    except Exception as e:
        print(f"== [{session_id}] 合成失败: {e} ==", flush=True)
        return JSONResponse({"ok": False, "error": str(e), "session": session_id})


# ---------------------------------------------------------------- 静态服务(必须最后挂载)
# ⚠️ 顺序有讲究: 具体路径的挂载全部排在 "/" 之前, 否则根挂载会先命中, 后面的全废。
app.mount("/sessions", StaticFiles(directory=SESSIONS_DIR), name="sessions")
# 闭环的空间资源: 全景/深度图/照片/缩略图/通缉令裁切图/验收报告都在这下面,
# host.html 和 join.html 里的 assetUrl() 拼的就是 /spaces/<sid>/... 这个前缀。
app.mount("/spaces", StaticFiles(directory=space_mod.SPACES_DIR), name="spaces")
app.mount("/", StaticFiles(directory=REPO_ROOT, html=True), name="root")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8777)
