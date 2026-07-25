#!/usr/bin/env python3
"""
server/verify.py -- 自检环【编排器】: 页面生成出来之后, 不靠人眼自动验收它对不对。

一轮 = 三道闸 + 一次裁决:
  ① 结构闸 server/checks.py     -- manifest 字段/资源/比例/深度/方位/置信度, 确定性检查
  ② 渲染闸 server/render_probe.mjs -- 无头 Chrome 真跑一遍页面, 转几个朝向截图, 看有没有黑屏/报错
  ③ 语义闸 server/judge.py      -- 拿截图问视觉模型(或离线像素规则)"这画面看着对不对"
  ④ 裁决 -- 全过就收工; 只是照片置信度不够就调 server/repair.py 自愈后重来一轮;
           渲染/语义/结构致命项挂了, 还有次数就重来, 没次数就判 reject。

全程 humanInLoop 恒为 false: 从渲染到判定到重试到隔离坏数据, 没有人看过一眼。

产物 = 会话目录下的 report.json(契约 schema=psm-verify/1), 页面 server/report.html 读它。

跑法(仓库根目录):
    .venv/bin/python -m server.verify fixture --base-url http://localhost:8899
    .venv/bin/python -m server.verify fixture --base-url http://localhost:8899 --inject-fault photo
    .venv/bin/python -m server.verify fixture --restore
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server.checks import run_structural, low_confidence_photos  # noqa: E402
from server.judge import judge_shots  # noqa: E402
from server.repair import repair_low_confidence, load_clip, build_dense_bank, score_photo  # noqa: E402

SESSIONS_DIR = os.path.join(REPO_ROOT, "server", "sessions")
PROBE_SCRIPT = os.path.join(REPO_ROOT, "server", "render_probe.mjs")
NODE = "/opt/homebrew/bin/node" if os.path.exists("/opt/homebrew/bin/node") else "node"

CONF_MIN = 0.45          # 和 checks.py 默认阈值保持一致
MAX_SHOTS = 4            # 一轮最多截几个朝向(每张都要过一次语义闸, 别无限加)
PROBE_TIMEOUT = 180      # 渲染探针总超时(它自己就绪超时 30s, 这里是兜底)

# 投毒用的外来照片: 从 assets/walkdemo/ 里挑一个和会话全景明显不同的场景
FAULT_PHOTO_REL = "photos/_fault_foreign.jpg"
FAULT_SOURCES = {"chapel": "chapel_day_j2.jpg", "other": "ballroom_j2.jpg"}


def session_dir_of(session_id):
    return os.path.join(SESSIONS_DIR, str(session_id))


def _read_manifest(session_dir):
    try:
        with open(os.path.join(session_dir, "manifest.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _notify(on_stage, stage, attempt):
    """进度回调(上传页那条自检环进度条靠它点亮), 回调自己炸了不许拖累验收。"""
    if not on_stage:
        return
    try:
        on_stage(stage, attempt)
    except Exception:
        pass


# ---------------------------------------------------------------- 渲染闸
def probe_yaws(manifest):
    """挑几个相机朝向去截图。

    ⚠️ 页面的 setYaw(θ) 面向的方向是"照片 yaw = -θ"(相机 forward 是 (-sinθ,0,-cosθ),
    而照片钉点方向是 (+sinφ,·,-cosφ))。所以想让第 i 张照片入画, 要传 -yaw_i。
    没有照片就退回三个固定朝向, 至少证明全景本身渲染出来了。

    朝向按"置信度从低到高"挑: 一轮只截 MAX_SHOTS 张, 那就把镜头优先转向最不放心的那几张
    照片 —— 验收要看的本来就是最可能出错的地方, 而不是排在前面的那几张。
    """
    def conf_of(p):
        v = p.get("confidence")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else -1.0

    photos = sorted(
        [p for p in (manifest.get("photos") or []) if isinstance(p, dict)], key=conf_of)
    yaws, seen = [], set()
    for p in photos:
        try:
            y = int(round(-float(p.get("yaw", 0)))) % 360
        except (TypeError, ValueError):
            continue
        if y not in seen:
            seen.add(y)
            yaws.append(y)
        if len(yaws) >= MAX_SHOTS:
            break
    return yaws or [0, 120, 240]


def manifest_url(base_url, session_id):
    """会话 manifest 的可访问 URL。compose_server 把会话挂在 /sessions/<id>/, 而裸
    python -m http.server 从仓库根开, 路径是 /server/sessions/<id>/ —— 两种都试一下,
    通哪个用哪个, 这样同一支编排器在真服务器和静态服务下都能跑。"""
    candidates = [
        "/sessions/%s/manifest.json" % session_id,
        "/server/sessions/%s/manifest.json" % session_id,
    ]
    base = base_url.rstrip("/")
    for path in candidates:
        try:
            with urllib.request.urlopen(base + path, timeout=5) as resp:
                if resp.status == 200:
                    return path
        except Exception:
            continue
    return candidates[0]  # 都不通就用标准路径, 让渲染闸如实报"加载失败"


def run_render_gate(base_url, session_id, session_dir, attempt, manifest):
    """老签名保持不动(旧 CLI / compose_server 那条路还在用): 自己拼会话页面的 URL 再往下走。"""
    url = "%s/viewer/walk.html?compose=%s" % (
        base_url.rstrip("/"), manifest_url(base_url, session_id))
    return run_render_gate_url(url, session_dir, attempt, manifest)


def run_render_gate_url(url, work_dir, attempt, manifest):
    """subprocess 调 node 探针。探针的 stdout 只有一行 JSON = gates.render。
    页面 URL 由调用方给 —— 会话是 walk.html?compose=...,空间是 walk.html?space=...&node=...,
    对探针来说都一样: 起 Chrome、等 __psmWalk、转几个朝向截图。"""
    shots_dir = os.path.join(work_dir, "shots")
    yaws = probe_yaws(manifest)
    cmd = [NODE, PROBE_SCRIPT, "--url", url, "--out", shots_dir,
           "--prefix", "a%d" % attempt, "--yaws", ",".join(str(y) for y in yaws)]

    empty = {"ok": False, "readyMs": None, "shots": [], "consoleErrors": [],
             "pageErrors": [], "error": None, "sprites": []}
    try:
        r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        empty["error"] = "渲染探针超过 %d 秒没返回, 已强制中止" % PROBE_TIMEOUT
        return empty
    except FileNotFoundError:
        empty["error"] = "找不到 node(%s), 渲染闸跑不了" % NODE
        return empty

    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    if not lines:
        empty["error"] = "渲染探针没有输出(退出码 %s), stderr 末尾: %s" % (
            r.returncode, (r.stderr or "")[-300:].strip())
        return empty
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        empty["error"] = "渲染探针输出不是 JSON: %s" % lines[-1][:300]
        return empty


# ---------------------------------------------------------------- 语义闸
def run_semantic_gate(render_gate, manifest):
    """把渲染闸截的图交给判官。返回 (gates.semantic, judge 元信息)。
    渲染闸没出图就不判 —— 没有截图的"语义合格"是假结论, 宁可留空。"""
    abs_paths = [s.get("abs") for s in render_gate.get("shots") or [] if s.get("abs")]
    if not abs_paths:
        return None, None
    context = {
        "title": manifest.get("title") or "我的空间",
        "photoCount": len(manifest.get("photos") or []),
        "expect": "一个可走动的全景空间网页, 照片缩略图钉在全景里对应的方位上",
        "sprites": render_gate.get("sprites") or [],
        # 逐张截图各自的钉点坐标: 判"钉点挤成一团"必须在同一张图里比,
        # 拿跨朝向汇总的坐标去比会误报(见 judge._sprite_issues 的注释)。
        "shotSprites": [s.get("sprites") or [] for s in render_gate.get("shots") or []],
    }
    got = judge_shots(abs_paths, context)
    meta = {
        "backend": got.pop("backend", "local"),
        "model": got.pop("model", None),
        "degraded": bool(got.pop("degraded", False)),
    }
    return got, meta


# ---------------------------------------------------------------- 投毒(演示用)
def _backup(path):
    """备份成 *.bak; 已经有备份就不覆盖(那份才是干净的原件)。"""
    bak = path + ".bak"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy2(path, bak)


def restore_session(session_dir):
    """把投毒动过的文件全部还原, 返回中文说明列表。演示可以反复跑。"""
    done = []
    for name in ("manifest.json", "depth.png"):
        path = os.path.join(session_dir, name)
        bak = path + ".bak"
        if os.path.exists(bak):
            shutil.move(bak, path)
            done.append("已还原 %s(并删除备份)" % name)
    fault_photo = os.path.join(session_dir, FAULT_PHOTO_REL)
    if os.path.exists(fault_photo):
        os.remove(fault_photo)
        done.append("已删除投毒照片 %s" % FAULT_PHOTO_REL)
    return done or ["没有需要还原的东西(该会话没被投毒过)"]


def inject_fault(session_dir, kind, model=None):
    """演示用的故意投毒。投之前先把上一次的毒还原干净, 保证每次投毒都从同一个起点出发。

    photo    -- 塞一张明显不属于这个空间的照片(会话是宴会厅就塞教堂的裁切),
                yaw 是随手编的, confidence 是当场用 CLIP 真算出来的, 不编数字。
    depth    -- 把 depth.png 涂成纯灰: 深度模型输出全平, 结构闸的 depth_sane 必挂。
    manifest -- 把第一张照片的 yaw 改成 400(越界), 结构闸的 photo_coords 必挂。
    """
    restore_session(session_dir)
    manifest_path = os.path.join(session_dir, "manifest.json")

    if kind == "depth":
        from PIL import Image
        depth_path = os.path.join(session_dir, "depth.png")
        _backup(depth_path)
        with Image.open(depth_path) as im:
            size = im.size
        Image.new("I;16", size, 32768).save(depth_path)
        return "已把 depth.png 涂成纯灰(%dx%d 全 32768), 深度图变成一块死板" % size

    _backup(manifest_path)
    manifest = _read_manifest(session_dir)

    if kind == "manifest":
        photos = manifest.get("photos") or []
        if not photos:
            return "会话里没有照片, manifest 投毒无从下手"
        photos[0]["yaw"] = 400.0
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return "已把 %s 的 yaw 改成 400(越界)" % photos[0].get("src", "第一张照片")

    if kind == "photo":
        title = str(manifest.get("title") or "")
        # 会话本身就是教堂就换宴会厅, 保证塞进去的确实是"别的空间"
        src_name = FAULT_SOURCES["other"] if ("chapel" in title or "教堂" in title) else FAULT_SOURCES["chapel"]
        src = os.path.join(REPO_ROOT, "assets", "walkdemo", src_name)
        dest = os.path.join(session_dir, FAULT_PHOTO_REL)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy(src, dest)

        # 置信度真算: 拿这张外来照片去和本会话全景的 72 张裁切比一遍, 写真实数字
        model = load_clip(model)
        bank = build_dense_bank(os.path.join(session_dir, manifest.get("panorama") or "pano.jpg"), model)
        _yaw, _pitch, conf = score_photo(bank, model, dest)

        photos = manifest.setdefault("photos", [])
        photos.append({
            "src": FAULT_PHOTO_REL, "yaw": 300.0, "pitch": 0,  # yaw 是随手编的
            "confidence": conf, "by": "auto", "caption": "投毒照片(%s)" % src_name,
        })
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return "已塞入外来照片 %s(来自 %s), 随手编的 yaw=300, 真实算出的置信度=%.4f" % (
            FAULT_PHOTO_REL, src_name, conf)

    return "不认识的投毒类型: %s" % kind


# ---------------------------------------------------------------- 编排主体
def verify_session(session_id, base_url="http://127.0.0.1:8777", max_attempts=2,
                   inject_fault_kind=None, model=None, conf_min=CONF_MIN, on_stage=None):
    """跑完整条自检环, 写 <session_dir>/report.json 并返回它的内容。

    这是【会话】用法(compose_server 的一次性合成 + 旧 CLI), 签名和行为一个字没变;
    真正干活的是下面的 verify_target —— 它不认"会话", 只认"一个目录 + 一个页面 URL"。
    """
    session_id = str(session_id)
    session_dir = session_dir_of(session_id)
    if not os.path.isdir(session_dir):
        return {
            "schema": "psm-verify/1", "session": session_id, "verdict": "reject",
            "reason": "会话目录不存在: server/sessions/%s" % session_id,
            "humanInLoop": False, "elapsedS": 0.0,
            "judge": {"backend": "local", "model": None, "degraded": False}, "attempts": [],
        }
    page_url = "%s/viewer/walk.html?compose=%s" % (
        base_url.rstrip("/"), manifest_url(base_url, session_id))
    return verify_target(session_dir, page_url, label=session_id, max_attempts=max_attempts,
                         inject_fault_kind=inject_fault_kind, model=model,
                         conf_min=conf_min, on_stage=on_stage)


def verify_target(work_dir, page_url, label="", max_attempts=2, inject_fault_kind=None,
                  model=None, conf_min=CONF_MIN, on_stage=None, write_report=True):
    """自检环的通用入口: 对【任意目录 + 任意页面 URL】跑三闸一裁决, 写 <work_dir>/report.json。

    work_dir 里必须有一份 manifest.json(结构闸读它, 里面的资源路径相对 work_dir),
    page_url 是那个"应该把这份 manifest 渲染出来"的页面 —— 渲染闸就去真跑它。

    会话(server/sessions/<id>/)和空间(server/spaces/<sid>/)两边目录长得不一样,
    但对这三道闸来说没有区别, 所以不必为空间另写一套编排。
    """
    t0 = time.time()
    label = str(label or os.path.basename(os.path.normpath(work_dir)))
    report = {
        "schema": "psm-verify/1", "session": label,
        "verdict": "reject", "reason": "", "humanInLoop": False, "elapsedS": 0.0,
        "judge": {"backend": "local", "model": None, "degraded": False},
        "attempts": [],
    }

    if not os.path.isdir(work_dir):
        report["reason"] = "目录不存在: %s" % work_dir
        report["elapsedS"] = round(time.time() - t0, 1)
        return report

    if inject_fault_kind:
        _notify(on_stage, "inject", 0)
        print("[投毒] " + inject_fault(work_dir, inject_fault_kind, model), flush=True)

    session_dir = work_dir     # 下面沿用原来的变量名, 少动一行是一行
    verdict = reason = None
    for n in range(1, max_attempts + 1):
        last_round = (n == max_attempts)
        manifest = _read_manifest(session_dir)

        _notify(on_stage, "structural", n)
        structural = run_structural(session_dir, conf_min)

        _notify(on_stage, "render", n)
        render = run_render_gate_url(page_url, session_dir, n, manifest)

        _notify(on_stage, "semantic", n)
        semantic, judge_meta = run_semantic_gate(render, manifest)
        if judge_meta:
            report["judge"] = judge_meta
        # abs 是探针给第三闸带路用的绝对路径, 报告里不留(契约没有它, 也没必要泄露本机路径)
        for shot in render.get("shots") or []:
            shot.pop("abs", None)

        _notify(on_stage, "verdict", n)
        failed = structural.get("failed") or []
        struct_clean = bool(structural.get("ok")) and not failed
        only_conf = bool(structural.get("ok")) and failed == ["photo_confidence"]
        render_ok = bool(render.get("ok"))
        semantic_ok = bool(semantic and semantic.get("ok"))

        attempt = {"n": n, "gates": {"structural": structural, "render": render,
                                     "semantic": semantic}, "action": "accept", "repairs": []}

        if struct_clean and render_ok and semantic_ok:
            attempt["action"] = "accept"
            report["attempts"].append(attempt)
            verdict = "pass"
            reason = ("第 %d 次尝试三闸全过: 结构 6 项全对、页面真渲染出画面且无报错(%d 张截图)、"
                      "判官认为画面正常(置信度 %.2f), 全程没有人看过一眼。" % (
                          n, len(render.get("shots") or []), (semantic or {}).get("confidence", 0.0)))
            break

        if last_round:
            quarantined = len(manifest.get("quarantined") or [])
            if only_conf and render_ok and semantic_ok:
                # 只剩"某几张照片置信度不够"这一项: 页面是能用的, 判过, 但要如实交代隔离了几张
                attempt["action"] = "accept"
                verdict = "pass"
                still_low = len(low_confidence_photos(session_dir, conf_min))
                reason = ("渲染和语义两闸都过, 只剩照片置信度不达标: 自愈已隔离 %d 张低置信照片, "
                          "仍有 %d 张低于阈值 %.2f 但不影响页面可用, 判通过。" % (quarantined, still_low, conf_min))
            else:
                attempt["action"] = "give_up"
                verdict = "reject"
                reason = "第 %d 次尝试仍不合格且没有重试次数了: %s" % (n, _why_failed(
                    structural, render, semantic, failed))
            report["attempts"].append(attempt)
            break

        # 还有次数: 这一轮判 repair。能自动修的只有"照片置信度"这一类, 其余问题
        # (渲染挂了/语义不合格/结构致命项)没有自动修的手段, 那就空手重来一轮, 但如实记 repairs=[]
        attempt["action"] = "repair"
        if "photo_confidence" in failed:
            _notify(on_stage, "repair", n)
            idx = low_confidence_photos(session_dir, conf_min)
            attempt["repairs"] = repair_low_confidence(session_dir, idx, conf_min, model)
        report["attempts"].append(attempt)

    report["verdict"] = verdict or "reject"
    report["reason"] = reason or "自检环没有得出结论。"
    report["elapsedS"] = round(time.time() - t0, 1)

    if write_report:
        with open(os.path.join(session_dir, "report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    _notify(on_stage, "done", len(report["attempts"]))
    return report


def _why_failed(structural, render, semantic, failed):
    """把三闸的失败原因拼成一句人话, 给 reject 的 reason 用。"""
    bits = []
    fatal = [c for c in structural.get("checks") or [] if not c["ok"] and c["id"] != "photo_confidence"]
    if fatal:
        bits.append("结构闸 %s 不过(%s)" % (fatal[0]["id"], fatal[0]["detail"][:60]))
    if not render.get("ok"):
        bits.append("渲染闸不过(%s)" % (render.get("error") or "页面没渲染出来"))
    if semantic is None:
        bits.append("语义闸没跑成(没有截图可判)")
    elif not semantic.get("ok"):
        bits.append("语义闸不过(%s)" % str(semantic.get("reason"))[:80])
    if not bits and "photo_confidence" in failed:
        bits.append("照片置信度仍不达标")
    return "; ".join(bits) or "原因不详"


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="空间记忆 · 自检环")
    ap.add_argument("session", help="会话 id(server/sessions/ 下的目录名)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8777")
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--conf-min", type=float, default=CONF_MIN, help="照片置信度阈值(默认 0.45)")
    ap.add_argument("--inject-fault", choices=("photo", "depth", "manifest"),
                    help="演示用的故意投毒, 跑完可用 --restore 还原")
    ap.add_argument("--restore", action="store_true", help="还原投毒过的会话文件后退出")
    args = ap.parse_args()

    session_dir = session_dir_of(args.session)
    if args.restore:
        for line in restore_session(session_dir):
            print(line)
        return

    def on_stage(stage, n):
        print("  [第 %s 轮] %s" % (n, stage), flush=True)

    report = verify_session(
        args.session, base_url=args.base_url, max_attempts=args.max_attempts,
        inject_fault_kind=args.inject_fault, conf_min=args.conf_min, on_stage=on_stage,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n== 裁决: %s == %s" % (report["verdict"], report["reason"]), flush=True)


if __name__ == "__main__":
    main()
