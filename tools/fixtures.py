#!/usr/bin/env python3
"""
fixtures.py -- 造合成测试素材,给「空间记忆·婚礼旅程」全链路今晚跑通用。
真实影石全景到之前,先用这个生成婚礼旅程四个环节的合成全景:
  1. 4 张 4096x2048 equirectangular 全景 (jieqin/chufa/yishi/yanxi),互相强区分,
     配色延续婚礼语境(接亲红金/出发晨橙/仪式香槟金白/宴席酒红烛光),
     且每张内部按 yaw 分 12 个 30 度扇区,扇区之间也强区分(颜色+图案+大字标注角度)。
  2. 从全景里用透视投影 (equirect -> perspective, FOV 70) 在已知 (node, yaw) 裁 16 张 800x600
     "手机照片",并加扰动(亮度、裁边、色偏)模拟真实拍摄。
  3. 真值写入 assets/photos/ground_truth.json。

依赖: pillow, numpy (pip3 install --user pillow numpy)
用法: python3 tools/fixtures.py
"""
import json
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont

random.seed(42)
np.random.seed(42)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANO_DIR = os.path.join(ROOT, "assets", "panos")
PHOTO_DIR = os.path.join(ROOT, "assets", "photos")
os.makedirs(PANO_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)

PANO_W, PANO_H = 4096, 2048
FONT_BIG = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
FONT_MED = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


# 左上角中文角标(scene['label'])用的 CJK 字体候选;FONT_BIG/FONT_MED (Arial 系) 不含中文字形,
# 直接用会画出方块(实测 stage.jpg 就是"□□□□□ / STAGE"),换一个真正带中文字形的字体即可。
FONT_LABEL_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def _font_label(size):
    for path in FONT_LABEL_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# 1. 生成四张强区分的 equirectangular 全景 -- 婚礼旅程四个环节
# ---------------------------------------------------------------------------

# 每张全景的场景配色 + 图案风格,四者必须一眼看出不是同一张;配色延续婚礼语境
SCENES = {
    "jieqin": {
        "name": "JIEQIN",
        "label": "新娘家·接亲",
        # 中国红 + 金: 接亲堵门的喜庆感
        "palette": [(196, 32, 38), (168, 20, 40), (214, 150, 40), (224, 180, 70)],
        "pattern": "dots",
    },
    "chufa": {
        "name": "CHUFA",
        "label": "车队·出发",
        # 晨光暖橙: 婚车队伍出发时的清晨光线
        "palette": [(224, 120, 40), (200, 90, 30), (240, 160, 60), (250, 190, 90)],
        "pattern": "stripes",
    },
    "yishi": {
        "name": "YISHI",
        "label": "礼堂·仪式",
        # 香槟金 + 白: 酒店礼堂拜堂仪式的庄重质感
        "palette": [(212, 190, 140), (180, 160, 110), (230, 215, 180), (245, 240, 225)],
        "pattern": "checker",
    },
    "yanxi": {
        "name": "YANXI",
        "label": "宴席厅·宴席",
        # 酒红 + 烛光暖黄: 喜宴大厅的灯光氛围
        "palette": [(120, 20, 30), (90, 15, 25), (200, 140, 40), (160, 40, 40)],
        "pattern": "diamond",
    },
}


def draw_sector_pattern(draw, x0, x1, h, color, pattern, seed):
    """在 equirect 画布的一个 30 度扇区 (像素列区间 [x0,x1)) 里画满密铺图案。"""
    rng = random.Random(seed)
    if pattern == "dots":
        r = 40
        step = 100
        for yy in range(0, h, step):
            for xx in range(x0, x1, step):
                jitter_x = rng.randint(-15, 15)
                jitter_y = rng.randint(-15, 15)
                cx, cy = xx + jitter_x, yy + jitter_y
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    elif pattern == "stripes":
        stripe_w = 60
        # 斜条纹: 用平行四边形近似,简单起见画竖直条纹再叠加对角线
        for xx in range(x0, x1, stripe_w * 2):
            draw.rectangle([xx, 0, min(xx + stripe_w, x1), h], fill=color)
        # 叠加对角细线增加区分度
        diag_color = tuple(min(255, c + 60) for c in color)
        for offset in range(x0 - h, x1, 120):
            draw.line([(offset, 0), (offset + h, h)], fill=diag_color, width=10)
    elif pattern == "checker":
        cell = 130
        toggle = False
        for yy in range(0, h, cell):
            row_toggle = toggle
            for xx in range(x0, x1, cell):
                if row_toggle:
                    c2 = tuple(min(255, c + 70) for c in color)
                    draw.rectangle([xx, yy, min(xx + cell, x1), min(yy + cell, h)], fill=c2)
                else:
                    draw.rectangle([xx, yy, min(xx + cell, x1), min(yy + cell, h)], fill=color)
                row_toggle = not row_toggle
            toggle = not toggle
    elif pattern == "diamond":
        # 菱形密铺(呼应喜庆窗棂/剪纸纹样),给宴席厅用
        size = 110
        row = 0
        for yy in range(-size, h + size, size):
            row_off = 0 if row % 2 == 0 else size // 2
            for xx in range(x0 - size, x1 + size, size):
                cx, cy = xx + row_off, yy + size // 2
                pts = [(cx, cy - size // 2), (cx + size // 2, cy), (cx, cy + size // 2), (cx - size // 2, cy)]
                draw.polygon(pts, fill=color)
            row += 1


def _fit_font(path, text, max_width, start_size, min_size=24):
    """从 start_size 开始缩小字号,直到 text 的渲染宽度 <= max_width。"""
    size = start_size
    dummy = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    while size > min_size:
        font = _font(path, size)
        bbox = dummy.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            return font
        size -= 4
    return _font(path, min_size)


def make_panorama(key):
    scene = SCENES[key]
    img = Image.new("RGB", (PANO_W, PANO_H), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    n_sectors = 12  # 每 30 度一个扇区
    sector_w = PANO_W // n_sectors
    palette = scene["palette"]
    max_text_w = sector_w * 0.86  # 留边,防止相邻扇区文字互相咬合

    for i in range(n_sectors):
        x0 = i * sector_w
        x1 = PANO_W if i == n_sectors - 1 else (i + 1) * sector_w
        color = palette[i % len(palette)]
        draw_sector_pattern(draw, x0, x1, PANO_H, color, scene["pattern"], seed=hash((key, i)) & 0xFFFF)

        # 扇区分界线,方便肉眼确认 30 度切割
        draw.line([(x0, 0), (x0, PANO_H)], fill=(0, 0, 0), width=6)

        # 大号角度标注,写在扇区中央水平位置、纵向居中偏上 (字号自适应,不越界到相邻扇区)
        yaw_deg = i * 30
        text = f"{yaw_deg:03d}°"
        font_big = _fit_font(FONT_BIG, text, max_text_w, start_size=150)
        tx = x0 + sector_w // 2
        ty = PANO_H // 2 - 300
        bbox = draw.textbbox((0, 0), text, font=font_big)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((tx - tw / 2, ty - th / 2), text, font=font_big, fill=(255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0))

        # 场景名称,写在扇区中央、纵向居中偏下 (同样自适应字号)
        font_med = _fit_font(FONT_MED, scene["name"], max_text_w, start_size=90)
        bbox2 = draw.textbbox((0, 0), scene["name"], font=font_med)
        tw2, th2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
        ty2 = PANO_H // 2 + 250
        draw.text((tx - tw2 / 2, ty2 - th2 / 2), scene["name"], font=font_med, fill=(255, 255, 0), stroke_width=5, stroke_fill=(0, 0, 0))

    # 顶部/底部加天地标注色带,防止上下颠倒
    draw.rectangle([0, 0, PANO_W, 40], fill=(255, 255, 255))
    draw.rectangle([0, PANO_H - 40, PANO_W, PANO_H], fill=(20, 20, 20))
    font_small = _font_label(60)  # 中文角标必须用带 CJK 字形的字体,否则画成方块
    draw.text((30, 40), f"{scene['label']} / {scene['name']}", font=font_small, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))

    path = os.path.join(PANO_DIR, f"{key}.jpg")
    img.save(path, quality=90)
    return path


# ---------------------------------------------------------------------------
# 2. equirect -> perspective 投影 (Equirec2Perspec 数学, numpy 手写)
# ---------------------------------------------------------------------------

def equirect_to_perspective(equirect_np, fov_deg, yaw_deg, pitch_deg, out_w, out_h):
    """
    equirect_np: (H, W, 3) uint8 array, x=0 对应 lon=0°, x=W 对应 lon=360°(环绕),
                 与 make_panorama() 画扇区标注时用的列约定一致 (列 0 = 000°, 从左到右递增)。
                 y=0 对应 lat=+90 (顶), y=H 对应 lat=-90 (底)。
    yaw_deg: 水平朝向, 0-360, 与 tour.js 的 yaw 同一约定 (0=全景第 0 列方向)。
    pitch_deg: 俯仰角, 正=向上看。
    返回 (out_h, out_w, 3) uint8 透视图。
    """
    eh, ew = equirect_np.shape[:2]
    fov = math.radians(fov_deg)
    theta = math.radians(yaw_deg)
    phi = math.radians(pitch_deg)

    # 相机局部坐标: x 右, y 上, z 前 (forward)
    aspect = out_h / out_w
    w_len = math.tan(fov / 2.0)
    h_len = w_len * aspect

    xs = (2 * (np.arange(out_w) + 0.5) / out_w - 1) * w_len          # (out_w,)
    ys = (1 - 2 * (np.arange(out_h) + 0.5) / out_h) * h_len          # (out_h,)
    xv, yv = np.meshgrid(xs, ys)                                     # (out_h, out_w)
    zv = np.ones_like(xv)

    norm = np.sqrt(xv ** 2 + yv ** 2 + zv ** 2)
    xv, yv, zv = xv / norm, yv / norm, zv / norm

    # pitch: 绕相机 x 轴旋转 (抬头看)
    y1 = yv * math.cos(phi) + zv * math.sin(phi)
    z1 = -yv * math.sin(phi) + zv * math.cos(phi)
    x1 = xv

    # yaw: 绕世界 y (竖直) 轴旋转
    x2 = x1 * math.cos(theta) + z1 * math.sin(theta)
    z2 = -x1 * math.sin(theta) + z1 * math.cos(theta)
    y2 = y1

    lon = np.arctan2(x2, z2)                     # -pi..pi
    lat = np.arcsin(np.clip(y2, -1.0, 1.0))       # -pi/2..pi/2

    # 注意: 不做 "+0.5" 居中偏移。make_panorama() 把列 0 当作 yaw=0 从左到右画到列 W 为 yaw=360,
    # 所以这里 src_x 也必须是列 0 = lon 0 的约定,否则求出的透视图会跟标注的 yaw 对不上
    # (实测过: 用居中约定时, 请求 yaw=15 实际会裁到标着 180°-210° 的扇区, 相差整 180 度)。
    src_x = (lon / (2 * math.pi)) * ew
    src_y = (0.5 - lat / math.pi) * eh

    src_x = np.mod(src_x, ew).astype(np.int32)
    src_y = np.clip(src_y, 0, eh - 1).astype(np.int32)

    return equirect_np[src_y, src_x]


# ---------------------------------------------------------------------------
# 3. 给裁出来的照片加扰动,模拟真实手机拍摄
# ---------------------------------------------------------------------------

def perturb_photo(img: Image.Image, rng: random.Random) -> Image.Image:
    w, h = img.size

    # a) 随机裁掉最多 10% 边 (每边独立随机 0-10%),再 resize 回原尺寸
    crop_frac = rng.uniform(0.0, 0.10)
    left = int(w * rng.uniform(0, crop_frac))
    top = int(h * rng.uniform(0, crop_frac))
    right = w - int(w * rng.uniform(0, crop_frac))
    bottom = h - int(h * rng.uniform(0, crop_frac))
    img = img.crop((left, top, right, bottom)).resize((w, h), Image.BILINEAR)

    arr = np.asarray(img).astype(np.float32)

    # b) 亮度 ±15%
    brightness = rng.uniform(0.85, 1.15)
    arr = arr * brightness

    # c) 轻微色偏 (每通道独立 ±8)
    for c in range(3):
        arr[:, :, c] += rng.uniform(-8, 8)

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("== 1. 生成全景 ==")
    pano_paths = {}
    for key in SCENES:
        p = make_panorama(key)
        size_kb = os.path.getsize(p) / 1024
        print(f"  {key}.jpg  {size_kb:.1f} KB")
        pano_paths[key] = p

    print("== 2. 裁透视照片 (FOV=70, 800x600) + 扰动 ==")
    # 每节点 4 张, 共 16 张, yaw 覆盖不同扇区, pitch 有轻微变化模拟手持
    # 文件名用 w 前缀(wedding),不与 AdventureX 旧素材 p001-p012 冲突,旧素材不删
    plan = [
        ("jieqin", 15, 0), ("jieqin", 105, 5), ("jieqin", 200, -5), ("jieqin", 320, 10),
        ("chufa", 30, 0), ("chufa", 140, -10), ("chufa", 250, 5), ("chufa", 340, 0),
        ("yishi", 10, 5), ("yishi", 95, 0), ("yishi", 190, -5), ("yishi", 300, 10),
        ("yanxi", 25, 0), ("yanxi", 115, -5), ("yanxi", 205, 5), ("yanxi", 325, 10),
    ]
    rng = random.Random(7)
    ground_truth = []
    for idx, (node, yaw, pitch) in enumerate(plan, start=1):
        pano_img = Image.open(pano_paths[node]).convert("RGB")
        pano_np = np.asarray(pano_img)
        persp_np = equirect_to_perspective(pano_np, fov_deg=70, yaw_deg=yaw, pitch_deg=pitch, out_w=800, out_h=600)
        persp_img = Image.fromarray(persp_np)
        persp_img = perturb_photo(persp_img, rng)

        fname = f"w{idx:03d}.jpg"
        fpath = os.path.join(PHOTO_DIR, fname)
        persp_img.save(fpath, quality=88)

        ground_truth.append({
            "file": fname,
            "node": node,
            "yaw": yaw,
            "pitch": pitch,
            "fov": 70,
        })
        print(f"  {fname}  node={node:8s} yaw={yaw:3d} pitch={pitch:3d}  -> {os.path.getsize(fpath)/1024:.1f} KB")

    gt_path = os.path.join(PHOTO_DIR, "ground_truth.json")
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, ensure_ascii=False, indent=2)
    print(f"== 3. 真值写入 {gt_path} ==")


if __name__ == "__main__":
    main()
