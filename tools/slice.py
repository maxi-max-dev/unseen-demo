#!/usr/bin/env python3
"""
slice.py -- 把 assets/panos/ 每张全景切成 12 个方向的透视裁切图 (FOV=70, yaw 每 30 度一张),
存 tools/cache/crops/<node>/<yaw>.jpg, 并把所有裁切图的 CLIP embedding 算好存
tools/cache/embeddings.npz。

equirect->perspective 投影数学与 tools/fixtures.py 的 equirect_to_perspective() 完全一致
(同一套 yaw/pitch 约定: 列 0 = yaw 0, 从左到右递增到 360; pitch 正=向上看),
这样切图和生成 ground truth 用的是同一把尺子, match.py 才能对得上。

用法: source .venv/bin/activate && python tools/slice.py
依赖: pillow, numpy, sentence-transformers (CLIP)
"""
import json
import math
import os
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANO_DIR = os.path.join(ROOT, "assets", "panos")
CACHE_DIR = os.path.join(ROOT, "tools", "cache")
CROP_DIR = os.path.join(CACHE_DIR, "crops")
EMB_PATH = os.path.join(CACHE_DIR, "embeddings.npz")

FOV = 70
CROP_W, CROP_H = 800, 600
YAWS = list(range(0, 360, 30))  # 12 个方向


def equirect_to_perspective(equirect_np, fov_deg, yaw_deg, pitch_deg, out_w, out_h):
    """与 tools/fixtures.py 中同名函数逐行一致,勿改动约定。"""
    eh, ew = equirect_np.shape[:2]
    fov = math.radians(fov_deg)
    theta = math.radians(yaw_deg)
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

    x2 = x1 * math.cos(theta) + z1 * math.sin(theta)
    z2 = -x1 * math.sin(theta) + z1 * math.cos(theta)
    y2 = y1

    lon = np.arctan2(x2, z2)
    lat = np.arcsin(np.clip(y2, -1.0, 1.0))

    src_x = (lon / (2 * math.pi)) * ew
    src_y = (0.5 - lat / math.pi) * eh

    src_x = np.mod(src_x, ew).astype(np.int32)
    src_y = np.clip(src_y, 0, eh - 1).astype(np.int32)

    return equirect_np[src_y, src_x]


def list_panos():
    nodes = []
    for fname in sorted(os.listdir(PANO_DIR)):
        if fname.lower().endswith((".jpg", ".jpeg", ".png")):
            node = os.path.splitext(fname)[0]
            nodes.append((node, os.path.join(PANO_DIR, fname)))
    return nodes


def make_crops():
    """切图, 返回 [(node, yaw, crop_path), ...]"""
    os.makedirs(CROP_DIR, exist_ok=True)
    items = []
    for node, pano_path in list_panos():
        node_dir = os.path.join(CROP_DIR, node)
        os.makedirs(node_dir, exist_ok=True)
        pano_img = Image.open(pano_path).convert("RGB")
        pano_np = np.asarray(pano_img)
        print(f"  {node}: {pano_img.size} -> 12 crops")
        for yaw in YAWS:
            persp_np = equirect_to_perspective(
                pano_np, fov_deg=FOV, yaw_deg=yaw, pitch_deg=0,
                out_w=CROP_W, out_h=CROP_H,
            )
            crop_path = os.path.join(node_dir, f"{yaw}.jpg")
            Image.fromarray(persp_np).save(crop_path, quality=92)
            items.append((node, yaw, crop_path))
    return items


def embed_crops(items):
    from sentence_transformers import SentenceTransformer

    print("== 加载 CLIP (clip-ViT-B-32) ==")
    t0 = time.time()
    model = SentenceTransformer("clip-ViT-B-32")
    print(f"  模型加载耗时 {time.time()-t0:.1f}s")

    imgs = [Image.open(p).convert("RGB") for _, _, p in items]
    t0 = time.time()
    embs = model.encode(imgs, batch_size=32, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)
    dt = time.time() - t0
    print(f"  {len(imgs)} 张裁切图 embedding 耗时 {dt:.1f}s ({dt/len(imgs)*1000:.0f}ms/张)")

    nodes = np.array([n for n, _, _ in items])
    yaws = np.array([y for _, y, _ in items], dtype=np.int32)
    paths = np.array([p for _, _, p in items])

    os.makedirs(CACHE_DIR, exist_ok=True)
    np.savez(EMB_PATH, embeddings=embs, nodes=nodes, yaws=yaws, paths=paths)
    print(f"== 写入 {EMB_PATH} ({embs.shape}) ==")


def main():
    print("== 1. equirect -> perspective 切图 (FOV=70, yaw 0..330 step 30) ==")
    items = make_crops()
    print(f"  共 {len(items)} 张裁切图, 存于 {CROP_DIR}")

    print("== 2. 计算 CLIP embedding ==")
    embed_crops(items)


if __name__ == "__main__":
    main()
