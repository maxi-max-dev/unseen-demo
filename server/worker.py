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
    spaces/<sid>/inbox-v2/gN/<时间戳毫秒>_<随机短id>__<base64url昵称>__<taskId或free>.jpg
  例: spaces/s4/inbox-v2/g1/1784900000123_a7f3__5bCP5piO__t2.jpg
  · 三段用【双下划线】分隔, 昵称必须 url 编码(中文/空格/表情都安全)
  · 没接任务就写 none; 昵称为空就留空(工人会记成"匿名宾客")
  · 解析失败一律降级成匿名投稿, 绝不丢照片

批次E新增(2026-07-28): 主办方自助建空间后, 自己传的全景走另一条独立通道
spaces/<sid>/pano-inbox/<时间戳毫秒>_<随机短id>.<ext>(建 key 的代码在
app/create.html), poll_panos_once() 每轮和照片收件箱一起看一眼, 新全景直接
调 space.add_node() 建真节点, 成功就把空间从草稿推成发布(自助建空间没有
另一个"发布"按钮可点, 传第一张全景进去就该是宾客能扫码看到的那一刻)。
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

# 心跳文件: 工人每轮写一次时间戳, 新人后台读它显示"后台工人: 运行中 / 未运行"。
# 为什么必须有: 忘了起工人的话, 宾客传的照片会一直躺在 OSS 收件箱里没人算,
# 页面上什么都不会变 —— 现场当场懵。让后台把这件事摆在脸上。
HEARTBEAT_NAME = ".worker.json"
HEARTBEAT_STALE_S = 60             # 60 秒内有心跳算在跑(和 space.py 的判定保持一致)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ================================================================ 收件箱 / 台账
def inbox_prefix(sid, current=None):
    """宾客直传的落点。⚠️ 必须和 server/publish.py 的 inbox_prefix 一模一样 ——
    发布器把这个前缀连同直传策略写进公开版 space.json, 宾客照它传, 工人照它收。"""
    if current is None:
        current = space.load_space(sid)
    return space._inbox_prefix(sid, current)


def state_path(sid):
    return os.path.join(space.space_dir(sid), STATE_NAME)


def beat(sid, note=""):
    """写一次心跳。写不成就算了 —— 心跳只是给后台看的仪表盘, 不值得为它中断收照片。"""
    try:
        path = os.path.join(space.space_dir(sid), HEARTBEAT_NAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "at": time.time(), "note": note}, f)
    except Exception:
        pass


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


PANO_STATE_NAME = ".pano_ingested.json"     # 全景收件箱的已处理台账, 和照片台账分开存


def pano_state_path(sid):
    return os.path.join(space.space_dir(sid), PANO_STATE_NAME)


def load_pano_state(sid):
    """读全景已处理台账。坏了/没有就当空的重来, 道理和 load_state() 一样。"""
    path = pano_state_path(sid)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            if isinstance(st.get("keys"), dict):
                return st
        except Exception as e:
            log(f"⚠️ 全景台账读坏了({e}), 当空的重建 —— 已入库的全景可能会被重算一次")
    return {"schema": "psm-pano-ingested/1", "spaceId": sid, "keys": {}}


def save_pano_state(sid, st):
    path = pano_state_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def sweep_retired_inboxes(sid, conf, current=None):
    """旧场景的上传策略在过期前仍可能被离线手机使用，工人每轮都把旧代清空。"""
    current = current or space.load_space(sid)
    records = space._normal_retired_inboxes(sid, current)
    if not records:
        return {"deleted": 0, "warnings": []}
    current_prefix = inbox_prefix(sid, current)
    legacy_root = f"spaces/{sid}/inbox/"
    deleted = 0
    warnings = []
    clearable = set()
    for record in records:
        retired_prefix = record["prefix"]
        if retired_prefix == current_prefix:
            continue
        try:
            objects = oss.list_keys(conf, retired_prefix)
        except Exception as e:
            warnings.append(f"{retired_prefix}: {type(e).__name__}")
            continue
        clean = True
        for item in objects:
            key = str(item.get("key") or "")
            suffix = key[len(retired_prefix):] if key.startswith(retired_prefix) else ""
            if not suffix or ".." in suffix.split("/"):
                clean = False
                continue
            if retired_prefix == legacy_root and "/" in suffix:
                continue
            try:
                oss.delete(conf, key)
                deleted += 1
            except Exception as e:
                if "HTTP 404" not in str(e):
                    clean = False
                    warnings.append(f"{key}: {type(e).__name__}")
        if clean and time.time() >= float(record["expiresAt"]):
            clearable.add(retired_prefix)
    if clearable:
        with space.space_txn(sid) as latest:
            left = [
                record for record in space._normal_retired_inboxes(sid, latest)
                if record["prefix"] not in clearable
            ]
            if left:
                latest["_retiredInboxPrefixes"] = left
            else:
                latest.pop("_retiredInboxPrefixes", None)
    return {"deleted": deleted, "warnings": warnings}


def _decode_nick(raw):
    """把宾客页 base64url 编过的昵称解回来。解不出来就退回 URL 解码, 再不行就原样。"""
    import base64
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        pad = "=" * (-len(s) % 4)
        out = base64.urlsafe_b64decode(s + pad).decode("utf-8")
        if out.strip():
            return out
    except Exception:
        pass
    try:
        return urllib.parse.unquote_plus(s)
    except Exception:
        return s


def parse_key(key):
    """从 OSS key 解析出 (投稿人, taskId)。约定见文件顶部。

    ⚠️ 必须健壮: 这段字符串是宾客手机拼的, 什么鬼东西都可能进来。
       解析不出来就当匿名投稿, 绝不抛异常 —— 丢一个昵称是小事, 丢一张照片是事故。

    ⚠️ 7/24 修的一个真实事故: 宾客页(web/join.html)用的是 **base64url** 编码昵称
       (btoa 之后把 +/ 换成 -_ 、去掉尾部 =), 这里原来只做 URL 解码, 于是中文昵称
       原样变成 "5L2g5aSn54i3" 这种乱码进了贡献者榜。两个模块各写各的、契约漂移。
       现在先试 base64url, 失败再退回 URL 解码(兼容老 key), 都不成就按原文。
    """
    stem = os.path.splitext(os.path.basename(key))[0]
    parts = stem.split("__")

    contributor = ""
    if len(parts) >= 2:
        contributor = _decode_nick(parts[1])
        contributor = " ".join(contributor.split())[:24]     # 压掉换行/连续空格, 限长

    task_id = None
    if len(parts) >= 3:
        t = parts[2].strip()
        # "free" 是宾客页(web/join.html)对"没接任务"的写法, "none" 是本文件顶部的老约定,
        # 两边都认 —— 契约漂移过一次(昵称编码), 这里就别再赌第二次。
        if t and t.lower() not in ("none", "free", "null", "undefined", "-"):
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
        r = None
        for _attempt in range(3):
            r = publish.publish_space(sid, conf=conf)
            if not r.get("stale"):
                break
            log("发布期间空间有新变化,正在改用最新版本重试")
        log(f"已重新发布 → 新传 {r['uploaded']} 个文件, 跳过 {r['skipped']} 个, 耗时 {r['elapsedS']}s")
        return r
    except Exception as e:
        log(f"⚠️ 发布失败: {e} —— 照片已算好落盘, 补跑发布即可")
        return None


# ================================================================ 直传许可续签
# 公开快照里带的上传 Policy 固定 48 小时(publish.UPLOAD_EXPIRE_S)。以前只有"重新发布"
# 这个动作才会签发新的一段 —— 一个没人动的空间到点就过期, 宾客直传直接 403。
# s4 真炸过一次(BLOCKED.md 里那条 "Invalid according to Policy: Policy expired")。
# 所以工人自己盯着: 剩余不足 24 小时就主动重发一次快照, 顺手把许可续上。
POLICY_RENEW_BEFORE_S = 24 * 3600
# 续签失败(断网/OSS 抽风)后的冷却。不加这个, 每 5 秒重试一次会把日志刷爆,
# 还会对着一个连不上的 OSS 猛敲。
POLICY_RETRY_COOLDOWN_S = 300
_policy_retry_after = {}


def upload_policy_state(sid, current=None):
    """这个空间的直传许可还剩多久。返回 {wanted, expiresAt, remainingS}。

    wanted=False 表示"它本来就不该带许可"(收集关了 / 没节点 / 名额满了)。这种情况下
    快照里的 expiresAt 是 time.time() 占位值, 永远显示"已过期" —— 不能拿它当续签信号,
    否则工人会对着一个关掉收集的空间每轮重发一次。
    """
    if current is None:
        with space.space_txn(sid, write=False) as snap:
            current = snap
    wanted = (
        space._normal_collection(current.get("collection"))["status"] == "open"
        and bool(current.get("nodes"))
        and not space.space_capacity(current)["full"]
    )
    try:
        expires_at = float(current.get("uploadExpiresAt") or 0)
    except (TypeError, ValueError):
        expires_at = 0.0
    return {"wanted": wanted, "expiresAt": expires_at,
            "remainingS": expires_at - time.time()}


def renew_upload_policy_if_needed(sid, conf=None):
    """剩余有效期不足 24 小时就重新发布一次, 把直传许可续上。

    返回发布报告 = 真续签了; 返回 None = 这轮不用管, 或者续签没成(会记冷却)。
    """
    try:
        with space.space_txn(sid, write=False) as current:
            if not space._cloud_publish_authorized(current):
                return None
            state = upload_policy_state(sid, current)
    except FileNotFoundError:
        return None
    if not state["wanted"] or state["remainingS"] > POLICY_RENEW_BEFORE_S:
        return None
    if time.time() < _policy_retry_after.get(sid, 0):
        return None

    left = state["remainingS"]
    if state["expiresAt"] <= 0:
        why = "本地还没记过到期时间(老数据), 先续一次把台账建起来"
    elif left <= 0:
        why = f"已经过期 {-left / 3600:.1f} 小时"
    else:
        why = f"只剩 {left / 3600:.1f} 小时"
    log(f"🔑 直传许可{why}, 自动续签中…")
    conf = conf or oss.load_conf()
    if republish(sid, conf) is None:
        _policy_retry_after[sid] = time.time() + POLICY_RETRY_COOLDOWN_S
        log(f"⚠️ 续签没成, {POLICY_RETRY_COOLDOWN_S // 60} 分钟后再试"
            f"(旧许可没过期的话宾客还能继续传)")
        return None
    _policy_retry_after.pop(sid, None)
    fresh = upload_policy_state(sid)
    log(f"✅ 直传许可已续到 {time.strftime('%m-%d %H:%M:%S', time.localtime(fresh['expiresAt']))}"
        f"(还剩 {fresh['remainingS'] / 3600:.1f} 小时)")
    return True


# ================================================================ 主循环
def poll_once(sid, conf=None, log_empty=True, do_publish=True):
    """收一轮。返回 {ok, listed, new, processed, failed, results, published}。

    space.json 里的 photo.inboxKey 是入库幂等真值,台账只是快速索引。即使进程在
    照片提交后、台账落盘前退出,下一轮也会认出同一个 key,不会重复加分。
    """
    conf = conf or oss.load_conf()
    st = load_state(sid)
    done = st["keys"]

    try:
        current_space = space.load_space(sid)
    except FileNotFoundError as e:
        log(f"⚠️ {e} —— 先在后台建好空间再开工人")
        return {"ok": False, "error": str(e), "listed": 0, "new": 0,
                "processed": 0, "failed": 0, "results": [], "published": None}

    retired = sweep_retired_inboxes(sid, conf, current_space)
    if retired["warnings"] and log_empty:
        log(f"⚠️ 旧收件箱还有 {len(retired['warnings'])} 项待清理")

    try:
        listed = oss.list_keys(conf, inbox_prefix(sid, current_space))
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
        published = None
        if do_publish:
            try:
                with space.space_txn(sid, write=False) as current:
                    can_sync = (
                        bool(current.get("publishDirty"))
                        and space._cloud_publish_authorized(current)
                    )
                if can_sync:
                    published = republish(sid, conf)
            except FileNotFoundError:
                pass
        return {"ok": True, "listed": len(listed), "new": 0,
                "processed": 0, "failed": 0, "results": [], "published": published}

    # 满额对象必须得到终态回执并进入去重台账，但绝不能下载或跑 CLIP。
    # 最后一个名额会在同一事务里自动关闭 collection，因此这个判断必须早于
    # “collection closed 就暂停”，否则超额对象会永远留在重试队列。
    capacity = space.space_capacity(current_space)
    if capacity["full"]:
        quota_rejected = 0
        for item in fresh:
            key = item["key"]
            contributor, task_id = parse_key(key)
            space.record_quota_full_receipt(sid, key, contributor)
            done[key] = {
                "state": "quota_full",
                "contributor": contributor,
                "taskId": task_id,
                "at": time.time(),
            }
            quota_rejected += 1
        save_state(sid, st)
        published = None
        if do_publish:
            with space.space_txn(sid, write=False) as current:
                can_sync = space._cloud_publish_authorized(current)
            if can_sync:
                published = republish(sid, conf)
        log(
            f"本场已收满 {capacity['maxPhotos']} 张,"
            f"已拒绝 {quota_rejected} 张超额投稿且未运行 CLIP"
        )
        return {
            "ok": True,
            "listed": len(listed),
            "new": len(fresh),
            "processed": 0,
            "failed": 0,
            "quotaFull": quota_rejected,
            "results": [],
            "published": published,
        }

    # 主办方暂停收集时, 新对象留在收件箱里等恢复, 既不处理也不记失败。
    # 公开直传策略在过期前仍可能被旧页面持有, 所以工人也必须守这道闸。
    collection = space._normal_collection(current_space.get("collection"))
    if collection["status"] != "open":
        if log_empty:
            log(f"收集已暂停, 云端还有 {len(fresh)} 张照片等待恢复后处理")
        return {"ok": True, "listed": len(listed), "new": len(fresh),
                "processed": 0, "failed": 0, "paused": True,
                "results": [], "published": None}

    # 已知任务 id, 用来挡掉宾客页传来的野 taskId(带个不存在的任务会让积分/任务状态错乱)
    known_tasks = {t["id"] for t in current_space.get("tasks", [])}

    results, failed, deferred, quota_rejected = [], 0, 0, 0
    for item in fresh:
        key = item["key"]
        contributor, task_id = parse_key(key)
        if task_id and task_id not in known_tasks:
            task_id = None                      # 野 taskId 直接丢掉, 让自动判定去接
        try:
            with space.space_txn(sid, write=False) as latest:
                latest_capacity = space.space_capacity(latest)
            if latest_capacity["full"]:
                space.record_quota_full_receipt(sid, key, contributor)
                done[key] = {
                    "state": "quota_full",
                    "contributor": contributor,
                    "taskId": task_id,
                    "at": time.time(),
                }
                quota_rejected += 1
                log(f"名额已满,拒绝 {os.path.basename(key)}（未下载、未跑 CLIP）")
                save_state(sid, st)
                continue
            try:
                raw = oss.get_bytes(conf, key)
            except Exception as e:
                # 列表成功不代表随后的 GET 不会遇到瞬时超时或 OSS 5xx。原件仍在,
                # 这类错误绝不能写进永久 failed 台账。
                deferred += 1
                log(f"⏸️ {os.path.basename(key)} 下载暂时失败,下一轮重试: {type(e).__name__}")
                continue
            out = space.upload_photos(
                sid, [(os.path.basename(key), oss.guess_type(key), raw)],
                contributor, task_id=task_id, inbox_key=key,
            )
            r = out[0]
            # inboxKey 已和 photo 在同一笔 space_txn 里提交。这里不再补第二笔,
            # 避免两笔之间断电造成重复入库或删除时漏掉云端原件。
            margin = r.get("margin", 0.0)

            done[key] = {"photoId": r["photoId"], "state": r["state"],
                         "contributor": contributor, "taskId": r.get("taskFilled") or task_id,
                         "confidence": r["confidence"], "margin": margin, "at": time.time()}
            results.append({"key": key, "photoId": r["photoId"], "state": r["state"],
                            "nodeId": r["nodeId"], "yaw": r["yaw"], "direction": r["direction"],
                            "confidence": r["confidence"], "margin": margin,
                            "contributor": contributor, "taskFilled": r.get("taskFilled")})
        except space.PhotoQuotaFull as e:
            space.record_quota_full_receipt(sid, key, contributor)
            done[key] = {
                "state": "quota_full",
                "contributor": contributor,
                "taskId": task_id,
                "at": time.time(),
            }
            quota_rejected += 1
            log(f"名额已满,拒绝 {os.path.basename(key)}（未入库）")
        except RuntimeError as e:
            # 主办方可能正好删了最后一个场景或在 CLIP 计算期间删了命中的场景。
            # 这不是坏图,OSS 原件还在。不要写进 done 台账,留到重新建场景并开放
            # 收集后再处理,否则一次场景调整会把宾客照片永久吞掉。
            msg = str(e)
            if ("还没有全景节点" in msg or "全景场景刚刚被移除" in msg
                    or "已经暂停收集照片" in msg or "正在处理中" in msg):
                deferred += 1
                log(f"⏸️ {os.path.basename(key)} 等待新场景,下一轮重试")
                continue
            if "已经随原场景移除" in msg:
                done[key] = {"removed": True, "contributor": contributor, "at": time.time()}
                log(f"已跳过随旧场景移除的投稿 {os.path.basename(key)}")
                save_state(sid, st)
                continue
            failed += 1
            done[key] = {"failed": True, "error": msg[:300],
                         "contributor": contributor, "at": time.time()}
            log(f"⚠️ {os.path.basename(key)} 处理失败,记账跳过: {e}")
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
        tail = (f", {failed} 张失败" if failed else "") + (
            f", {deferred} 张等待重试" if deferred else "") + (
            f", {quota_rejected} 张因满额拒绝" if quota_rejected else "")
        log(f"收到 {len(fresh)} 张{tail} → " + " / ".join(bits))
    elif deferred:
        log(f"收到 {len(fresh)} 张,其中 {deferred} 张等待新场景后重试")
    elif quota_rejected:
        log(f"收到 {len(fresh)} 张,其中 {quota_rejected} 张因名额已满未入库")
    else:
        log(f"收到 {len(fresh)} 张, 全部处理失败")

    published = None
    if do_publish and (results or quota_rejected):
        with space.space_txn(sid, write=False) as current:
            auto_publish = space._cloud_publish_authorized(current)
        if auto_publish:
            published = republish(sid, conf)
        else:
            log("照片已归位,展览仍是主办方草稿,等主办方发布后再同步公网")
    return {"ok": True, "listed": len(listed), "new": len(fresh), "processed": len(results),
            "failed": failed, "deferred": deferred,
            "quotaFull": quota_rejected,
            "results": results, "published": published}


# ================================================================ 全景收件箱(批次E)
def poll_panos_once(sid, conf=None, log_empty=True, do_publish=True):
    """收一轮主办方自传的全景。独立通道(spaces/<sid>/pano-inbox/), 和宾客照片的
    收件箱互不干扰、互不去重。每张新全景调 space.add_node() 建一个真节点
    (标准化 + DAP 深度 + 缺口任务, 逻辑和 Studio 手传全景完全一样, 只是触发源
    从"HTTP 上传请求"换成了"云端收件箱里出现一个新对象")。

    自助建空间没有一个单独的"发布"按钮给主办方点, 所以这里的产品语义是:
    传第一张全景进去的那一刻,就该是宾客能扫码看到的那一刻。这一点和宾客
    上传照片故意不同——那边不自动发布未发布的草稿(见 poll_once), 因为
    上传照片的是宾客, 万一主办方还没准备好, 不该替他们把草稿捅出去。
    但全景是主办方自己传的, 这就是他们自己在明确地"添加内容", 没有"抢跑"
    这一说, 所以每收到至少一张就顺手把空间从草稿推成已发布(publish_space
    对已发布的空间是幂等的, 不会因为重复调用出问题)。
    """
    conf = conf or oss.load_conf()
    st = load_pano_state(sid)
    done = st["keys"]

    try:
        space.load_space(sid)
    except FileNotFoundError as e:
        log(f"⚠️ {e} —— 先建好空间再开工人")
        return {"ok": False, "error": str(e), "listed": 0, "new": 0,
                "processed": 0, "failed": 0, "results": [], "published": None}

    try:
        listed = oss.list_keys(conf, space.pano_inbox_prefix(sid))
    except Exception as e:
        log(f"⚠️ 列云端全景收件箱失败(下一轮再试): {e}")
        return {"ok": False, "error": str(e), "listed": 0, "new": 0,
                "processed": 0, "failed": 0, "results": [], "published": None}

    fresh = [it for it in listed
             if it["key"] not in done and it["size"] > 0 and is_image_key(it["key"])]
    fresh.sort(key=lambda it: it["key"])   # key 以时间戳打头, 排序 ≈ 按上传先后

    if not fresh:
        if log_empty:
            log(f"没有新全景(云端全景收件箱 {len(listed)} 个对象, 台账已记 {len(done)} 个)")
        return {"ok": True, "listed": len(listed), "new": 0,
                "processed": 0, "failed": 0, "results": [], "published": None}

    results, failed = [], 0
    for item in fresh:
        key = item["key"]
        base = os.path.basename(key)
        try:
            raw = oss.get_bytes(conf, key)
        except Exception as e:
            # 列表成功不代表 GET 一定成功(瞬时超时/OSS 5xx), 这类错误不能写进
            # 永久台账 —— 原件还在, 留到下一轮重试。
            log(f"⏸️ {base} 下载暂时失败,下一轮重试: {type(e).__name__}")
            continue
        try:
            nid, tasks, timings = space.add_node(
                sid, raw, base, oss.guess_type(key), "", "",
            )
            done[key] = {"nodeId": nid, "at": time.time()}
            results.append({"key": key, "nodeId": nid, "tasks": len(tasks), "timings": timings})
            log(f"新全景 {base} → 建成节点 {nid}(切图 {timings.get('pano_s')}s, "
                f"深度 {timings.get('depth_s')}s, 缺口任务 {len(tasks)} 个)")
        except Exception as e:
            # 坏图/画幅不对/等等: 记一笔失败就翻篇, 别让一张烂图卡住整条队列
            # (道理和 poll_once 处理坏照片一样)。
            failed += 1
            done[key] = {"failed": True, "error": str(e)[:300], "at": time.time()}
            log(f"⚠️ {base} 建节点失败,记账跳过: {e}")
        save_pano_state(sid, st)   # 每张都落盘: 中途 Ctrl-C/断电也不会重算已经算完的

    published = None
    if do_publish and results:
        try:
            space.publish_space(sid)
        except Exception as e:
            log(f"⚠️ 本地发布状态没能更新(全景已建成节点,下一轮重试发布): {e}")
        published = republish(sid, conf)

    return {"ok": True, "listed": len(listed), "new": len(fresh),
            "processed": len(results), "failed": failed,
            "results": results, "published": published}


def run_forever(sid, interval=5, conf=None):
    """常驻循环。Ctrl-C 干净退出(台账每张都已经落盘, 不会丢进度)。"""
    conf = conf or oss.load_conf()
    # 云配置的任何值都不进日志。后台只需要知道空间和轮询间隔。
    log(f"工人上岗: 空间 {sid}, 每 {interval}s 查看云端收件箱")
    beat(sid, "loading-clip")   # 先跳一下: 加载 CLIP 那十几秒, 后台也该显示"工人在了"
    space.get_clip_model()      # 先把 CLIP 加载完, 别让第一个宾客等这 10-20 秒
    log("CLIP 就绪, 开始盯收件箱(Ctrl-C 收工)")

    idle = 0
    quiet_rounds = max(1, int(60 / max(interval, 1)))    # 大约每分钟报一次平安
    try:
        while True:
            beat(sid, "polling")     # 每轮一次心跳, 新人后台靠它显示"工人运行中"
            # 收照片之前先看一眼直传许可还剩多久。放在最前面是有意的: 许可过期时
            # 宾客根本传不进来, 收件箱空空如也看起来跟"没人传"一模一样。
            renew_upload_policy_if_needed(sid, conf)
            res = poll_once(sid, conf, log_empty=False)
            # 全景收件箱(主办方自传)和照片收件箱(宾客直传)同一轮里都看一眼。
            # 两条通道各自独立、互不去重, 这里只是共用同一个循环节奏。
            pano_res = poll_panos_once(sid, conf, log_empty=False)
            if res.get("processed") or pano_res.get("processed"):
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
    keys = []
    seen = set()
    for prefix in (f"spaces/{sid}/inbox/", f"spaces/{sid}/inbox-v2/", f"spaces/{sid}/pano-inbox/"):
        for item in oss.list_keys(conf, prefix):
            key = str(item.get("key") or "")
            if key and key not in seen:
                seen.add(key)
                keys.append(item)
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
        if not args.no_publish:
            renew_upload_policy_if_needed(args.sid, conf)
        res = poll_once(args.sid, conf, do_publish=not args.no_publish)
        pano_res = poll_panos_once(args.sid, conf, do_publish=not args.no_publish)
        return 0 if (res.get("ok") and pano_res.get("ok")) else 1

    run_forever(args.sid, args.interval, conf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
