#!/usr/bin/env python3
"""
match.py -- 给一批照片自动定位到 tour 的 (node, yaw)。

流程:
  1. 加载 tools/cache/embeddings.npz (slice.py 产出的 36 张裁切图 CLIP embedding)。
  2. 对 --photos-dir 下每张照片 (默认 assets/photos/, 自动跳过 ground_truth.json 和非图片文件)
     算 CLIP embedding, 与全部裁切图做余弦相似度 (embedding 已 L2 归一化, 点积即 cosine sim)。
  3. 取相似度最高的裁切图所在 node 作为 node 预测; 该裁切图的 yaw 作为初始 yaw0。
  4. 精修: 看 yaw0 的两个相邻裁切 (yaw0-30, yaw0+30, 同 node 内), 取相似度更高的那个作邻居 yaw1,
     用 sim1/(sim0+sim1) 做插值权重, 在 yaw0->yaw1 方向上线性插值出更精细的 yaw。
     (sim0 是全局最大值, 所以 sim1<=sim0 恒成立, 插值权重天然落在 [0, 0.5] 之间,
     即结果不会越过 yaw1 本身, 物理意义上就是"往邻居那侧偏一点"。)
  5. 输出 matches.json: [{src, node, yaw, confidence, by:"auto", sim, ms}, ...]
     (sim, ms 是调试用的附加字段, 不属于 tour.js 冻结契约, --apply 时不会带入 tour.js)
  6. --apply: 把结果合并写回 tour.js 对应节点的 photos[], 保留已有 by:"manual" 条目不动,
     且不会重复添加已被手动标注过的同一张照片; 同 node 下旧的 by:"auto" 条目会被这次结果整体替换
     (幂等, 可重复跑)。

用法:
  python tools/match.py                          # 跑 assets/photos/, 写 matches.json
  python tools/match.py --apply                  # 顺便合并进 tour.js
  python tools/match.py --photos-dir some/dir --out out.json
"""
import argparse
import json
import os
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PHOTOS_DIR = os.path.join(ROOT, "assets", "photos")
DEFAULT_EMB_PATH = os.path.join(ROOT, "tools", "cache", "embeddings.npz")
DEFAULT_OUT = os.path.join(ROOT, "matches.json")
DEFAULT_TOUR = os.path.join(ROOT, "tour.js")

IMG_EXTS = (".jpg", ".jpeg", ".png")


def load_crop_bank(path):
    data = np.load(path, allow_pickle=False)
    return (
        data["embeddings"],                    # (N, 512) float32, L2 normalized
        data["nodes"].astype(str),             # (N,) node id per crop
        data["yaws"].astype(int),              # (N,) yaw per crop
    )


def list_photos(photos_dir):
    files = []
    for fname in sorted(os.listdir(photos_dir)):
        if fname == "ground_truth.json":
            continue
        if fname.lower().endswith(IMG_EXTS):
            files.append(fname)
    return files


def circular_delta(a, b):
    """从角度 a 到角度 b 的最短带符号差值, 落在 (-180, 180]。"""
    return (b - a + 180) % 360 - 180


def match_one(sims, crop_nodes, crop_yaws):
    """sims: (N,) 该照片对全部裁切图的余弦相似度。返回 (node, yaw, confidence, sim0)。"""
    top_idx = int(np.argmax(sims))
    node0 = str(crop_nodes[top_idx])
    yaw0 = int(crop_yaws[top_idx])
    sim0 = float(sims[top_idx])

    mask = crop_nodes == node0
    node_yaws = crop_yaws[mask]
    node_sims = sims[mask]

    yaw_prev = (yaw0 - 30) % 360
    yaw_next = (yaw0 + 30) % 360
    hit_prev = node_yaws == yaw_prev
    hit_next = node_yaws == yaw_next
    sim_prev = float(node_sims[hit_prev][0]) if np.any(hit_prev) else -1e9
    sim_next = float(node_sims[hit_next][0]) if np.any(hit_next) else -1e9

    if sim_prev >= sim_next:
        yaw1, sim1 = yaw_prev, sim_prev
    else:
        yaw1, sim1 = yaw_next, sim_next

    if sim1 <= -1e8:
        weight = 0.0
    else:
        # sim0 是全局最大值, sim1 <= sim0 恒成立 -> weight 恒落在 [0, 0.5]
        s0, s1 = max(sim0, 0.0), max(sim1, 0.0)
        weight = s1 / (s0 + s1) if (s0 + s1) > 0 else 0.0

    delta = circular_delta(yaw0, yaw1)  # +30 或 -30
    yaw_final = (yaw0 + delta * weight) % 360

    confidence = float(np.clip(sim0, 0.0, 1.0))
    return node0, yaw_final, confidence, sim0


def run_match(photos_dir, emb_path):
    crop_embs, crop_nodes, crop_yaws = load_crop_bank(emb_path)

    from sentence_transformers import SentenceTransformer
    print("== 加载 CLIP (clip-ViT-B-32) ==")
    model = SentenceTransformer("clip-ViT-B-32")

    files = list_photos(photos_dir)
    print(f"== 匹配 {len(files)} 张照片 ({photos_dir}) ==")

    results = []
    for fname in files:
        fpath = os.path.join(photos_dir, fname)
        t0 = time.time()
        img = Image.open(fpath).convert("RGB")
        emb = model.encode([img], convert_to_numpy=True, normalize_embeddings=True)[0]
        sims = crop_embs @ emb
        node, yaw, confidence, sim0 = match_one(sims, crop_nodes, crop_yaws)
        ms = (time.time() - t0) * 1000

        rel_src = os.path.relpath(fpath, ROOT).replace(os.sep, "/")
        results.append({
            "src": rel_src,
            "node": node,
            "yaw": round(float(yaw), 1),
            "confidence": round(confidence, 4),
            "by": "auto",
            "sim": round(sim0, 4),
            "ms": round(ms, 1),
        })
        print(f"  {fname:12s} -> node={node:10s} yaw={yaw:6.1f}  sim={sim0:.3f}  conf={confidence:.3f}  {ms:.0f}ms")

    return results


def apply_matches(tour_path, matches):
    text = open(tour_path, encoding="utf-8").read()
    marker = "window.TOUR = "
    idx = text.index(marker)
    prefix = text[: idx + len(marker)]
    body = text[idx + len(marker):].rstrip()
    if body.endswith(";"):
        body = body[:-1]
    tour = json.loads(body)

    manual_srcs = set()
    for node in tour["nodes"]:
        photos = node.get("photos", [])
        node["photos"] = [p for p in photos if p.get("by") == "manual"]
        manual_srcs.update(p["src"] for p in node["photos"])

    node_map = {n["id"]: n for n in tour["nodes"]}
    added, skipped_manual, skipped_unknown = 0, 0, 0
    for m in matches:
        if m["src"] in manual_srcs:
            skipped_manual += 1
            continue
        node = node_map.get(m["node"])
        if node is None:
            skipped_unknown += 1
            continue
        node["photos"].append({
            "src": m["src"],
            "yaw": m["yaw"],
            "pitch": 0,
            "confidence": m["confidence"],
            "by": "auto",
        })
        added += 1

    new_body = json.dumps(tour, ensure_ascii=False, indent=2)
    with open(tour_path, "w", encoding="utf-8") as f:
        f.write(prefix + new_body + ";\n")

    print(f"== 写回 {tour_path}: 新增 {added} 条 auto 照片, 跳过 {skipped_manual} 条(已手动标注), "
          f"{skipped_unknown} 条 node 未知 ==")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos-dir", default=DEFAULT_PHOTOS_DIR)
    ap.add_argument("--embeddings", default=DEFAULT_EMB_PATH)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--tour", default=DEFAULT_TOUR)
    ap.add_argument("--apply", action="store_true", help="把结果合并写回 tour.js")
    args = ap.parse_args()

    if not os.path.exists(args.embeddings):
        raise SystemExit(f"找不到 {args.embeddings}, 先跑 python tools/slice.py")

    matches = run_match(args.photos_dir, args.embeddings)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)
    print(f"== 写入 {args.out} ({len(matches)} 条) ==")

    if args.apply:
        apply_matches(args.tour, matches)


if __name__ == "__main__":
    main()
