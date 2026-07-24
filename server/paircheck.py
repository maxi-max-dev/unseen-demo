#!/usr/bin/env python3
"""
server/paircheck.py -- 成对比对: 「这张照片」 vs 「全景在它被分配到的那个方位的裁切」。

## 为什么要有这个东西(这是整套自检环的命门)

自检环原来的三道闸, 一道也验不出**唯一真正要命的错**: 照片被放到了错误的方位。
- 结构闸看的 confidence, 是 CLIP 给【自己刚做的决定】打的分 —— 循环论证。
- 渲染闸只算截图亮度, 不看内容。
- 语义闸只在"所有照片钉点都不在画面里"时才报错, 有一个在就放行。

所以要做的是: **拿一个和 CLIP 完全无关的信号, 去检查 CLIP 的答案。**
把全景按 (yaw, pitch) 切出一张透视图, 和照片本身比 —— 如果 CLIP 放对了, 这两张
应该是同一个地方的同一个朝向, 颜色分布和明暗结构都该对得上; 放错了就对不上。

判据两个, 都不碰 CLIP、不碰任何神经网络:
  · 颜色相似度   : HSV 直方图的巴氏系数(Bhattacharyya coefficient)
  · 结构相似度   : 灰度降到 32x24 之后的归一化互相关(去掉均值和方差, 只看明暗骨架)

在线时还可以再叠一层视觉模型(阶跃), 问它"这两张是不是同一个地方" ——
那才叫真正代替人眼。没有 key 就只跑上面两个离线判据, 报告里如实标注。

## ⚠️ 标定结果推翻了这两个判据当"闸门"的用法, 老实记在这里

第一版标定用 assets/walkdemo 的 _j*.jpg 当正样本, 结构相似度恒等于 1.000 ——
因为那些图就是从同一张全景切出来的, 等于自己跟自己比, 阈值是假的。

改成【模拟真实拍摄】的正样本后(方位偏 5-14 度、视野更窄、曝光白平衡偏移、噪点、
再压一道 JPEG, 见 _realistic_photo), 真实分布是:
    正样本(放对) n=108   颜色 0.144~0.946(中位 0.722)   结构 0.041~0.842(中位 0.497)
    负样本(放错) n=756   颜色 0.121~0.963(中位 0.641)   结构 -0.502~0.745(中位 0.206)
**两组重叠严重。** 要做到"放错的一张都不漏", 只能保住 7% 放对的 —— 当硬闸门没法用。

所以这个模块的定位改成【否决网, 不是闸门】:
只在两个信号都明显很差时才出 reject。实测 颜色<0.40 且 结构<0.25 这一档:
    误伤放对的 0/108, 捞到放错的 143/756(19%)
零误伤能捞两成, 这是净收益; 剩下八成它不表态(unsure), 不假装自己知道。

**而这件事本身就是阶跃赛道那个命题的实证**: 确定性规则做不了最后一公里的验收,
必须让一个会"看"的模型去看。所以 check_with_stepfun() 才是这里的主判据,
离线这两条只是断网时的兜底网。报告里必须如实标注当时用的是哪一层。

零新依赖: numpy + Pillow + 标准库。
"""
import base64
import json
import os
import sys

import numpy as np
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.slice import equirect_to_perspective, FOV, CROP_W, CROP_H  # noqa: E402

# 「高置信度否决」band —— 只有两个信号【都】掉进这条线以下才敢说放错了。
# 实测(见文件头): 误伤放对的 0/108, 捞到放错的 143/756。刻意定得保守:
# 冤枉一张放对的照片 = 新人白看一眼, 但它只有 19% 的召回, 所以【绝不能反过来
# 把"没被它否决"当成"放对了"】—— 那是 unsure, 不是 ok。
REJECT_COLOR = float(os.environ.get("PSM_PAIR_REJECT_COLOR", "0.40"))
REJECT_STRUCT = float(os.environ.get("PSM_PAIR_REJECT_STRUCT", "0.25"))

# 反过来: 两个信号都很高时, 才敢说"看着是对的"。这一档是从正样本中位数往上取的,
# 同样只是参考, 不是保证。
STRONG_COLOR = float(os.environ.get("PSM_PAIR_STRONG_COLOR", "0.80"))
STRONG_STRUCT = float(os.environ.get("PSM_PAIR_STRONG_STRUCT", "0.60"))

_pano_cache = {}


def _load_pano(pano_path):
    st = os.path.getmtime(pano_path)
    hit = _pano_cache.get(pano_path)
    if hit and hit[0] == st:
        return hit[1]
    arr = np.asarray(Image.open(pano_path).convert("RGB"))
    _pano_cache[pano_path] = (st, arr)
    return arr


def crop_at(pano_path, yaw, pitch=0.0, fov=FOV, w=CROP_W, h=CROP_H):
    """把全景在指定方位切出一张透视图(和 CLIP 那条链路用的是同一个投影函数)。"""
    return Image.fromarray(
        equirect_to_perspective(_load_pano(pano_path), fov_deg=fov, yaw_deg=float(yaw),
                                pitch_deg=float(pitch), out_w=w, out_h=h)
    )


# ---------------------------------------------------------------- 两个离线判据
def _hsv_hist(img, bins=(8, 8, 8)):
    """HSV 三维直方图, 归一化。用 HSV 是因为它对整体明暗变化没那么敏感,
    而同一个地方在照片和全景里的曝光往往差一截。"""
    hsv = np.asarray(img.convert("HSV"), dtype=np.float32) / 255.0
    idx = [np.clip((hsv[..., i] * bins[i]).astype(np.int32), 0, bins[i] - 1) for i in range(3)]
    flat = (idx[0] * bins[1] + idx[1]) * bins[2] + idx[2]
    hist = np.bincount(flat.ravel(), minlength=bins[0] * bins[1] * bins[2]).astype(np.float64)
    s = hist.sum()
    return hist / s if s > 0 else hist


def color_similarity(a, b):
    """巴氏系数: 两个概率分布逐格开方相乘再求和。1=完全一样, 0=毫不相干。"""
    ha, hb = _hsv_hist(a), _hsv_hist(b)
    return float(np.sum(np.sqrt(ha * hb)))


def structure_similarity(a, b, size=(32, 24)):
    """降到 32x24 灰度, 去均值除标准差之后做互相关 —— 只比明暗骨架,
    不受整体亮度和对比度差异影响。范围 [-1, 1]。"""
    def prep(im):
        g = np.asarray(im.convert("L").resize(size, Image.BILINEAR), dtype=np.float64)
        g -= g.mean()
        sd = g.std()
        return g / sd if sd > 1e-6 else g
    x, y = prep(a), prep(b)
    return float(np.mean(x * y))


# ---------------------------------------------------------------- 对外接口
def check_placement(pano_path, photo_path, yaw, pitch=0.0, use_model=True):
    """比对一张照片和它被分配到的方位。

    verdict 三档(**不是二值**, 这很重要):
        reject  两个离线信号都掉进否决 band, 或视觉模型说不是同一个地方 → 有把握说放错了
        likely  两个信号都很高 / 视觉模型说是 → 看着是对的
        unsure  中间地带 → 机器不表态。这是大多数情况, 别把它当"通过"。

    ⚠️ 离线这两条判据【不用】CLIP —— 意义就在于用独立信号去检查 CLIP 的答案。
    有 STEPFUN_API_KEY 时会再叠一层视觉模型, 那一层才是真正代替人眼的主判据。
    """
    photo = Image.open(photo_path).convert("RGB")
    ref = crop_at(pano_path, yaw, pitch)
    photo_r = photo.resize((CROP_W, CROP_H), Image.BILINEAR)

    color = color_similarity(photo_r, ref)
    struct = structure_similarity(photo_r, ref)

    if color < REJECT_COLOR and struct < REJECT_STRUCT:
        verdict = "reject"
        reason = (f"照片和全景在 {float(yaw):.0f}° 的画面明显对不上"
                  f"(颜色 {color:.2f}、结构 {struct:.2f} 都低于否决线),"
                  f"这张很可能不在这个方位")
    elif color >= STRONG_COLOR and struct >= STRONG_STRUCT:
        verdict = "likely"
        reason = (f"照片和全景在 {float(yaw):.0f}° 的画面高度吻合"
                  f"(颜色 {color:.2f}、结构 {struct:.2f}),放置看着是对的")
    else:
        verdict = "unsure"
        reason = (f"离线判据看不准(颜色 {color:.2f}、结构 {struct:.2f} 都在中间地带)——"
                  f"这一档需要视觉模型来看")

    out = {"verdict": verdict, "yaw": round(float(yaw), 1), "pitch": round(float(pitch), 1),
           "color": round(color, 4), "struct": round(struct, 4),
           "backend": "offline", "reason": reason}

    if use_model:
        m = check_with_stepfun(pano_path, photo_path, yaw, pitch)
        if m is not None:
            # 视觉模型的话算数, 它是主判据; 离线两个数留在报告里当旁证。
            out["verdict"] = "likely" if m["ok"] else "reject"
            out["backend"] = "stepfun"
            out["modelConfidence"] = m["confidence"]
            out["reason"] = f"视觉模型判定:{m['reason']}(离线旁证 颜色 {color:.2f}/结构 {struct:.2f})"
        else:
            out["degraded"] = True     # 想用模型但没用上, 如实标注
    return out


def check_manifest(pano_path, photos, base_dir="", use_model=True):
    """对一批照片逐张比对。photos = [{src, yaw, pitch}]。

    返回 {rejected, unsure, likely, items, backend}。
    ⚠️ 调用方注意: rejected 才是"有把握说错了", unsure 不等于通过。
    """
    items = []
    for p in photos:
        path = p.get("src", "")
        if base_dir and not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        if not os.path.exists(path):
            items.append({"src": p.get("src"), "verdict": "reject",
                          "reason": "照片文件不存在,无法比对"})
            continue
        r = check_placement(pano_path, path, p.get("yaw", 0), p.get("pitch", 0) or 0,
                            use_model=use_model)
        r["src"] = p.get("src")
        items.append(r)
    counts = {k: sum(1 for i in items if i.get("verdict") == k)
              for k in ("reject", "unsure", "likely")}
    return {"rejected": counts["reject"], "unsure": counts["unsure"],
            "likely": counts["likely"], "checked": len(items), "items": items,
            "backend": items[0].get("backend") if items else "offline"}


# ---------------------------------------------------------------- 在线那一层(阶跃)
STEPFUN_PROMPT = (
    "你是前端验收员。第一张图是用户上传的照片,第二张图是全景在系统判定的那个方位切出来的画面。"
    "请判断:这两张是不是同一个地方的同一个朝向?(取景宽窄、曝光可以不同,看的是场景本身。)"
    "只输出 JSON,不要任何其他文字,格式:"
    '{"same_place": true/false, "confidence": 0到1的小数, "reason": "一句中文说明"}'
)


def check_with_stepfun(pano_path, photo_path, yaw, pitch=0.0, timeout=30):
    """用阶跃视觉模型做同一件事(真·代替人眼)。没 key / 调用失败就返回 None,
    调用方自己退回离线判据 —— 外网不通绝不能让整条自检环挂掉。"""
    key = os.environ.get("STEPFUN_API_KEY")
    if not key:
        return None
    import urllib.request

    def b64(im):
        import io
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    photo = Image.open(photo_path)
    ref = crop_at(pano_path, yaw, pitch)
    body = json.dumps({
        "model": os.environ.get("STEPFUN_MODEL", "step-1o-turbo-vision"),
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": STEPFUN_PROMPT},
            {"type": "image_url", "image_url": {"url": b64(photo)}},
            {"type": "image_url", "image_url": {"url": b64(ref)}},
        ]}],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        "https://api.stepfun.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        txt = data["choices"][0]["message"]["content"].strip()
        if txt.startswith("```"):                      # 容忍它套 markdown 围栏
            txt = txt.split("```")[1].lstrip("json").strip()
        out = json.loads(txt)
        return {"ok": bool(out.get("same_place")), "confidence": float(out.get("confidence", 0)),
                "reason": str(out.get("reason", "")), "backend": "stepfun"}
    except Exception:
        return None


# ---------------------------------------------------------------- 标定
def _realistic_photo(pano_path, yaw, pitch, seed):
    """造一张【像真实宾客拍的】照片。

    ⚠️ 为什么必须造: assets/walkdemo 里的 _j*.jpg 就是从同一张全景里切出来的,
    拿它当正样本, 结构相似度恒等于 1.000 —— 那是自己跟自己比, 标出来的阈值是假的。
    真人是站在附近另一个位置、用另一台手机、另一个时刻拍的, 所以这里模拟:
      · 方位偏 ±5~14 度(人不会正好站在全景机位上)
      · 视野更窄(手机不是 70° 广角)
      · 曝光和白平衡偏一截
      · 轻微裁切偏移 + JPEG 压缩噪点
    这样标出来的阈值才对得起真实数据。
    """
    rng = np.random.default_rng(seed)
    dy = float(rng.uniform(5, 14)) * (1 if rng.random() < 0.5 else -1)
    dp = float(rng.uniform(-4, 4))
    fov = float(rng.uniform(48, 62))
    im = crop_at(pano_path, (yaw + dy) % 360, pitch + dp, fov=fov)
    a = np.asarray(im, dtype=np.float32)
    a *= rng.uniform(0.78, 1.22)                                  # 曝光
    a *= np.array([rng.uniform(0.92, 1.08) for _ in range(3)])    # 白平衡
    a += rng.normal(0, 4.0, a.shape)                              # 噪点
    im2 = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    import io
    buf = io.BytesIO()
    im2.save(buf, "JPEG", quality=int(rng.integers(72, 92)))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _check_img(pano_path, img, yaw, pitch):
    """和 check_placement 同一套判据, 但吃内存里的 Image(标定时不落盘)。"""
    ref = crop_at(pano_path, yaw, pitch)
    r = img.resize((CROP_W, CROP_H), Image.BILINEAR)
    return color_similarity(r, ref), structure_similarity(r, ref)


def calibrate(realistic=True):
    """在 assets/walkdemo 上标定阈值。

    正样本 = 【模拟真实拍摄】的照片放在系统判定的方位(默认, 见 _realistic_photo);
             realistic=False 时退回"原样裁切图", 那组结构恒为 1.0, 只用来对照看差距。
    负样本 = 同一张照片放在错误方位(±60/±120/180 度)以及放进别的房间。
    """
    from server.film import WALK_CROP_POSE
    scenes = ["entrance_hall", "comfy_cafe", "ballroom", "chapel_day"]
    pos, neg = [], []
    for sc in scenes:
        pano = os.path.join(REPO_ROOT, "assets", "walkdemo", sc + ".jpg")
        if not os.path.exists(pano):
            continue
        for tag, (yaw, pitch) in WALK_CROP_POSE.items():
            ph = os.path.join(REPO_ROOT, "assets", "walkdemo", f"{sc}_j{tag}.jpg")
            if not os.path.exists(ph):
                continue
            if realistic:
                for k in range(3):     # 每个方位造 3 张不同扰动的"真实照片"
                    img = _realistic_photo(pano, yaw, pitch, seed=hash((sc, tag, k)) % (2**31))
                    c, s = _check_img(pano, img, yaw, pitch)
                    pos.append((f"{sc}_j{tag}#{k}@真方位", c, s))
            else:
                r = check_placement(pano, ph, yaw, pitch)
                pos.append((f"{sc}_j{tag}@真方位", r["color"], r["struct"]))
            for off in (60, -60, 120, 180):
                r2 = check_placement(pano, ph, (yaw + off) % 360, pitch)
                neg.append((f"{sc}_j{tag}@偏{off}°", r2["color"], r2["struct"]))
            for other in scenes:
                if other == sc:
                    continue
                op = os.path.join(REPO_ROOT, "assets", "walkdemo", other + ".jpg")
                if os.path.exists(op):
                    r3 = check_placement(op, ph, yaw, pitch)
                    neg.append((f"{sc}_j{tag}→{other}", r3["color"], r3["struct"]))

    def stat(rows, name):
        c = np.array([r[1] for r in rows]); s = np.array([r[2] for r in rows])
        print(f"{name}: n={len(rows)}  颜色 {c.min():.3f}~{c.max():.3f}(中位 {np.median(c):.3f})"
              f"  结构 {s.min():.3f}~{s.max():.3f}(中位 {np.median(s):.3f})")
        return c, s

    pc, ps = stat(pos, "正样本(放对)")
    nc, ns = stat(neg, "负样本(放错)")
    # 扫一遍阈值组合, 找"放错的一个都不漏"前提下放对的保留最多的那组。
    # 口径是刻意偏保守的: 漏过一张放错的照片 = 演示当场被评委抓住;
    # 误判一张放对的 = 推给新人点一下"收下", 代价小得多。
    best = None
    for cm in np.arange(0.40, 0.95, 0.01):
        for sm in np.arange(-0.10, 0.80, 0.02):
            fp = int(np.sum((nc >= cm) & (ns >= sm)))
            tp = int(np.sum((pc >= cm) & (ps >= sm)))
            if best is None or (fp, -tp) < (best[0], -best[1]):
                best = (fp, tp, float(cm), float(sm))
    fp, tp, cm, sm = best
    print(f"\n最优阈值(先保证放错不漏): 颜色≥{cm:.2f} 且 结构≥{sm:.2f}")
    print(f"  放对的判过: {tp}/{len(pos)}  ({tp/len(pos)*100:.0f}%)")
    print(f"  放错的漏过: {fp}/{len(neg)}")
    fp0 = int(np.sum((nc >= COLOR_MIN) & (ns >= STRUCT_MIN)))
    tp0 = int(np.sum((pc >= COLOR_MIN) & (ps >= STRUCT_MIN)))
    print(f"当前代码里的 颜色≥{COLOR_MIN} 结构≥{STRUCT_MIN}: 判过 {tp0}/{len(pos)}, 漏过 {fp0}/{len(neg)}")
    return {"pos": len(pos), "neg": len(neg), "bestColor": round(cm,2), "bestStruct": round(sm,2),
            "tp": tp, "fp": fp}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "calibrate":
        calibrate()
    elif len(sys.argv) >= 5:
        print(json.dumps(check_placement(sys.argv[2], sys.argv[3], float(sys.argv[4]),
                                         float(sys.argv[5]) if len(sys.argv) > 5 else 0),
                         ensure_ascii=False, indent=2))
    else:
        print(__doc__)
