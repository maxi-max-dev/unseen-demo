#!/usr/bin/env python3
"""
server/judge.py -- 自检环【第三闸: 语义验收】, 用来替代人眼看那一下。

前两闸(结构闸看 manifest 字段/资源, 渲染闸开无头浏览器截图)只能证明"页面没报错",
证明不了"页面看着对不对"。这一闸吃渲染闸产出的截图, 回答人眼那个问题:
是不是黑屏白屏破图? 是不是一个正常渲染出来的全景空间? 照片钉点贴得合不合理?

对外只有一个函数:
    judge_shots(shot_paths, context) -> dict
返回值 = 报告契约里的 gates.semantic 对象(ok/confidence/reason/issues/perShot),
外加 backend/model/degraded 三个字段, 供上层填 report.json 的 judge 段。

两个后端, 用环境变量 PSM_JUDGE 选(stepfun / local / auto, 默认 auto):
  · stepfun -- 调阶跃星辰视觉模型(OpenAI 兼容接口), 只用标准库 urllib 发请求, 零新依赖。
  · local   -- 离线像素规则(numpy + Pillow)。它不是 AI, 就是一堆阈值判定, 别包装成 AI。
auto = 有 STEPFUN_API_KEY 就走 stepfun, 否则走 local。
stepfun 这条路只要出任何岔子(没 key / 网络不通 / 返回的不是能解析的 JSON), 一律自动降级到
local, 并把 degraded 置 True、在 reason 里如实写明降级原因 —— 外网不通绝不能让整个自检环挂掉。

跑法(自测):
    .venv/bin/python server/judge.py assets/walkdemo/ballroom.jpg
    PSM_JUDGE=local .venv/bin/python server/judge.py 截图1.png 截图2.png
"""
import base64
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

import numpy as np
from PIL import Image

STEPFUN_URL = "https://api.stepfun.com/v1/chat/completions"
STEPFUN_DEFAULT_MODEL = "step-1o-turbo-vision"
STEPFUN_TIMEOUT = 30  # 秒, 卡死一张截图不能拖垮整条自检环

# ---- 离线像素规则的阈值(用 assets/walkdemo 里三张真全景标定过:
#      正常画面 mean≈123-127, std≈43-52, grad≈5-7; 高斯模糊半径 25 时 grad 掉到 1.3)
DARK_MEAN = 12.0        # 平均亮度低于此 = 黑屏
BRIGHT_MEAN = 243.0     # 平均亮度高于此 = 白屏
FLAT_STD = 6.0          # 亮度标准差低于此 = 一片纯色(没画面/被单色蒙层盖住)
LOW_GRAD = 1.5          # 相邻像素平均差分低于此 = 边缘密度太低, 糊了或压根没内容
SPRITE_MIN_GAP = 20.0   # 两个照片钉点中心距离小于此(像素) = 挤成一团
ANALYZE_SIDE = 512      # 统计前先缩到这个边长, 省时间且不影响这几个统计量


# ---------------------------------------------------------------- 小工具
def _short(path):
    """报告里 file 字段用相对短名: shots/ 目录下的截图写成 "shots/xxx.png", 其余只留文件名。
    这样 judge 的 perShot[].file 能和渲染闸的 shots[].file 对得上。"""
    parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
    name = os.path.basename(path)
    return f"{parent}/{name}" if parent == "shots" else name


def _pixel_stats(path):
    """一张截图的三个统计量: 平均亮度 / 亮度标准差 / 边缘密度(相邻像素平均绝对差分)。
    先转灰度再缩到 512 边长, 三个量对缩放都不敏感, 但速度差一个量级。"""
    with Image.open(path) as im:
        gray = im.convert("L")
        gray.thumbnail((ANALYZE_SIDE, ANALYZE_SIDE))
        arr = np.asarray(gray).astype(np.float32)
    if arr.size == 0 or arr.shape[0] < 2 or arr.shape[1] < 2:
        return 0.0, 0.0, 0.0
    dx = float(np.abs(np.diff(arr, axis=1)).mean())
    dy = float(np.abs(np.diff(arr, axis=0)).mean())
    return float(arr.mean()), float(arr.std()), (dx + dy) / 2.0


def _clustered_in_one_shot(sprites):
    """在【同一张截图】里两两比距离, 返回挤在一起的钉点编号集合。"""
    on = [s for s in sprites if s.get("onScreen")]
    clustered = set()
    for i in range(len(on)):
        for j in range(i + 1, len(on)):
            ax, ay = float(on[i].get("x", 0)), float(on[i].get("y", 0))
            bx, by = float(on[j].get("x", 0)), float(on[j].get("y", 0))
            if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < SPRITE_MIN_GAP:
                clustered.add(on[i].get("i", i))
                clustered.add(on[j].get("i", j))
    return clustered


def _sprite_issues(sprites, shot_sprites=None):
    """钉点合理性: 只看渲染闸抓回来的 sprites 坐标, 不看像素。
    两条规则 —— 一个都没进画面 = 照片没贴上去; 多个钉点挤在 20px 内 = 糊成一团。

    ⚠️ 重叠必须在【同一张截图】里判。渲染闸回传的顶层 sprites 是跨朝向汇总的
    (每个钉点取"第一次看见它的那一张"的坐标), 而每个朝向恰恰是冲着某张照片转过去的,
    那张照片自然落在画面正中 —— 于是一堆本来天各一方的钉点在汇总表里都成了 (640, 357),
    照着汇总表判重叠会把它们全报成"挤成一团"。2026-07-24 实测: 8 张照片分布在
    15°/75°/105°/255°/285° 五个方位, 汇总表判出 7 个"重叠", 逐张判出 0 个。
    所以有 shot_sprites(逐张的坐标)时一律按逐张判; 没有就退回老口径, 不改变旧调用方的行为。
    """
    issues = []
    if not sprites:
        return issues  # 上层没给钉点信息就不判, 别凭空造问题

    on = [s for s in sprites if s.get("onScreen")]
    if not on:
        issues.append(f"{len(sprites)} 个照片钉点没有一个落在画面内, 照片可能没贴到全景上")
        return issues

    if shot_sprites:
        clustered = set()
        for one in shot_sprites:
            clustered |= _clustered_in_one_shot(one or [])
    else:
        clustered = _clustered_in_one_shot(sprites)
    if clustered:
        issues.append(
            f"{len(clustered)} 个照片钉点重叠在 {SPRITE_MIN_GAP:.0f}px 以内(编号 "
            f"{sorted(clustered)}), 挤成一团了"
        )
    return issues


# ---------------------------------------------------------------- 后端一: 离线像素规则
def _local_one(path):
    """单张截图的像素规则判定, 返回 (perShot 条目, 统计量字符串)。"""
    file_id = _short(path)
    try:
        mean, std, grad = _pixel_stats(path)
    except Exception as e:
        return {"file": file_id, "ok": False, "issues": [f"截图读不出来: {e}"],
                "reason": "文件损坏或不是图片"}, "读取失败"

    issues = []
    if mean < DARK_MEAN:
        issues.append(f"黑屏: 平均亮度只有 {mean:.1f}(低于 {DARK_MEAN:.0f})")
    elif mean > BRIGHT_MEAN:
        issues.append(f"白屏: 平均亮度高到 {mean:.1f}(超过 {BRIGHT_MEAN:.0f})")
    if std < FLAT_STD:
        issues.append(f"画面基本是一片纯色: 亮度标准差只有 {std:.1f}(低于 {FLAT_STD:.0f})")
    if grad < LOW_GRAD:
        issues.append(f"画面信息量过低: 边缘密度只有 {grad:.2f}(低于 {LOW_GRAD:.1f}), 糊了或没内容")

    stat = f"亮度 {mean:.1f} / 标准差 {std:.1f} / 边缘密度 {grad:.2f}"
    reason = "像素规则未发现异常(" + stat + ")" if not issues else "; ".join(issues)
    return {"file": file_id, "ok": not issues, "issues": issues, "reason": reason}, stat


def judge_local(shot_paths, context, degraded=False, degrade_reason=""):
    """离线像素规则后端。断网、没 key、模型抽风时都靠它兜底。
    degraded/degrade_reason 由 stepfun 那条路降级过来时传, 会拼进 reason 如实说明。"""
    per_shot = []
    for p in shot_paths:
        item, _stat = _local_one(p)
        per_shot.append(item)

    sprite_bad = _sprite_issues(context.get("sprites") or [], context.get("shotSprites"))
    issues = []
    for item in per_shot:
        for msg in item["issues"]:
            issues.append(f"{item['file']}: {msg}")
    issues.extend(sprite_bad)

    bad = [i for i in per_shot if not i["ok"]]
    ok = bool(per_shot) and not bad and not sprite_bad

    if not per_shot:
        ok = False
        issues.append("没有可供判定的截图")
        reason = "没有截图, 判不了"
        confidence = 0.0
    elif ok:
        # 规则只能证明"不是黑屏白屏糊图", 证明不了"内容语义对", 所以置信度封顶 0.7, 别虚报。
        reason = f"离线像素规则: {len(per_shot)} 张截图都不是黑屏/白屏/纯色/糊图, 钉点分布正常"
        confidence = 0.7
    else:
        reason = f"离线像素规则: {len(bad)}/{len(per_shot)} 张截图有问题 —— " + "; ".join(issues[:3])
        confidence = max(0.1, 0.9 - 0.1 * len(issues))

    if degraded and degrade_reason:
        reason = f"[已降级到离线像素规则: {degrade_reason}] {reason}"

    return {
        "ok": ok,
        "confidence": round(float(confidence), 2),
        "reason": reason,
        "issues": issues,
        "perShot": per_shot,
        "backend": "local",
        "model": None,
        "degraded": bool(degraded),
    }


# ---------------------------------------------------------------- 后端二: 阶跃星辰视觉模型
PROMPT = """你是前端验收员, 现在替代人眼验收一个网页的截图。这个页面应该是: {expect}
标题「{title}」, 页面里应该有 {photo_count} 张照片缩略图钉在全景空间的对应方位上。

请只看这张截图本身, 逐条判断:
1. 是不是黑屏、白屏、或者一大片纯色/破图(图片没加载出来)?
2. 是不是一个正常渲染出来的全景空间画面(能看出是个真实场景, 不是乱码色块)?
3. 照片缩略图钉点看着是不是贴在合理的位置? 有没有糊成一团挤在一起、或者飞在天上/悬在半空?
4. 页面上的文字有没有乱码、方框、明显重叠遮挡?

只输出一个 JSON 对象, 不要任何解释文字, 不要 markdown 围栏, 字段固定为:
{{"ok": true 或 false, "issues": ["中文问题描述"], "confidence": 0 到 1 的小数, "reason": "一句中文结论"}}
没发现问题就 ok=true 且 issues 为空数组。"""


def _data_url(path):
    """截图转 base64 data URL。顺手缩到 1024 宽、转 JPEG, 免得几 MB 的 PNG 把请求撑爆。"""
    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > 1024:
            im = im.resize((1024, max(1, round(im.height * 1024 / im.width))))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json(text):
    """严格解析模型回复。容忍两种常见脏输出: 套了 ```json 围栏、JSON 前后带客套话。
    解析不出来或字段不合规就抛异常, 由上层统一降级 —— 绝不猜测、绝不半信半疑地放行。"""
    if not text or not text.strip():
        raise ValueError("模型回复是空的")
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # 退一步: 抠出第一个 { 到最后一个 } 之间的部分再试一次
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"回复里找不到 JSON: {body[:120]}")
        data = json.loads(body[start:end + 1])

    if not isinstance(data, dict):
        raise ValueError("解析出来的不是 JSON 对象")
    if not isinstance(data.get("ok"), bool):
        raise ValueError(f"ok 字段不是布尔值: {data.get('ok')!r}")
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        raise ValueError("issues 字段不是数组")
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        raise ValueError(f"confidence 字段不是数字: {data.get('confidence')!r}")
    return {
        "ok": data["ok"],
        "issues": [str(x) for x in issues],
        "confidence": min(1.0, max(0.0, confidence)),
        "reason": str(data.get("reason", "")).strip() or "模型没给结论",
    }


def _stepfun_one(path, context, api_key, model):
    """对单张截图调一次阶跃星辰。只用 urllib(零新依赖), 30s 超时。
    网络/HTTP/解析任何一步炸了都往上抛, 由 judge_shots 统一降级。"""
    prompt = PROMPT.format(
        expect=context.get("expect") or "一个可走动的全景空间网页",
        title=context.get("title") or "(无标题)",
        photo_count=context.get("photoCount", 0),
    )
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 800,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _data_url(path)}},
            ],
        }],
    }
    req = urllib.request.Request(
        STEPFUN_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=STEPFUN_TIMEOUT) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(f"接口返回结构不认识: {json.dumps(body, ensure_ascii=False)[:200]}")
    return _extract_json(text)


def judge_stepfun(shot_paths, context, api_key, model):
    """阶跃星辰后端: 一张截图一次请求, 汇总成 gates.semantic。
    任何一张失败就整体抛异常 —— 半套结果比没结果更危险, 宁可整体降级到离线规则。"""
    per_shot = []
    issues = []
    confidences = []
    for p in shot_paths:
        got = _stepfun_one(p, context, api_key, model)
        file_id = _short(p)
        per_shot.append({
            "file": file_id,
            "ok": got["ok"],
            "issues": got["issues"],
            "reason": got["reason"],
        })
        confidences.append(got["confidence"])
        for msg in got["issues"]:
            issues.append(f"{file_id}: {msg}")

    _sp = _sprite_issues(context.get("sprites") or [], context.get("shotSprites"))
    issues.extend(_sp)
    sprite_bad = bool(_sp)
    bad = [i for i in per_shot if not i["ok"]]
    ok = bool(per_shot) and not bad and not sprite_bad

    if not per_shot:
        raise ValueError("没有截图可判")
    if ok:
        reason = f"{model} 验收 {len(per_shot)} 张截图, 都是正常渲染的全景空间画面"
    else:
        reason = f"{model} 判定 {len(bad)}/{len(per_shot)} 张截图不合格 —— " + "; ".join(issues[:3])

    return {
        "ok": ok,
        "confidence": round(float(sum(confidences) / len(confidences)), 2),
        "reason": reason,
        "issues": issues,
        "perShot": per_shot,
        "backend": "stepfun",
        "model": model,
        "degraded": False,
    }


# ---------------------------------------------------------------- 对外入口
def judge_shots(shot_paths, context):
    """第三闸入口。返回 report.json 里的 gates.semantic 对象 + backend/model/degraded。

    shot_paths: 渲染闸产出的截图绝对路径列表。
    context:    {"title":..., "photoCount": 4, "sprites": [...], "expect": "室内婚礼宴会厅全景漫游页面"}
    """
    context = context or {}
    mode = (os.environ.get("PSM_JUDGE") or "auto").strip().lower()
    api_key = (os.environ.get("STEPFUN_API_KEY") or "").strip()
    model = (os.environ.get("STEPFUN_MODEL") or "").strip() or STEPFUN_DEFAULT_MODEL

    if mode == "local":
        return judge_local(shot_paths, context)
    if mode not in ("stepfun", "auto"):
        # 环境变量写错了别静默按默认跑, 在 reason 里说清楚
        return judge_local(shot_paths, context, degraded=True,
                           degrade_reason=f"PSM_JUDGE={mode!r} 不认识, 只认 stepfun/local/auto")
    if not api_key:
        if mode == "auto":
            return judge_local(shot_paths, context)  # auto 下没 key 走本地是预期路径, 不算降级
        return judge_local(shot_paths, context, degraded=True,
                           degrade_reason="PSM_JUDGE=stepfun 但环境变量 STEPFUN_API_KEY 是空的")

    try:
        return judge_stepfun(shot_paths, context, api_key, model)
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace") if hasattr(e, "read") else ""
        why = f"阶跃星辰接口返回 HTTP {e.code}({detail.strip()})"
    except urllib.error.URLError as e:
        why = f"连不上阶跃星辰接口({e.reason})"
    except (TimeoutError, OSError) as e:
        why = f"请求阶跃星辰超时或网络出错({e})"
    except (ValueError, json.JSONDecodeError) as e:
        why = f"模型回复解析失败({e})"
    except Exception as e:  # 兜底: 第三闸自己绝不能把整条自检环带崩
        why = f"调用阶跃星辰时出了没预料到的错({type(e).__name__}: {e})"
    return judge_local(shot_paths, context, degraded=True, degrade_reason=why)


if __name__ == "__main__":
    # 自测: 把截图路径当参数传进来, 打印 gates.semantic 的 JSON
    paths = sys.argv[1:]
    if not paths:
        print(__doc__)
        sys.exit(1)
    demo_context = {
        "title": "夹具会话 · ballroom",
        "photoCount": 4,
        "expect": "室内婚礼宴会厅全景漫游页面",
        "sprites": [
            {"i": 0, "x": 640, "y": 400, "onScreen": True},
            {"i": 1, "x": 300, "y": 220, "onScreen": True},
        ],
    }
    print(json.dumps(judge_shots(paths, demo_context), ensure_ascii=False, indent=2))
