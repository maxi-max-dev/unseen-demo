#!/usr/bin/env python3
"""
server/video_ingest.py -- 全景视频 -> 一串空间节点(可走的路线)。

X5 边走边拍出来的是一段全景视频。把它每隔几秒抽一帧,每帧就是一张 equirectangular 全景,
串起来就是"沿着拍摄者走过的路一路走进去"。这一层只管抽帧和体检,不碰深度模型、不碰存储,
调用方(server/space.py)拿到帧列表后自己去跑 DAP、自己写进 space.json。

只依赖 ffmpeg/ffprobe(已装在 /opt/homebrew/bin)和 Pillow,不引入新包。

单独跑法(自测):
    .venv/bin/python -m server.video_ingest <视频路径> --out /tmp/frames --every 3
"""
import json
import os
import subprocess

from PIL import Image

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

# 全景视频的帧应该是 2:1 的 equirectangular。手机横屏视频(16:9)混进来会让后面整条链路
# 全是垃圾,所以在这里就拦住,容差给宽一点(±8%),别把边缘裁切过的素材误杀。
EQUIRECT_RATIO = 2.0
RATIO_TOLERANCE = 0.08

# 抽帧的默认间隔(秒)和上限。上限是保护:DAP 一帧要 1.6-2 秒,抽 60 帧就是两分钟起步,
# 现场演示等不起。宁可少抽几个节点,也别让新人对着转圈等。
DEFAULT_EVERY_S = 3.0
MAX_FRAMES = 12


class VideoIngestError(RuntimeError):
    pass


def probe(video_path):
    """读视频基本信息:时长/宽高/帧率。ffprobe 拿不到就直接抛,别猜。"""
    if not os.path.exists(video_path):
        raise VideoIngestError(f"视频文件不存在: {video_path}")

    cmd = [
        FFPROBE, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
        "-of", "json", video_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise VideoIngestError(f"ffprobe 失败: {r.stderr[-500:]}")

    try:
        data = json.loads(r.stdout)
        stream = (data.get("streams") or [{}])[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        duration = float((data.get("format") or {}).get("duration") or 0)
    except Exception as e:
        raise VideoIngestError(f"ffprobe 输出解析失败: {e}")

    if width <= 0 or height <= 0:
        raise VideoIngestError("读不到视频分辨率,可能不是有效的视频文件")

    ratio = width / height
    is_equirect = abs(ratio - EQUIRECT_RATIO) / EQUIRECT_RATIO <= RATIO_TOLERANCE

    return {
        "width": width,
        "height": height,
        "ratio": round(ratio, 3),
        "durationS": round(duration, 2),
        "isEquirect": is_equirect,
    }


def plan_frames(duration_s, every_s=DEFAULT_EVERY_S, max_frames=MAX_FRAMES):
    """算出要在哪几个时间点抽帧。

    规则:头尾各让开一点(视频开头结尾常常是手在动/在按快门),中间均匀取。
    帧数超过上限就自动拉大间隔——宁可节点稀疏,也不能让 DAP 跑到天荒地老。
    """
    if duration_s <= 0:
        return [0.0]

    # 头尾各让开 5%,但最多让 1.5 秒,短视频不能让没了
    margin = min(1.5, duration_s * 0.05)
    start = margin
    end = max(start, duration_s - margin)
    span = end - start

    if span <= 0.01:
        return [round(duration_s / 2, 2)]

    n = int(span // every_s) + 1
    if n > max_frames:
        n = max_frames
    if n < 1:
        n = 1

    if n == 1:
        return [round(start + span / 2, 2)]

    step = span / (n - 1)
    return [round(start + i * step, 2) for i in range(n)]


def extract_frames(video_path, out_dir, timestamps, prefix="f", quality=2):
    """按时间点逐帧抽出来存 jpg。

    用 -ss 放在 -i 前面走关键帧快速定位:精度差一点点无所谓(差几十毫秒的全景看不出来),
    但比逐帧解码快一个数量级,现场等不起。
    """
    os.makedirs(out_dir, exist_ok=True)
    frames = []

    for i, ts in enumerate(timestamps):
        dest = os.path.join(out_dir, f"{prefix}{i + 1:02d}.jpg")
        cmd = [
            FFMPEG, "-y",
            "-ss", str(ts),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", str(quality),
            dest,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(dest):
            # 单帧失败不该整段崩:末尾时间点越界是常见情况,跳过继续。
            continue

        try:
            with Image.open(dest) as img:
                w, h = img.size
        except Exception:
            os.remove(dest)
            continue

        frames.append({
            "index": len(frames) + 1,
            "path": dest,
            "timeS": ts,
            "width": w,
            "height": h,
        })

    if not frames:
        raise VideoIngestError("一帧都没抽出来,视频可能损坏或格式不支持")
    return frames


def ingest(video_path, out_dir, every_s=DEFAULT_EVERY_S, max_frames=MAX_FRAMES, prefix="f"):
    """全景视频 -> 帧列表。调用方拿这个列表去建节点。

    返回 {info, frames, warnings}。warnings 是给界面显示的人话提醒(比如"这段不像全景视频"),
    不是致命错误——素材不标准也让他先跑通,别在演示现场卡死一个人。
    """
    info = probe(video_path)
    warnings = []
    if not info["isEquirect"]:
        warnings.append(
            f"这段视频是 {info['width']}x{info['height']}(比例 {info['ratio']}),"
            "不像 2:1 的全景视频。可以继续,但走进去可能是歪的。"
        )
    if info["durationS"] > 180:
        warnings.append(f"视频有 {int(info['durationS'])} 秒,只会均匀取 {max_frames} 个节点。")

    stamps = plan_frames(info["durationS"], every_s=every_s, max_frames=max_frames)
    frames = extract_frames(video_path, out_dir, stamps, prefix=prefix)

    return {"info": info, "frames": frames, "warnings": warnings}


def suggest_node_names(frames):
    """给抽出来的节点起个临时名字,新人可以在后台改。

    没有语义信息可用,就老实按顺序和时间点命名,别编造"宴会厅""教堂"这种假地名。
    """
    names = []
    for f in frames:
        names.append(f"路线点 {f['index']} · 第 {int(f['timeS'])} 秒")
    return names


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="全景视频抽帧成一串空间节点")
    ap.add_argument("video")
    ap.add_argument("--out", default="/tmp/psm_frames")
    ap.add_argument("--every", type=float, default=DEFAULT_EVERY_S)
    ap.add_argument("--max", type=int, default=MAX_FRAMES)
    args = ap.parse_args()

    result = ingest(args.video, args.out, every_s=args.every, max_frames=args.max)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    for name in suggest_node_names(result["frames"]):
        print("  节点:", name)
