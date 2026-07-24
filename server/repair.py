#!/usr/bin/env python3
"""
server/repair.py -- 自检环【自愈】: 低置信照片的密集重匹配。

结构闸(server/checks.py)会点名哪几张照片置信度不够。合成时那一趟只按 yaw 每 30 度
切了 12 张裁切图、pitch 固定 0, 采样太粗 —— 照片如果是仰拍/俯拍, 或者正好卡在两个
裁切中间, 就会匹配到一个不高不低的相似度上。这一步换更密的采样再算一次:
    yaw 每 15 度共 24 个 × pitch -15/0/+15 三档 = 72 张裁切
足够密的情况下还是过不了阈值的, 说明这张照片压根不属于这个空间(或者 CLIP 认不出),
那就不硬贴 —— 直接把它从 manifest["photos"] 挪进 manifest["quarantined"], 页面上
不再出现这个钉点。宁可少一张照片, 也不给用户一个放错地方的钉子。

对外只有一个函数:
    repair_low_confidence(session_dir, indices, conf_min=0.45, model=None) -> list[dict]
返回报告契约里的 repairs 数组: [{"type","target","before","after","result"}, ...]
result = "improved"(重匹配成功, 已更新 yaw/pitch/confidence) | "dropped"(仍不达标, 已隔离)

投影这段数学不自己重写, 直接复用 tools/slice.py 的 equirect_to_perspective。
匹配这一步原本也打算复用 tools/match.py 的 match_one, 实测发现它的 ±30 度插值精修在
15 度密集网格上会把答案拖偏 15 度(理由和实测数字写在 score_photo 的注释里), 所以这里
只取网格峰值。tools/ 下一行没改, 合成主链路照旧用 match_one。

跑法(仓库根目录, 调试用):
    .venv/bin/python -m server.repair server/sessions/fixture
"""
import json
import os
import sys

import numpy as np
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.slice import equirect_to_perspective, FOV, CROP_W, CROP_H  # noqa: E402

# 密集采样网格: 24 个 yaw × 3 个 pitch = 72 张裁切(合成那趟是 12 张 × 1 档)
DENSE_YAWS = list(range(0, 360, 15))
DENSE_PITCHES = (-15, 0, 15)


def load_clip(model=None):
    """CLIP 模型: 外面传进来就用(compose_server 启动时已经加载过一份, 别再来一遍),
    没传才自己加载。加载一次约 10-15 秒, 能省则省。"""
    if model is not None:
        return model
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("clip-ViT-B-32")


def build_dense_bank(pano_path, model):
    """把全景切成 72 张裁切图并编码, 返回 (embeddings, pitch 档位数组, yaw 数组)。

    三个数组一一对应, 第 i 个元素就是"pitch 档 bands[i]、朝向 yaws[i] 的那张裁切图"的
    embedding, 后面 score_photo 直接拿它算余弦相似度取峰值。
    """
    pano_np = np.asarray(Image.open(pano_path).convert("RGB"))
    crops, bands, yaws = [], [], []
    for pitch in DENSE_PITCHES:
        for yaw in DENSE_YAWS:
            persp = equirect_to_perspective(
                pano_np, fov_deg=FOV, yaw_deg=yaw, pitch_deg=pitch, out_w=CROP_W, out_h=CROP_H,
            )
            crops.append(Image.fromarray(persp))
            bands.append(str(pitch))
            yaws.append(yaw)
    embs = model.encode(crops, batch_size=12, convert_to_numpy=True, normalize_embeddings=True)
    return embs, np.array(bands), np.array(yaws, dtype=np.int32)


def score_photo(bank, model, photo_path):
    """一张照片在密集网格上的最佳落点。返回 (yaw, pitch, confidence)。
    confidence 和合成时一个口径: 最相似那张裁切的余弦相似度(embedding 已归一化)。

    ⚠️ 这里故意"只取网格峰值, 不做插值精修", 别好心改回 tools/match.py 的 match_one ——
    实测过, 它在这个密集网格上会把结果拖歪:
      match_one 的精修是 yaw_final = yaw0 + (±30) * s1/(s0+s1), 这个权重公式默认
      "邻居不匹配时相似度会掉到接近 0"。但 CLIP 对同一个房间的不同朝向裁切, 余弦相似度
      整条曲线都挤在 0.73~0.93 之间(夹具 004 实测: 峰值 yaw150=0.9265, 邻居 yaw180=0.9099,
      yaw120=0.8702), 于是 s1/(s0+s1) 恒等于 0.5 上下, 结果永远落在"峰值和较好邻居的中点"。
      004 就这样从正确的 150 被拖到 164.9, 偏了 15 度, 而且 confidence 还照报 0.9265 ——
      置信度更高、位置更错, 正是自检环最该拦住的那种"看起来变好了"。
      (肉眼复核过: 把全景按 yaw145/pitch10 和 yaw164.9/pitch15 各切一张和 004.jpg 并排比,
       前者门框/吊灯/挂画全对得上, 后者整体右移了一个门洞。)
    网格是 15 度一格, 所以这里的 yaw 精度就是 ±7.5 度, 不做假精修去伪造小数位。
    tools/match.py 一行没改, 合成主链路仍然用它。
    """
    embs, bands, yaws = bank
    img = Image.open(photo_path).convert("RGB")
    emb = model.encode([img], convert_to_numpy=True, normalize_embeddings=True)[0]
    sims = embs @ emb
    top = int(np.argmax(sims))
    return float(yaws[top]), float(bands[top]), round(float(sims[top]), 4)


def _conf_of(photo):
    """读一张照片原来的置信度; 字段缺失或不是数就返回 None(报告里如实写 null)。"""
    v = photo.get("confidence") if isinstance(photo, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return round(float(v), 4)


def repair_low_confidence(session_dir, indices, conf_min=0.45, model=None):
    """对 manifest.photos 里指定下标的照片做密集重匹配, 写回 manifest.json。

    达标的原地更新(by 改成 "auto-repaired"), 不达标的移进 quarantined 数组。
    indices 里越界的下标会被忽略; manifest 读不出来直接返回空数组(那种情况轮不到自愈,
    结构闸已经整体判死了)。
    """
    manifest_path = os.path.join(session_dir, "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return []
    photos = manifest.get("photos")
    if not isinstance(photos, list):
        return []

    targets = sorted({i for i in indices if isinstance(i, int) and 0 <= i < len(photos)})
    if not targets:
        return []

    pano_path = os.path.join(session_dir, manifest.get("panorama") or "pano.jpg")
    if not os.path.isfile(pano_path):
        return []

    model = load_clip(model)
    bank = build_dense_bank(pano_path, model)

    repairs = []
    to_quarantine = {}  # 下标 -> 隔离条目(循环里先攒着, 循环完再统一搬家, 免得改到一半下标全乱)
    for i in targets:
        photo = photos[i]
        if not isinstance(photo, dict) or not isinstance(photo.get("src"), str):
            continue
        src = photo["src"]
        before = _conf_of(photo)
        photo_path = os.path.join(session_dir, src)

        if not os.path.isfile(photo_path):
            # 文件都不在, 重匹配无从谈起, 直接隔离
            entry = dict(photo)
            entry["by"] = "auto-quarantined"
            entry["reason"] = "照片文件不存在(%s), 无法重匹配, 已隔离" % src
            to_quarantine[i] = entry
            repairs.append({"type": "rematch_dense", "target": src,
                            "before": before, "after": None, "result": "dropped"})
            continue

        yaw, pitch, conf = score_photo(bank, model, photo_path)
        if conf >= conf_min:
            photo.update({"yaw": yaw, "pitch": pitch, "confidence": conf, "by": "auto-repaired"})
            result = "improved"
        else:
            entry = dict(photo)
            entry.update({
                "yaw": yaw, "pitch": pitch, "confidence": conf, "by": "auto-quarantined",
                "reason": "密集重匹配(72 张裁切)后置信度 %.4f 仍低于阈值 %.2f, "
                          "判定这张照片不属于本空间, 已隔离, 页面不再显示它的钉点" % (conf, conf_min),
            })
            to_quarantine[i] = entry
            result = "dropped"

        repairs.append({"type": "rematch_dense", "target": src,
                        "before": before, "after": conf, "result": result})

    if to_quarantine:
        quarantined = manifest.get("quarantined")
        manifest["quarantined"] = (quarantined if isinstance(quarantined, list) else []) + \
            [to_quarantine[i] for i in sorted(to_quarantine)]
        manifest["photos"] = [p for i, p in enumerate(photos) if i not in to_quarantine]

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return repairs


if __name__ == "__main__":
    from server.checks import low_confidence_photos

    target_dir = sys.argv[1] if len(sys.argv) > 1 else "server/sessions/fixture"
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.45
    idx = low_confidence_photos(target_dir, threshold)
    print("低置信照片下标:", idx)
    print(json.dumps(repair_low_confidence(target_dir, idx, threshold), ensure_ascii=False, indent=2))
