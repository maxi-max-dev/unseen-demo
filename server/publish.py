#!/usr/bin/env python3
"""
server/publish.py -- 把一个空间发布到阿里云 OSS(宾客真正看到的那一份)。

为什么要有这一层: 现场宾客的手机连不到 Max 的电脑(热点/内网/公网穿透都不现实),
所以【所有宾客要看的东西都必须先躺在 OSS 上】。Mac 从此只是一台后台计算机:
它算完 -> 推一份公开快照到 OSS -> 宾客的页面只跟 OSS 说话, Mac 断网都不影响观看。

发布器做三件事:
    ① 把 spaces/<sid>/ 里宾客需要的文件推到 OSS(每个都带 x-oss-object-acl: public-read)
    ② 生成一份【公开版 space.json】—— 只含已入选的照片, 路径换成 OSS 完整 URL
    ③ 在公开版里塞一份 PostObject 直传策略, 宾客的照片直接进 OSS 的 inbox/, 不经过任何服务器

OSS 目录约定(定死, 全组按这个来):
    spaces/<sid>/space.json               公开版空间数据
    spaces/<sid>/nodes/<nid>/pano.jpg | depth.png | depth.json
    spaces/<sid>/photos/<pid>.jpg
    spaces/<sid>/thumbs/<pid>.jpg
    spaces/<sid>/tasks/<tid>.jpg          悬赏任务的"通缉令"裁切图
    spaces/<sid>/inbox/                   宾客直传落这里(发布器不碰, 收件工人来收)
本地相对路径和 OSS 的 key 是 1:1 的(只是前面多一段 spaces/<sid>/), 所以这里不用做任何路径翻译。

隐私红线: 待审(needs_review)/被拒(rejected)/隔离(quarantined)的照片一张都不许出现在
公开版里 —— 新人没点头的照片不能被任何人看到, 连文件都不上传。

零新依赖: 只用标准库 + server/oss.py。密钥只从 ~/.config/psm/aliyun.json 读,
公开版里只会出现 post_policy 生成的 policy/signature(有前缀+有效期限制), 绝不含 accessKeySecret。

单独跑法:
    .venv/bin/python -m server.publish <sid>
    .venv/bin/python -m server.publish <sid> --force      # 忽略增量, 全部重传
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import oss                                          # noqa: E402
from server.space import SELECTED_STATES, space_dir, space_txn   # noqa: E402

# OSS 上的根前缀。所有空间都挂在这下面, 别的项目要用同一个 bucket 也不会撞。
ROOT_PREFIX = "spaces"

# 宾客直传通道的有效期。48 小时够覆盖"婚礼前一天布场 + 当天 + 第二天补传",
# 过期后前端会提示"上传通道已关闭,请联系新人", 新人重新发布一次就续上了。
UPLOAD_EXPIRE_S = 48 * 3600

# 每个文件上传时都要带的头: 让【这一个文件】可以公开读。
# Bucket 本身是私有的 —— 别人列不了目录、猜不到 key, 只有我们主动发布的东西能被看到。
PUBLIC_READ = {"x-oss-object-acl": "public-read"}

# 超时按文件大小算, 别用一个死数。实测这台机器传杭州只有 ~27KB/s(跨境上行),
# 一张 2MB 的全景要 80 秒, 用 oss.py 默认的 60 秒必然报 "write operation timed out"。
# 按 8KB/s 这个很悲观的下限估算, 现场婚宴 Wi-Fi 再烂也兜得住。
SLOW_UPLINK_BPS = 8 * 1024
MIN_TIMEOUT_S = 60


def upload_timeout(size):
    return max(MIN_TIMEOUT_S, int(size / SLOW_UPLINK_BPS) + 30)


def oss_key(sid, rel):
    """本地相对路径 -> OSS key。"""
    return f"{ROOT_PREFIX}/{sid}/{str(rel).lstrip('/')}"


def public_url(conf, sid, rel):
    """本地相对路径 -> 宾客能直接用的完整 URL。rel 为空返回 None(比如深度图没跑出来)。"""
    return oss.public_url(conf, oss_key(sid, rel)) if rel else None


def inbox_prefix(sid):
    return f"{ROOT_PREFIX}/{sid}/inbox/"


def build_public_space(conf, sid, space, upload_expire_s=UPLOAD_EXPIRE_S):
    """把本地 space.json 翻译成【公开版】。

    返回 (public_space, rels, warnings):
        public_space  要写到 OSS 上的那份 json
        rels          需要跟着上传的本地相对路径列表(已去重、已确认文件真的在)
        warnings      人话提醒(比如某张入选照片的文件不见了), 不致命, 但要说出来

    和本地版的差别:
      · 只保留已入选(auto_ok / approved)的照片, 其余连文件都不上传
      · 每个资源路径换成 OSS 完整 URL
      · 多一段 upload(直传策略)和 expiresAt、publishedAt
      · 不带 reason/margin 这些内部评分细节 —— 宾客不需要看机器怎么评价自己的照片
    """
    rels = []
    warnings = []
    root = space_dir(sid)

    def take(rel):
        """登记一个要上传的文件; 文件不在就返回 None 并记一条提醒。"""
        if not rel:
            return None
        if not os.path.exists(os.path.join(root, rel)):
            warnings.append(f"文件不在, 跳过: {rel}")
            return None
        if rel not in rels:
            rels.append(rel)
        return public_url(conf, sid, rel)

    nodes = []
    for n in space.get("nodes") or []:
        pano = take(n.get("panorama"))
        if not pano:
            # 没有全景就没有空间, 这个节点发上去也是白发, 直接不要。
            warnings.append(f"节点 {n.get('id')} 没有全景图, 已从公开版剔除")
            continue
        nodes.append({
            "id": n.get("id"),
            "name": n.get("name"),
            "time": n.get("time"),
            "panorama": pano,
            "depth": take(n.get("depth")),
            "depthJson": take(n.get("depthJson")),
        })
    node_ids = {n["id"] for n in nodes}

    photos = []
    for p in space.get("photos") or []:
        if p.get("state") not in SELECTED_STATES:
            continue                      # ← 隐私红线就在这一行
        src = take(p.get("src"))
        if not src:
            continue
        photos.append({
            "id": p.get("id"),
            "src": src,
            "thumb": take(p.get("thumb")) or src,
            "nodeId": p.get("nodeId"),
            "yaw": p.get("yaw"),
            "pitch": p.get("pitch", 0),
            "confidence": p.get("confidence"),
            "contributor": p.get("contributor"),
            "taskId": p.get("taskId"),
            "uploadedAt": p.get("uploadedAt"),
            # 宾客页靠这段 key 里的短 id 认领"我传的那张"(见 web/join.html findMine)
            "inboxKey": p.get("inboxKey"),
        })

    # 待确认回执: 只发【状态和署名】, 不发照片文件、不发方位、不发机器评分。
    #
    # ⚠️ 7/24 现场踩到的真实事故: 一位宾客传了照片, 机器判成 needs_review, 于是它按上面
    #   那条隐私红线不进公开版 —— 宾客的页面轮询公开数据永远等不到自己那张, 就一直转圈,
    #   人以为"卡住了"。照片不公开是对的, 但【连"我收到了"都不告诉他】是错的。
    #   所以这里补一条不含任何画面内容的回执: 宾客能看到"已收到, 等新人确认",
    #   别人看到的也只是一个昵称和一个时间戳, 照片本身仍然一个字节都没上公网。
    pending = []
    for p in space.get("photos") or []:
        st = p.get("state")
        if st in SELECTED_STATES:
            continue
        if st not in ("needs_review", "rejected", "quarantined"):
            continue
        pending.append({
            "id": p.get("id"),
            "state": st,
            "contributor": p.get("contributor"),
            "uploadedAt": p.get("uploadedAt"),
            "taskId": p.get("taskId"),
            "inboxKey": p.get("inboxKey"),
            # 给宾客看的人话, 不暴露机器的具体评分
            "note": {"needs_review": "已收到,等新人确认",
                     "rejected": "新人看过了,这张没收进空间",
                     "quarantined": "机器判定它不在这个空间,已自动隔离"}.get(st, "已收到"),
        })

    tasks = []
    for t in space.get("tasks") or []:
        if t.get("nodeId") and node_ids and t.get("nodeId") not in node_ids:
            continue                      # 节点都没发布, 它的悬赏任务发了也点不进去
        tasks.append({
            "id": t.get("id"),
            "nodeId": t.get("nodeId"),
            "type": t.get("type"),
            "title": t.get("title"),
            "brief": t.get("brief"),
            "yaw": t.get("yaw"),
            "yawRange": t.get("yawRange"),
            "briefImage": take(t.get("briefImage")),
            "bounty": t.get("bounty"),
            "status": t.get("status"),
            "filledBy": t.get("filledBy") or [],
        })

    upload = oss.post_policy(conf, inbox_prefix(sid), expire_s=upload_expire_s)

    public = {
        "schema": space.get("schema"),
        "id": sid,
        "title": space.get("title"),
        "couple": space.get("couple"),
        "createdAt": space.get("createdAt"),
        "publishedAt": time.time(),
        "nodes": nodes,
        "tasks": tasks,
        "photos": photos,
        # 待确认回执(不含照片文件, 见上面 pending 那段注释)
        "pending": pending,
        "contributors": space.get("contributors") or [],
        # 宾客页拿这份策略把照片直接 POST 进 OSS。表单字段:
        # key / OSSAccessKeyId / policy / Signature / x-oss-object-acl / file
        "upload": upload,
        # 顶层再放一份过期时间, 前端过期时提示"上传通道已关闭,请联系新人"
        "expiresAt": upload["expiresAt"],
    }
    return public, rels, warnings


def publish_space(sid, conf=None, progress=None, force=False):
    """把空间 sid 发布到 OSS。返回一份发布报告。

    progress 是可选回调 progress(done, total, key), 给前端画进度条用。

    增量发布: 全景一张 2MB, 现场网可能很差, 所以先 head 看一眼 OSS 上在不在、大小一不一样,
    一样就跳过。这里只比大小不比 MD5 —— 这套数据里文件是"一次写定"的(照片按 id 存,
    全景按节点存, 不会原地改内容), 比大小足够, 还省掉把每个 2MB 文件读出来做哈希。
    真要重传(比如手动换过素材)加 force=True。
    """
    t0 = time.time()
    conf = conf or oss.load_conf()

    with space_txn(sid, write=False) as space:
        public, rels, warnings = build_public_space(conf, sid, space)

    root = space_dir(sid)
    total = len(rels) + 1          # +1 是最后那份 space.json
    uploaded = skipped = sent_bytes = 0
    done = 0
    done_lock = threading.Lock()

    # 本地发布账本: {key: size}。
    # ⚠️ 为什么要它: 原来每个文件都打一次 head 问"你在不在"。实测这台机器到杭州单次往返
    #   1324ms, 22 个没变的文件光问一遍就是 29 秒, 宾客传完照片要干等一分钟才看见。
    #   账本记下"这个 key 我传过、多大", 下次直接跳过, 零往返。
    #   账本里没有的才退回去打 head(比如换了台机器发布、或者账本丢了), 所以不会因为
    #   账本不准就漏传 —— 只有"账本说传过"才敢跳。
    ledger_path = os.path.join(root, ".published.json")
    ledger = {}
    if not force and os.path.exists(ledger_path):
        try:
            with open(ledger_path, encoding="utf-8") as f:
                ledger = json.load(f)
        except Exception:
            ledger = {}

    def bump(key):
        nonlocal done
        with done_lock:
            done += 1
            cur = done
        if progress:
            progress(cur, total, key)

    def handle(rel):
        """返回 ('skip'|'up', key, size)。可并发调用。"""
        path = os.path.join(root, rel)
        key = oss_key(sid, rel)
        size = os.path.getsize(path)

        if not force:
            if ledger.get(key) == size:          # 账本命中: 零往返
                bump(key)
                return ("skip", key, size)
            h = oss.head(conf, key)              # 账本没有才问一次
            if h is not None and int(h.get("Content-Length") or -1) == size:
                bump(key)
                return ("skip", key, size)

        oss.put_file(conf, key, path, oss_headers=PUBLIC_READ, timeout=upload_timeout(size))
        bump(key)
        return ("up", key, size)

    # 并发上传: 慢的是往返延迟不是带宽, 并行几条能把墙上时间摊掉一大半。
    # 6 条是保守值 —— 现场网可能很差, 开太多反而互相抢。
    results = []
    if rels:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [pool.submit(handle, rel) for rel in rels]
            for fut in as_completed(futs):
                results.append(fut.result())

    for kind, key, size in results:
        if kind == "skip":
            skipped += 1
        else:
            uploaded += 1
            sent_bytes += size
        ledger[key] = size

    # space.json 永远最后传、永远重传:
    #   最后传 —— 宾客拿到的清单里绝不会指向还没上传完的文件;
    #   重传   —— 里面有新的直传策略和 publishedAt, 内容每次都变。
    body = json.dumps(public, ensure_ascii=False, indent=2).encode("utf-8")
    key = oss_key(sid, "space.json")
    space_json_url = oss.put_bytes(conf, key, body, "application/json", oss_headers=PUBLIC_READ)
    uploaded += 1
    sent_bytes += len(body)
    done += 1
    if progress:
        progress(done, total, key)

    # 本地也记一笔"已发布", 新人后台好显示状态。真值仍然在本地 space.json 里。
    with space_txn(sid) as space:
        space["published"] = True
        space["publishedAt"] = public["publishedAt"]
        space["ossSpaceJson"] = space_json_url

    # 落账本(不含 space.json —— 它每次内容都变, 必须每次重传)。
    # 写坏了也只是下次多打几次 head, 不影响正确性, 所以失败不抛。
    try:
        tmp = ledger_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ledger, f)
        os.replace(tmp, ledger_path)
    except Exception as e:
        print(f"   (账本没写成, 不影响发布: {e})", flush=True)

    return {
        "ok": True,
        "sid": sid,
        "spaceJson": space_json_url,
        "uploaded": uploaded,
        "skipped": skipped,
        "bytes": sent_bytes,
        "elapsedS": round(time.time() - t0, 2),
        "nodes": len(public["nodes"]),
        "photos": len(public["photos"]),
        "tasks": len(public["tasks"]),
        "inboxPrefix": inbox_prefix(sid),
        "expiresAt": public["expiresAt"],
        "warnings": warnings,
        "public": public,
    }


def _human_bytes(n):
    return f"{n / 1024 / 1024:.2f}MB" if n >= 1024 * 1024 else f"{n / 1024:.1f}KB"


def main(argv):
    import argparse

    ap = argparse.ArgumentParser(description="把一个空间发布到阿里云 OSS")
    ap.add_argument("sid", help="空间 id, 比如 s4")
    ap.add_argument("--force", action="store_true", help="忽略增量, 所有文件全部重传")
    args = ap.parse_args(argv)

    def show(done, total, key):
        print(f"  [{done}/{total}] {key}", flush=True)

    try:
        r = publish_space(args.sid, progress=show, force=args.force)
    except Exception as e:
        print(f"❌ 发布失败: {e}")
        return 1

    for w in r["warnings"]:
        print(f"⚠️ {w}")
    print(f"\n✅ 空间 {r['sid']} 已发布: 上传 {r['uploaded']} 个 / 跳过 {r['skipped']} 个 / "
          f"{_human_bytes(r['bytes'])} / {r['elapsedS']}s")
    print(f"   内容: {r['nodes']} 个节点, {r['photos']} 张入选照片, {r['tasks']} 个任务")
    print(f"   公开清单: {r['spaceJson']}")
    print(f"   宾客直传前缀: {r['inboxPrefix']}(有效期至 "
          f"{time.strftime('%m-%d %H:%M', time.localtime(r['expiresAt']))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
