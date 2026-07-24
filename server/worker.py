#!/usr/bin/env python3
"""
server/worker.py -- Mac 侧的后台工人: 把云上宾客直传的新照片捞回来算。

为什么要有这么个东西: 现场宾客的手机连不上 Max 的电脑(也不该连)。宾客的照片用
oss.post_policy 签出来的策略【直接 POST 进 OSS】, 谁都不用暴露到公网; 然后 Max 的
电脑在旁边当一个后台工人, 循环干这五件事:

    列 OSS 收件箱 -> 发现新照片 -> 下载 -> 复用 space.py 做 CLIP 定位+双判据分流
    -> 更新本地 space.json -> 重新发布到 OSS

也就是说: **照片不经过任何服务器, 计算全在本机, 结果再推回云上。**

跑法(cwd 必须是仓库根目录):
    .venv/bin/python -m server.worker s4 --once          # 收一轮就退
    .venv/bin/python -m server.worker s4 --interval 5    # 常驻, Ctrl-C 干净退出
    .venv/bin/python -m server.worker s4 --purge-inbox   # 活动结束后清云端收件箱

⚠️ 工人是独立进程, 会自己加载一份 CLIP(约 10-20 秒)。如果 compose_server 也在跑,
   两个进程各占一份模型内存(每份约 1GB), 这是预期行为, 不是 bug。

【宾客页必须按这个约定拼 key】(做 join 页的工兵看这里):
    spaces/<sid>/inbox/<时间戳毫秒>_<随机短id>__<encodeURIComponent(昵称)>__<taskId或none>.jpg
  例: spaces/s4/inbox/1784900000123_a7f3__%E5%B0%8F%E6%98%8E__t2.jpg
  · 三段用【双下划线】分隔, 昵称必须 url 编码(中文/空格/表情都安全)
  · 没接任务就写 none; 昵称为空就留空(工人会记成"匿名宾客")
  · 解析失败一律降级成匿名投稿, 绝不丢照片
"""
import argparse
import json
import os
import sys
import time
import urllib.parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import oss, space  # noqa: E402

STATE_NAME = ".ingested.json"      # 已处理台账, 放在空间目录里
STATE_SCHEMA = "psm-ingested/1"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ================================================================ 收件箱 / 台账
def inbox_prefix(sid):
    """宾客直传的落点。⚠️ 必须和 server/publish.py 的 inbox_prefix 一模一样 ——
    发布器把这个前缀连同直传策略写进公开版 space.json, 宾客照它传, 工人照它收。"""
    return f"spaces/{sid}/inbox/"


def state_path(sid):
    return os.path.join(space.space_dir(sid), STATE_NAME)


def load_state(sid):
    """读已处理台账。坏了/没有就当空的重来 —— 台账只是去重用的, 不值得为它崩掉整条队列。"""
    path = state_path(sid)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            if isinstance(st.get("keys"), dict):
                return st
        except Exception as e:
            log(f"⚠️ 台账读坏了({e}), 当空的重建 —— 已入库的照片可能会被重算一次")
    return {"schema": STATE_SCHEMA, "spaceId": sid, "keys": {}}


def save_state(sid, st):
    """先写临时文件再 os.replace, 和 space.save_space 一个路数: 写一半断电不会毁台账。"""
    path = state_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def parse_key(key):
    """从 OSS key 解析出 (投稿人, taskId)。约定见文件顶部。

    ⚠️ 必须健壮: 这段字符串是宾客手机拼的, 什么鬼东西都可能进来。
       解析不出来就当匿名投稿, 绝不抛异常 —— 丢一个昵称是小事, 丢一张照片是事故。
    """
    stem = os.path.splitext(os.path.basename(key))[0]
    parts = stem.split("__")

    contributor = ""
    if len(parts) >= 2:
        try:
            contributor = urllib.parse.unquote_plus(parts[1])
        except Exception:
            contributor = ""
        contributor = " ".join(contributor.split())[:24]     # 压掉换行/连续空格, 限长

    task_id = None
    if len(parts) >= 3:
        t = parts[2].strip()
        if t and t.lower() not in ("none", "null", "undefined", "-"):
            task_id = t[:16]

    return (contributor or "匿名宾客"), task_id


def is_image_key(key):
    return os.path.splitext(key)[1].lower() in space.IMAGE_EXTS


def _why(conf, margin):
    """把双判据的结果压成一句短话, 给日志用(完整理由在 space.py 里写进 photo.reason)。"""
    if conf < space.CONF_MIN and margin < space.MARGIN_MIN:
        return "不像这个空间"
    if margin < space.MARGIN_MIN:
        return "跟哪个方向都差不多像"
    return "方位拿不准"


# ================================================================ 重新发布
def republish(sid, conf=None):
    """处理完把空间重新推回 OSS(增量, 只传变了的文件)。

    publish.py 万一还没就绪就先兜住并如实打日志 —— 工人自己的活(下载/定位/分流/落盘)
    已经完成了, 不能因为发布模块缺席就算这轮白跑, 补跑一次发布即可。
    """
    try:
        from server import publish        # 延迟导入: 这个模块可能还不存在
    except Exception as e:
        log(f"⚠️ 暂时发布不了(server/publish.py 还没就绪: {e}) —— 照片已算好落盘, 补跑发布即可")
        return None
    try:
        r = publish.publish_space(sid, conf=conf)
        log(f"已重新发布 → 新传 {r['uploaded']} 个文件, 跳过 {r['skipped']} 个, 耗时 {r['elapsedS']}s")
        return r
    except Exception as e:
        log(f"⚠️ 发布失败: {e} —— 照片已算好落盘, 补跑发布即可")
        return None


# ================================================================ 主循环
def poll_once(sid, conf=None, log_empty=True, do_publish=True):
    """收一轮。返回 {ok, listed, new, processed, failed, results, published}。

    幂等靠台账: 同一个 key 处理过就永远不再处理, 重启工人不会重算、不会重复加分。
    """
    conf = conf or oss.load_conf()
    st = load_state(sid)
    done = st["keys"]

    try:
        listed = oss.list_keys(conf, inbox_prefix(sid))
    except Exception as e:
        log(f"⚠️ 列云端收件箱失败(下一轮再试): {e}")
        return {"ok": False, "error": str(e), "listed": 0, "new": 0,
                "processed": 0, "failed": 0, "results": [], "published": None}

    # 只认没处理过的、非空的图片(目录占位对象和半截上传都挡掉)
    fresh = [it for it in listed
             if it["key"] not in done and it["size"] > 0 and is_image_key(it["key"])]
    fresh.sort(key=lambda it: it["key"])        # key 以时间戳打头, 排序 ≈ 按上传先后

    if not fresh:
        if log_empty:
            log(f"没有新照片(云端收件箱 {len(listed)} 个对象, 台账已记 {len(done)} 个)")
        return {"ok": True, "listed": len(listed), "new": 0,
                "processed": 0, "failed": 0, "results": [], "published": None}

    # 已知任务 id, 用来挡掉宾客页传来的野 taskId(带个不存在的任务会让积分/任务状态错乱)
    try:
        known_tasks = {t["id"] for t in space.load_space(sid).get("tasks", [])}
    except FileNotFoundError as e:
        log(f"⚠️ {e} —— 先在后台建好空间再开工人")
        return {"ok": False, "error": str(e), "listed": len(listed), "new": len(fresh),
                "processed": 0, "failed": 0, "results": [], "published": None}

    results, failed = [], 0
    for item in fresh:
        key = item["key"]
        contributor, task_id = parse_key(key)
        if task_id and task_id not in known_tasks:
            task_id = None                      # 野 taskId 直接丢掉, 让自动判定去接
        try:
            raw = oss.get_bytes(conf, key)
            out = space.upload_photos(
                sid, [(os.path.basename(key), oss.guess_type(key), raw)],
                contributor, task_id=task_id,
            )
            r = out[0]
            # 回读一眼 margin: upload_photos 的返回里没带, 但日志和台账想说人话就得有它
            with space.space_txn(sid, write=False) as sp:
                rec = next((p for p in sp["photos"] if p["id"] == r["photoId"]), {})
            margin = rec.get("margin", 0.0)

            done[key] = {"photoId": r["photoId"], "state": r["state"],
                         "contributor": contributor, "taskId": r.get("taskFilled") or task_id,
                         "confidence": r["confidence"], "margin": margin, "at": time.time()}
            results.append({"key": key, "photoId": r["photoId"], "state": r["state"],
                            "nodeId": r["nodeId"], "yaw": r["yaw"], "direction": r["direction"],
                            "confidence": r["confidence"], "margin": margin,
                            "contributor": contributor, "taskFilled": r.get("taskFilled")})
        except Exception as e:
            # 下载坏了/解码失败/定位炸了: 记一笔 failed 就翻篇, 别让一张烂图卡住整条队列。
            # (upload_photos 是先占 id 建空文件再落盘的, 所以炸掉的那张会在 photos/ 留一个
            #  没人认领的 pX.jpg。故意不去扫它: space.json 里没有记录 = 发布器不会传、
            #  前端不会显示; 而"扫掉所有没记录的文件"会误杀 compose_server 正在上传的占位文件。)
            failed += 1
            done[key] = {"failed": True, "error": str(e)[:300],
                         "contributor": contributor, "at": time.time()}
            log(f"⚠️ {os.path.basename(key)} 处理失败, 记账跳过: {e}")
        save_state(sid, st)      # 每张都落盘: 中途 Ctrl-C / 断电也不会重算已经算完的

    # 一行人话日志: 收到 2 张 → p4 入选(右后方) / p5 待审(不像这个空间)
    if results:
        bits = []
        for r in results:
            if r["state"] in space.SELECTED_STATES:
                s = f"{r['photoId']} 入选({r['direction']})"
                if r["taskFilled"]:
                    s += f" 完成任务{r['taskFilled']}"
            else:
                s = f"{r['photoId']} 待审({_why(r['confidence'], r['margin'])})"
            bits.append(s)
        tail = f", {failed} 张失败" if failed else ""
        log(f"收到 {len(fresh)} 张{tail} → " + " / ".join(bits))
    else:
        log(f"收到 {len(fresh)} 张, 全部处理失败")

    published = republish(sid, conf) if (do_publish and results) else None
    return {"ok": True, "listed": len(listed), "new": len(fresh), "processed": len(results),
            "failed": failed, "results": results, "published": published}


def run_forever(sid, interval=5, conf=None):
    """常驻循环。Ctrl-C 干净退出(台账每张都已经落盘, 不会丢进度)。"""
    conf = conf or oss.load_conf()
    log(f"工人上岗: 空间 {sid} ← oss://{conf['bucket']}/{inbox_prefix(sid)}, 每 {interval}s 看一眼")
    space.get_clip_model()      # 先把 CLIP 加载完, 别让第一个宾客等这 10-20 秒
    log("CLIP 就绪, 开始盯收件箱(Ctrl-C 收工)")

    idle = 0
    quiet_rounds = max(1, int(60 / max(interval, 1)))    # 大约每分钟报一次平安
    try:
        while True:
            res = poll_once(sid, conf, log_empty=False)
            if res.get("processed"):
                idle = 0
            else:
                idle += 1
                if idle % quiet_rounds == 0:
                    log(f"等新照片中…(已守 {idle * interval // 60} 分钟)")
            time.sleep(interval)
    except KeyboardInterrupt:
        log("收工(Ctrl-C), 台账已落盘, 下次开工从这里接着来")


def purge_inbox(sid, conf=None):
    """活动结束后清云端收件箱。

    平时【绝不删】宾客的原图: 那是人家的东西, 也是"这张照片真是现场传的"的证据,
    去重靠台账不靠删文件。只有活动收尾、Max 明确要清的时候才走这条路。
    """
    conf = conf or oss.load_conf()
    keys = oss.list_keys(conf, inbox_prefix(sid))
    n = 0
    for it in keys:
        try:
            oss.delete(conf, it["key"])
            n += 1
        except Exception as e:
            log(f"⚠️ 删不掉 {it['key']}: {e}")
    log(f"云端收件箱已清: 删了 {n}/{len(keys)} 个对象(本地原图和台账都还在)")
    return n


def main():
    ap = argparse.ArgumentParser(description="空间记忆 · Mac 侧后台工人(从 OSS 收宾客照片)")
    ap.add_argument("sid", help="空间 id, 例如 s4")
    ap.add_argument("--once", action="store_true", help="只收一轮就退出")
    ap.add_argument("--interval", type=float, default=5, help="轮询间隔秒数, 默认 5")
    ap.add_argument("--purge-inbox", action="store_true", help="清空云端收件箱(活动结束再用)")
    ap.add_argument("--no-publish", action="store_true", help="算完不重新发布(调试用)")
    args = ap.parse_args()

    try:
        conf = oss.load_conf()
    except Exception as e:
        log(f"❌ 读不到阿里云凭据: {e}")
        log("   凭据应该在 ~/.config/psm/aliyun.json(bucket/region/accessKeyId/accessKeySecret)")
        return 2

    if args.purge_inbox:
        purge_inbox(args.sid, conf)
        return 0

    if args.once:
        res = poll_once(args.sid, conf, do_publish=not args.no_publish)
        return 0 if res.get("ok") else 1

    run_forever(args.sid, args.interval, conf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
