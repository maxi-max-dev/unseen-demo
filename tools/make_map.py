#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_map.py -- 生成「空间记忆·婚礼旅程」地图导航层的旅程地图。

苹果地图浅色系质感延续不变:米白底 + 柔和投影白色建筑块,但内容从「会场平面图」
换成「城市旅程图」:新娘家(左下院落)-> 出发(路点)-> 酒店(礼堂 + 宴席厅,右上建筑群),
一条圆头、暖红色调的粗路径蜿蜒串联四个环节,沿途点缀街区/绿地/水面,
路径上叠加实心箭头,表达"从家到酒店"的行进方向。

四个地名对应 tour.js 里的四个 node.map 归一化坐标(jieqin/chufa/yishi/yanxi),
两边坐标要对得上,否则地图上的光点会插到路的外面。

用法: python3 tools/make_map.py
输出: assets/map/journey.jpg (2048x1536) -- 新文件名,不覆盖旧 assets/map/venue.jpg
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "map")
OUT_PATH = os.path.join(OUT_DIR, "journey.jpg")

SCALE = 2                 # 超采样倍数
W, H = 2048, 1536         # 最终输出尺寸(需与 tour.js 里 TOUR.map.width/height 一致)
SW, SH = W * SCALE, H * SCALE

BG = (246, 244, 239)            # 米白底
STREET_FILL = (233, 229, 221)   # 街区色块,比米白底深一点,城市肌理
GRASS_FILL = (204, 231, 199)    # 浅绿草地
WATER_FILL = (185, 222, 240)    # 淡蓝水面
BUILDING_FILL = (255, 255, 255)
BUILDING_EDGE = (225, 222, 214)
HOME_FILL = (250, 231, 224)     # 新娘家院落:淡玫瑰白,呼应喜庆但不抢路线的红
HOME_EDGE = (214, 150, 130)
LABEL_COLOR = (108, 106, 98)
LABEL_STRONG = (150, 46, 44)    # 关键地名(新娘家/酒店)强调色,呼应喜庆红

# 婚车路线三段配色:正红 -> 朱红 -> 暖红渐金,全程不出"暖红色调"这个大类,
# 只是逐段变亮变暖,表达"从家到酒店"的行进渐变(配合下面的箭头一起表达方向)。
PATH_SEGMENTS_COLOR = [
    {"edge": (176, 48, 46), "fill": (198, 74, 66)},    # 新娘家 -> 出发: 正红/胭脂红(最浓)
    {"edge": (196, 74, 56), "fill": (214, 100, 76)},   # 出发 -> 礼堂: 朱红偏暖
    {"edge": (206, 104, 62), "fill": (224, 132, 88)},  # 礼堂 -> 宴席厅: 暖红收尾,略透金
]
ARROW_COLOR = (150, 32, 30)     # 比路径边线更深的正红,箭头清晰可辨方向

# 四个节点在归一化坐标系里的位置,必须和 tour.js 的 node.map.{x,y} 完全一致
NODE_POS = {
    "jieqin": (0.13, 0.80),   # 新娘家
    "chufa": (0.46, 0.60),    # 出发(路点)
    "yishi": (0.77, 0.22),    # 礼堂
    "yanxi": (0.90, 0.32),    # 宴席厅
}

FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def soft_shadow(base_rgba, box, radius, blur, offset, opacity):
    """在 base_rgba(RGBA Image)上给一个圆角矩形/圆区域画柔和投影,原地合成。"""
    layer = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    d.rounded_rectangle(
        (x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]),
        radius=radius, fill=(0, 0, 0, opacity),
    )
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    base_rgba.alpha_composite(layer)


def thick_path(draw, points, width, fill):
    """粗线连接多点并在每个折点补圆头,模拟苹果地图小径的圆润笔触。"""
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=fill, width=width, joint="curve")
    r = width // 2
    for (x, y) in points:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def soft_blob(size, polygon_pts, blur):
    """把多边形画到独立蒙版上再高斯模糊,把生硬的折角揉成水面那种圆润轮廓。
    返回一张同尺寸的 L 模式蒙版(0~255),供 Image.composite 用。"""
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(polygon_pts, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur))


def path_point(t, pts):
    """在折线 pts 上按累计弧长比例 t(0..1) 取点坐标和切线方向(弧度)。"""
    seg_len = []
    total = 0.0
    for i in range(len(pts) - 1):
        d = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        seg_len.append(d)
        total += d
    target = total * t
    acc = 0.0
    for i, d in enumerate(seg_len):
        if acc + d >= target or i == len(seg_len) - 1:
            local_t = (target - acc) / d if d > 0 else 0.0
            x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * local_t
            y = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * local_t
            ang = math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0])
            return x, y, ang
        acc += d
    return pts[-1][0], pts[-1][1], 0.0


def draw_arrow(draw, x, y, angle, size, color):
    """在 (x,y) 画一个指向 angle(弧度)的实心三角箭头,表达路线前进方向。"""
    tip = (x + math.cos(angle) * size, y + math.sin(angle) * size)
    back = (x - math.cos(angle) * size * 0.6, y - math.sin(angle) * size * 0.6)
    perp = angle + math.pi / 2
    left = (back[0] + math.cos(perp) * size * 0.55, back[1] + math.sin(perp) * size * 0.55)
    right = (back[0] - math.cos(perp) * size * 0.55, back[1] - math.sin(perp) * size * 0.55)
    draw.polygon([tip, left, right], fill=color)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    img = Image.new("RGB", (SW, SH), BG)
    draw = ImageDraw.Draw(img, "RGBA")

    # ---- 城市肌理:街区色块(浅灰圆角矩形,散落路线两侧,不压路径/建筑) ----
    for (x0, y0, x1, y1) in (
        (SW * 0.22, SH * 0.10, SW * 0.34, SH * 0.24),
        (SW * 0.36, SH * 0.72, SW * 0.50, SH * 0.90),
        (SW * 0.56, SH * 0.68, SW * 0.68, SH * 0.82),
        (SW * 0.06, SH * 0.30, SW * 0.20, SH * 0.44),
        (SW * 0.58, SH * 0.06, SW * 0.70, SH * 0.16),
    ):
        draw.rounded_rectangle((x0, y0, x1, y1), radius=int(10 * SCALE), fill=STREET_FILL)

    # ---- 淡蓝水面(画面右下角,不挡路线,模糊蒙版揉出圆润轮廓) ----
    water_pts = [
        (SW * 0.98, SH * 0.72), (SW * 1.0, SH * 0.68), (SW * 1.0, SH * 1.0),
        (SW * 0.78, SH * 1.0), (SW * 0.80, SH * 0.90), (SW * 0.90, SH * 0.80),
    ]
    water_mask = soft_blob((SW, SH), water_pts, blur=int(14 * SCALE))
    img.paste(Image.new("RGB", (SW, SH), WATER_FILL), (0, 0), water_mask)
    draw = ImageDraw.Draw(img, "RGBA")

    # ---- 浅绿草地(点缀路线沿途,圆润色块) ----
    for (x0, y0, x1, y1) in (
        (SW * 0.20, SH * 0.62, SW * 0.34, SH * 0.76),
        (SW * 0.52, SH * 0.36, SW * 0.62, SH * 0.50),
        (SW * 0.66, SH * 0.42, SW * 0.74, SH * 0.54),
    ):
        draw.ellipse((x0, y0, x1, y1), fill=GRASS_FILL)

    # ---- 婚车路线:新娘家 -> 出发 -> 礼堂 -> 宴席厅,三段暖红渐变,圆头笔触 ----
    p_jieqin = (SW * NODE_POS["jieqin"][0], SH * NODE_POS["jieqin"][1])
    p_chufa = (SW * NODE_POS["chufa"][0], SH * NODE_POS["chufa"][1])
    p_yishi = (SW * NODE_POS["yishi"][0], SH * NODE_POS["yishi"][1])
    p_yanxi = (SW * NODE_POS["yanxi"][0], SH * NODE_POS["yanxi"][1])

    seg1 = [p_jieqin, (SW * 0.24, SH * 0.74), (SW * 0.34, SH * 0.68), p_chufa]
    seg2 = [p_chufa, (SW * 0.58, SH * 0.48), (SW * 0.66, SH * 0.34), p_yishi]
    seg3 = [p_yishi, (SW * 0.84, SH * 0.26), p_yanxi]
    segments = (seg1, seg2, seg3)

    path_width = int(34 * SCALE)  # 明显比城市街区粗,一眼看出是"路线"不是"街道"
    for seg, cset in zip(segments, PATH_SEGMENTS_COLOR):
        thick_path(draw, seg, path_width + int(8 * SCALE), cset["edge"])
    for seg, cset in zip(segments, PATH_SEGMENTS_COLOR):
        thick_path(draw, seg, path_width, cset["fill"])

    # ---- 方向箭头:沿三段路线各点缀两个,箭头始终指向"新娘家 -> 酒店"的前进方向 ----
    for seg in segments:
        for t in (0.32, 0.68):
            ax, ay, ang = path_point(t, seg)
            draw_arrow(draw, ax, ay, ang, size=int(15 * SCALE), color=ARROW_COLOR)

    # ---- 新娘家:小院落(圆形徽标,玫瑰白底 + 柔和投影,呼应"家"的温暖感) ----
    home_r = int(66 * SCALE)
    home_box = (p_jieqin[0] - home_r, p_jieqin[1] - home_r, p_jieqin[0] + home_r, p_jieqin[1] + home_r)
    overlay = img.convert("RGBA")
    soft_shadow(overlay, home_box, radius=home_r, blur=int(10 * SCALE), offset=(0, int(6 * SCALE)), opacity=45)
    img = overlay.convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    draw.ellipse(home_box, fill=HOME_FILL, outline=HOME_EDGE, width=int(3 * SCALE))

    # ---- 酒店建筑群:礼堂(主楼,压住 yishi 坐标)+ 宴席厅(旁楼,压住 yanxi 坐标)+ 一栋连接配楼 ----
    hall_box = (SW * 0.715, SH * 0.155, SW * 0.845, SH * 0.265)      # 礼堂主楼(yishi 落在框内)
    banquet_box = (SW * 0.855, SH * 0.265, SW * 0.965, SH * 0.375)   # 宴席厅(yanxi 落在框内)
    annex_box = (SW * 0.80, SH * 0.185, SW * 0.865, SH * 0.245)      # 连接配楼,纯装饰,不对应节点

    building_boxes = [hall_box, banquet_box, annex_box]
    overlay = img.convert("RGBA")
    for box in building_boxes:
        soft_shadow(overlay, box, radius=int(18 * SCALE), blur=int(9 * SCALE),
                    offset=(0, int(5 * SCALE)), opacity=45)
    img = overlay.convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    for box in building_boxes:
        draw.rounded_rectangle(box, radius=int(18 * SCALE), fill=BUILDING_FILL,
                                outline=BUILDING_EDGE, width=int(2 * SCALE))

    # ---- 地名标注 ----
    label_font = load_font(int(30 * SCALE))
    strong_font = load_font(int(32 * SCALE))
    labels = [
        ("新娘家", (p_jieqin[0], p_jieqin[1] + home_r + int(28 * SCALE)), strong_font, LABEL_STRONG),
        ("出发", (p_chufa[0], p_chufa[1] - int(38 * SCALE)), label_font, LABEL_COLOR),
        ("礼堂", ((hall_box[0] + hall_box[2]) / 2, hall_box[1] - int(26 * SCALE)), label_font, LABEL_COLOR),
        ("宴席厅", ((banquet_box[0] + banquet_box[2]) / 2, banquet_box[3] + int(34 * SCALE)), label_font, LABEL_COLOR),
        ("酒店", (SW * 0.865, SH * 0.135), strong_font, LABEL_STRONG),
    ]
    for text, (cx, cy), font, color in labels:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), text, font=font, fill=color)

    img = img.resize((W, H), Image.LANCZOS)
    img.save(OUT_PATH, "JPEG", quality=90)
    print("生成完成 -> %s (%dx%d)" % (OUT_PATH, W, H))


if __name__ == "__main__":
    main()
