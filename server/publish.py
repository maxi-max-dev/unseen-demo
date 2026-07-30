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
import hashlib
import json
import os
import sys
import threading
import time
import fcntl
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import oss                                          # noqa: E402
from server.space import (                                         # noqa: E402
    SELECTED_STATES,
    _cloud_publish_authorized,
    _ensure_private_inbox_prefix,
    _has_valid_cloud_delete_outbox,
    _inbox_prefix as _space_inbox_prefix,
    _normal_collection,
    _normal_exhibition,
    _normal_limits,
    _normal_retired_inboxes,
    space_capacity,
    space_dir,
    space_txn,
)

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

_publish_locks = {}
_publish_locks_guard = threading.Lock()


def _publish_lock(sid):
    """同一空间的 worker 重发和 Studio 手动发布必须串行。

    两轮同时写同一个 OSS space.json 时,旧轮可能最后完成把公网退回旧快照；
    本地 .published.json 也会互相覆盖。按 sid 加锁,不同空间仍可并行。
    """
    with _publish_locks_guard:
        return _publish_locks.setdefault(sid, threading.Lock())


def upload_timeout(size):
    return max(MIN_TIMEOUT_S, int(size / SLOW_UPLINK_BPS) + 30)


def oss_key(sid, rel):
    """本地相对路径 -> OSS key。"""
    return f"{ROOT_PREFIX}/{sid}/{str(rel).lstrip('/')}"


def public_url(conf, sid, rel):
    """本地相对路径 -> 宾客能直接用的完整 URL。rel 为空返回 None(比如深度图没跑出来)。"""
    return oss.public_url(conf, oss_key(sid, rel)) if rel else None


def inbox_prefix(sid, space=None):
    return _space_inbox_prefix(sid, space or {})


# ---------------------------------------------------------------- 降档全景(给小程序看的)
# 微信小程序真机加载 >2000px 的图失败率接近 100%(开发工具里测不出来, 只有真机会挂),
# 而云端全景是 4096 宽。所以每个节点额外发一张 2048x1024 的降档图 —— 这不是可选优化,
# 是小程序能不能看到全景的前提。等距柱状投影必须保持 2:1, 所以宽高一起写死。
PANO_MINI_W, PANO_MINI_H = 2048, 1024
PANO_MINI_QUALITY = 86


def _pano_mini_rel(root, node):
    """这个节点的降档全景【应该叫什么】(只算名字, 不生成)。

    文件名里带的是【源全景内容的哈希】, 不是节点 id 或时间戳。理由: 路演背景可以在
    保留同一个 n1 的前提下换图, 名字不跟着内容变的话, 客户端本地缓存和 CDN 都会拿
    旧图冒充新图 —— 而全景恰恰是"换了就必须立刻生效"的东西(照片方位全挂在它上面)。
    """
    rel = str(node.get("panorama") or "").replace("\\", "/").lstrip("/")
    if not rel.startswith("nodes/") or ".." in rel.split("/"):
        return None
    src = os.path.join(root, rel.replace("/", os.sep))
    if not os.path.exists(src):
        return None
    h = hashlib.sha256()
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"{os.path.dirname(rel)}/pano-mini-{h.hexdigest()[:12]}.jpg"


def _ensure_pano_mini(root, node):
    """按需生成降档全景, 返回相对路径。生成不了就返回 None —— 绝不因此挡住发布,
    小程序那头有离线兜底, 大不了这一版看不到新背景, 但展览本身不该受影响。"""
    rel = _pano_mini_rel(root, node)
    if not rel:
        return None
    dst = os.path.join(root, rel.replace("/", os.sep))
    if os.path.exists(dst):
        return rel                      # 名字带内容哈希, 存在即等于内容对得上
    src_rel = str(node.get("panorama")).replace("\\", "/").lstrip("/")
    src = os.path.join(root, src_rel.replace("/", os.sep))
    try:
        from PIL import Image           # 延迟导入: 发布路径本身不该强依赖 Pillow
        with Image.open(src) as im:
            small = im.convert("RGB").resize((PANO_MINI_W, PANO_MINI_H), Image.LANCZOS)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".tmp"
        small.save(tmp, "JPEG", quality=PANO_MINI_QUALITY, optimize=True)
        os.replace(tmp, dst)            # 半张图绝不能留在那个名字上(名字=内容承诺)
    except Exception as e:
        print(f"   (降档全景没生成成功, 小程序会退回离线兜底: {type(e).__name__}: {e})", flush=True)
        return None
    return rel


def _public_resource_rels(space, root=None):
    """不碰网络，只列出当前真值仍可能公开引用的本地素材路径。

    root 给了才把降档全景算进来(要读源文件算哈希)。不给就退回老行为，
    调用方只是少认一个 key，不会误删——降档图和全景在同一个 nodes/ 前缀下，
    当前清单里有它时永远在 wanted_keys 里。
    """
    rels = set()

    def add(raw, prefix):
        rel = str(raw or "").replace("\\", "/").lstrip("/")
        if rel.startswith(prefix) and ".." not in rel.split("/"):
            rels.add(rel)

    node_ids = set()
    for node in space.get("nodes") or []:
        node_ids.add(node.get("id"))
        add(node.get("panorama"), "nodes/")
        add(node.get("depth"), "nodes/")
        add(node.get("depthJson"), "nodes/")
        if root:
            add(_pano_mini_rel(root, node), "nodes/")
    for photo in space.get("photos") or []:
        if photo.get("state") in SELECTED_STATES:
            add(photo.get("src"), "photos/")
            add(photo.get("thumb"), "thumbs/")
    task_visibility = _normal_exhibition(space.get("exhibition"))["taskVisibility"]
    if task_visibility != "hidden":
        for task in space.get("tasks") or []:
            if task.get("nodeId") and node_ids and task.get("nodeId") not in node_ids:
                continue
            if task_visibility == "completed" and not (
                task.get("status") == "filled" or bool(task.get("filledBy"))
            ):
                continue
            add(task.get("briefImage"), "tasks/")
    return rels


def _save_publish_ledger(path, ledger):
    """账本是性能缓存，原子写失败只会让下一轮多做 HEAD，不影响业务真值。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f)
    os.replace(tmp, path)


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
            # 展示型空间可以给每个节点编排首屏与章节文案。只透传这些明确的
            # 公开字段，导入来源、校验摘要等内部信息仍留在本机 space.json。
            "eyebrow": n.get("eyebrow"),
            "title": n.get("title"),
            "description": n.get("description"),
            "initialYaw": n.get("initialYaw"),
            "initialPitch": n.get("initialPitch"),
            "initialFov": n.get("initialFov"),
            "panorama": pano,
            # 小程序专用的 2048x1024 降档图。文件名带源全景的内容哈希, 换了背景图
            # 名字就变, 旧缓存不可能命中(见 _pano_mini_rel)。生成失败时是 None,
            # 小程序那头会退回离线兜底, 不会白屏。
            "panoMini": take(_ensure_pano_mini(root, n)),
            "depth": take(n.get("depth")),
            "depthJson": take(n.get("depthJson")),
        })
    node_ids = {n["id"] for n in nodes}
    collection = _normal_collection(space.get("collection"))
    exhibition = _normal_exhibition(space.get("exhibition"))
    limits = _normal_limits(space.get("limits"))
    capacity = space_capacity(space)
    contributor_visibility = exhibition["contributorVisibility"]
    task_visibility = exhibition["taskVisibility"]

    def public_contributor(name):
        """展览的署名开关必须作用到公开数据本身,不能只靠页面藏文字。"""
        if contributor_visibility == "name":
            return name
        if contributor_visibility == "anonymous":
            return "匿名参与者"
        return None

    def public_receipt_ref(key):
        """公开回执只保留时间戳和随机短 id,去掉 key 里编码过的昵称与任务。"""
        if not key:
            return None
        stem = os.path.splitext(os.path.basename(str(key)))[0]
        return stem.split("__", 1)[0][:96] or None

    photos = []
    for p in space.get("photos") or []:
        if p.get("state") not in SELECTED_STATES:
            continue                      # ← 隐私红线就在这一行
        src = take(p.get("src"))
        if not src:
            continue
        photo = {
            "id": p.get("id"),
            "src": src,
            "thumb": take(p.get("thumb")) or src,
            "nodeId": p.get("nodeId"),
            "yaw": p.get("yaw"),
            "pitch": p.get("pitch", 0),
            "confidence": p.get("confidence"),
            "taskId": p.get("taskId"),
            # 参与端只有拿到后端发出的真实奖励标记，才能确认“完成了任务”。
            # 不能根据 taskId 自行推断，因为已完成任务仍允许继续投稿。
            "bountyPaid": bool(p.get("bountyPaid")),
            "taskNote": p.get("taskNote"),
            "uploadedAt": p.get("uploadedAt"),
            # 预置演示照片没有真实投稿人，但仍需要标题和时间标签把它放回
            # 对应章节；这些字段都是策展文案，不包含机器评分或私有上传信息。
            "title": p.get("title"),
            "caption": p.get("caption"),
            "timeLabel": p.get("timeLabel"),
            # 宾客页靠这段 key 里的短 id 认领"我传的那张"(见 web/join.html findMine)
            "inboxKey": public_receipt_ref(p.get("inboxKey")),
        }
        contributor = public_contributor(p.get("contributor"))
        if contributor:
            photo["contributor"] = contributor
        photos.append(photo)

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
            "uploadedAt": p.get("uploadedAt"),
            "taskId": p.get("taskId"),
            "inboxKey": public_receipt_ref(p.get("inboxKey")),
            # 给宾客看的人话, 不暴露机器的具体评分
            "note": {"needs_review": "已收到,等主办方确认",
                     "rejected": "主办方看过了,这张没收进空间",
                     "quarantined": "机器判定它不在这个空间,已自动隔离"}.get(st, "已收到"),
        })
    for receipt in space.get("_quotaReceipts") or []:
        if not isinstance(receipt, dict) or receipt.get("state") != "quota_full":
            continue
        pending.append({
            "id": None,
            "state": "quota_full",
            "uploadedAt": receipt.get("uploadedAt"),
            "taskId": None,
            "inboxKey": public_receipt_ref(receipt.get("inboxKey")),
            "note": (
                f"本场已收满 {capacity['maxPhotos']} 张,这张未进入空间"
                if capacity["maxPhotos"] is not None
                else "本场名额已满,这张未进入空间"
            ),
        })

    tasks = []
    for t in space.get("tasks") or []:
        if t.get("nodeId") and node_ids and t.get("nodeId") not in node_ids:
            continue                      # 节点都没发布, 它的悬赏任务发了也点不进去
        filled_by = t.get("filledBy") or []
        if task_visibility == "hidden":
            continue
        if task_visibility == "completed" and not (
            t.get("status") == "filled" or filled_by
        ):
            continue
        if contributor_visibility == "anonymous":
            filled_by = ["匿名参与者"] if filled_by else []
        elif contributor_visibility == "hidden":
            filled_by = []
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
            "filledBy": filled_by,
            # “还能继续投稿”和“悬赏还没发出”是两件事。心愿任务会长期保持
            # open 以继续收照片，但 filledBy 非空后不能再向参与者展示可领取奖励。
            # 单独公开布尔真值，也避免贡献者匿名/隐藏时前端从 filledBy 猜错。
            "bountyAvailable": (
                t.get("status", "open") != "closed"
                and not bool(t.get("filledBy"))
            ),
        })

    raw_contributors = space.get("contributors") or []
    if contributor_visibility == "name":
        contributors = raw_contributors
    elif contributor_visibility == "anonymous":
        contributors = [{
            "name": f"参与者 {i + 1:02d}",
            "photos": int(c.get("photos") or 0),
        } for i, c in enumerate(raw_contributors)]
    else:
        contributors = []

    if (
        collection["status"] == "open"
        and bool(nodes)
        and not capacity["full"]
    ):
        upload = oss.post_policy(conf, inbox_prefix(sid, space), expire_s=upload_expire_s)
        upload["enabled"] = True
    else:
        # 关闭收集的公开快照不再携带仍可使用的签名。已经在旧页面里拿到的签名会自然过期,
        # 工人端还有同一道 collection 闸门,因此旧页面传来的对象也不会被归入空间。
        upload = {"enabled": False, "expiresAt": time.time()}

    public = {
        "schema": space.get("schema"),
        "id": sid,
        "title": space.get("title"),
        "couple": space.get("couple"),
        "date": space.get("date") or "",
        "place": space.get("place") or "",
        "cover": space.get("cover") or "",
        "subtitle": space.get("subtitle") or "",
        "contentLabel": space.get("contentLabel") or "",
        "demoDisclosure": space.get("demoDisclosure") or "",
        "aiDisclosure": space.get("aiDisclosure") or "",
        "createdAt": space.get("createdAt"),
        "published": True,
        "publishedAt": time.time(),
        "collection": collection,
        "exhibition": exhibition,
        "limits": limits,
        "capacity": capacity,
        "nodes": nodes,
        "tasks": tasks,
        "photos": photos,
        # 待确认回执(不含照片文件, 见上面 pending 那段注释)
        "pending": pending,
        "contributors": contributors,
        # 宾客页拿这份策略把照片直接 POST 进 OSS。表单字段:
        # key / OSSAccessKeyId / policy / Signature / x-oss-object-acl(private) / file
        "upload": upload,
        # 顶层再放一份过期时间, 前端过期时提示"上传通道已关闭,请联系新人"
        "expiresAt": upload["expiresAt"],
    }
    return public, rels, warnings


def build_empty_public_space(sid, space):
    """生成删除最后一个节点后的公开撤展快照。

    不能直接沿用普通构建结果:老数据里可能还留着心愿任务、贡献者或待审回执。
    空展览必须不再引用任何画面和上传通道,然后发布器才会安全清掉旧对象。
    """
    now = time.time()
    collection = _normal_collection(space.get("collection"))
    collection["status"] = "closed"
    exhibition = _normal_exhibition(space.get("exhibition"))
    exhibition["status"] = "published"
    limits = _normal_limits(space.get("limits"))
    capacity = space_capacity(space)
    upload = {"enabled": False, "expiresAt": now}
    return {
        "schema": space.get("schema"),
        "id": sid,
        "title": space.get("title"),
        "couple": space.get("couple"),
        "date": space.get("date") or "",
        "place": space.get("place") or "",
        "cover": space.get("cover") or "",
        "subtitle": space.get("subtitle") or "",
        "contentLabel": space.get("contentLabel") or "",
        "demoDisclosure": space.get("demoDisclosure") or "",
        "aiDisclosure": space.get("aiDisclosure") or "",
        "createdAt": space.get("createdAt"),
        "published": True,
        "publishedAt": now,
        "collection": collection,
        "exhibition": exhibition,
        "limits": limits,
        "capacity": capacity,
        "nodes": [],
        "tasks": [],
        "photos": [],
        "pending": [],
        "contributors": [],
        "upload": upload,
        "expiresAt": now,
    }


def assert_not_private(sid, space):
    """私密空间绝不许发成公开可读。发布器的硬断言, 拦不住就是数据泄露。

    为什么要单独一道: 本机访客路由确实查了 private(space.py 的 is_publicly_published_space),
    但那只挡住"从这台机器的 API 看这个空间", 挡不住发布器。发布器把 space.json、全景和
    入选照片逐个对象设成 public-read(见文件顶部的 PUBLIC_READ), 一旦 private 空间走到这里,
    本机路由会装作它不存在, OSS 上的对象却是谁都能读的 —— 而空间 id 又是递增的 sN, 猜得到。

    位置很关键: 必须在【任何一次网络写入之前】。资源文件是先于 manifest 上传的,
    等到 manifest 那一步再拦, 照片早就以 public-read 躺在 OSS 上了。

    (P1-4, 2026-07-30。当前 s17/s19/s34 是 private=true 的空间, 三个都还没发布过,
     所以这道闸不会打断任何已经在跑的东西。)
    """
    if space.get("private"):
        raise RuntimeError(
            f"空间 {sid} 标了私密(private=true), 不能发布成公开可读的云端展览。"
            "私密空间的权限系统还没建(P2-2), 在那之前发布器一律拒绝, 免得把人家的照片"
            "以 public-read 摊在一个猜得到的地址上。"
        )


def _publish_space_locked(sid, conf=None, progress=None, force=False):
    """把空间 sid 发布到 OSS。返回一份发布报告。

    progress 是可选回调 progress(done, total, key), 给前端画进度条用。

    增量发布: 全景一张 2MB, 现场网可能很差, 所以先 head 看一眼 OSS 上在不在、大小一不一样,
    一样就跳过。这里只比大小不比 MD5 —— 这套数据里文件是"一次写定"的(照片按 id 存,
    全景按节点存, 不会原地改内容), 比大小足够, 还省掉把每个 2MB 文件读出来做哈希。
    真要重传(比如手动换过素材)加 force=True。
    """
    t0 = time.time()
    conf = conf or oss.load_conf()

    # 旧版策略允许 starts-with spaces/<sid>/inbox/，即使后来在它下面加 gN
    # 也挡不住旧标签页继续上传。发布前把所有老空间一次性迁到并列的 inbox-v2/，
    # 让旧签名从前缀层面就够不到当前收件箱。
    with space_txn(sid) as migration_space:
        _ensure_private_inbox_prefix(sid, migration_space)

    with space_txn(sid, write=False) as space:
        try:
            source_revision = int(space.get("publishRevision") or 0)
        except (TypeError, ValueError):
            source_revision = 0
        cloud_prefix = f"{ROOT_PREFIX}/{sid}/"
        snapshot_inbox_prefix = inbox_prefix(sid, space)
        retired_inbox_records = [
            item for item in _normal_retired_inboxes(sid, space)
            if item["prefix"] != snapshot_inbox_prefix
        ]
        retired_inbox_prefixes = [item["prefix"] for item in retired_inbox_records]
        retired_expiry = {
            item["prefix"]: item["expiresAt"] for item in retired_inbox_records
        }
        allowed_delete_prefixes = tuple(
            cloud_prefix + rel
            for rel in ("nodes/", "photos/", "thumbs/", "tasks/", "inbox/", "inbox-v2/")
        )
        published_delete_prefixes = tuple(
            cloud_prefix + rel for rel in ("nodes/", "photos/", "thumbs/", "tasks/")
        )
        pending_cloud_deletes = []
        for raw_key in (space.get("_pendingCloudDeletes") or []):
            key = str(raw_key)
            suffix = key[len(cloud_prefix):] if key.startswith(cloud_prefix) else ""
            if key.startswith(allowed_delete_prefixes) and ".." not in suffix.split("/"):
                pending_cloud_deletes.append(key)
        protected_inbox_keys = set()
        raw_published_keys = space.get("_publishedResourceKeys")
        published_keys_known = (
            isinstance(raw_published_keys, list)
            or (
                not bool(space.get("ossSpaceJson"))
                and not bool(space.get("published"))
                and not _has_valid_cloud_delete_outbox(sid, space)
            )
        )
        published_resource_keys = {
            str(value) for value in (raw_published_keys or [])
            if str(value).startswith(f"{ROOT_PREFIX}/{sid}/")
        }
        for photo in (space.get("photos") or []):
            key = str(photo.get("inboxKey") or "")
            suffix = key[len(cloud_prefix):] if key.startswith(cloud_prefix) else ""
            if (key.startswith((cloud_prefix + "inbox/", cloud_prefix + "inbox-v2/"))
                    and ".." not in suffix.split("/")):
                protected_inbox_keys.add(key)
        # 私密闸在授权闸【之前】: 两条都不过时, 私密这条的报错更准确, 也更该被看见。
        # 而且这里是整个发布流程第一次拿到真值、还没发出任何一个字节的地方。
        assert_not_private(sid, space)
        if not _cloud_publish_authorized(space):
            raise RuntimeError("这份展览还是主办方草稿,公开展览没有更新")
        allow_empty_snapshot = (
            not space.get("nodes")
            and (
                bool(space.get("ossSpaceJson"))
                or (
                    bool(space.get("published"))
                    and _has_valid_cloud_delete_outbox(sid, space)
                )
                or bool(space.get("roadshowMode"))
            )
            and _normal_collection(space.get("collection"))["status"] == "closed"
        )
        if not space.get("nodes"):
            if not allow_empty_snapshot:
                raise RuntimeError("还没有可发布的全景场景,公开展览没有更新")
            public = build_empty_public_space(sid, space)
            rels, warnings = [], []
        else:
            public, rels, warnings = build_public_space(conf, sid, space)
    if not public.get("nodes") and not allow_empty_snapshot:
        # 源真值有节点但公开版为空只可能是素材缺失,不能冒充撤展。
        raise RuntimeError("全景素材不完整,公开展览没有更新")
    if warnings:
        # 业务真值还引用着、但本地文件不见了时,绝不能用缩水版清单覆盖公网，
        # 更不能把云端可能仅存的一份当作 stale 删除。让本轮明确失败,修好本地
        # 素材后再发布。
        raise RuntimeError("本地素材不完整,公开展览没有更新:" + "；".join(warnings))

    root = space_dir(sid)
    total = len(rels) + 1          # +1 是最后那份 space.json
    uploaded = skipped = sent_bytes = 0
    done = 0
    done_lock = threading.Lock()
    wanted_keys = {oss_key(sid, rel) for rel in rels}

    # 本地发布账本: {key: size}。
    # ⚠️ 为什么要它: 原来每个文件都打一次 head 问"你在不在"。实测这台机器到杭州单次往返
    #   1324ms, 22 个没变的文件光问一遍就是 29 秒, 宾客传完照片要干等一分钟才看见。
    #   账本记下"这个 key 我传过、多大", 下次直接跳过, 零往返。
    #   账本里没有的才退回去打 head(比如换了台机器发布、或者账本丢了), 所以不会因为
    #   账本不准就漏传 —— 只有"账本说传过"才敢跳。
    ledger_path = os.path.join(root, ".published.json")
    ledger = {}
    if os.path.exists(ledger_path):
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

    # space.json 永远最后传、永远重传。真正 PUT 前再拿一次业务事务锁复核 revision：
    # 资源上传很慢，期间主办方可能删了场景或保存了新草稿。旧轮一旦过期，就只留下
    # 已上传但尚未引用的不可见资源，绝不能再用旧清单覆盖公网。
    body = json.dumps(public, ensure_ascii=False, indent=2).encode("utf-8")
    key = oss_key(sid, "space.json")
    manifest_skipped = False
    latest_space_json_url = ""
    with space_txn(sid) as current:
        try:
            manifest_revision = int(current.get("publishRevision") or 0)
        except (TypeError, ValueError):
            manifest_revision = 0
        # 资源已经传完、manifest 还没 PUT 的这个缝隙里, 空间有可能刚被改成私密。
        # 这里必须【硬失败】, 不能走下面 manifest_skipped 那条"安静跳过"的路:
        # 安静跳过会让人以为没事发生, 但刚上传的那批资源已经是 public-read 了,
        # 得让它响, 主办方才知道要去清。
        assert_not_private(sid, current)
        if manifest_revision != source_revision or not _cloud_publish_authorized(current):
            manifest_skipped = True
            latest_space_json_url = current.get("ossSpaceJson") or ""
        else:
            # 只在这一个很小的 manifest PUT 期间挡住业务写入，消除“复核后立刻被改”
            # 的窗口。全景和照片大文件早已在锁外并发上传，不会长时间卡住宾客。
            space_json_url = oss.put_bytes(
                conf, key, body, "application/json", oss_headers=PUBLIC_READ,
            )
            current["published"] = True
            current["ossSpaceJson"] = space_json_url
            # Studio 用它判断二维码里的直传策略是否仍在有效期，过期就必须重新发布。
            current["uploadExpiresAt"] = public["expiresAt"]
            # 这是“公网当前 manifest 正在引用什么”的本机镜像。下一次慢发布过期时，
            # 它用来区分可立刻清掉的新孤儿和仍被旧公网引用、必须等新 manifest 后再删的资源。
            current["_publishedResourceKeys"] = sorted(wanted_keys)
    if manifest_skipped:
        stale_warnings = list(warnings)
        stale_warnings.append("发布期间内容发生变化,旧公开快照已跳过")
        deleted_remote = 0
        cleanup_failed = False
        # 旧轮可能刚把后来被拒绝的照片以 public-read 上传。先在短事务里按最新
        # 真值把孤儿 key 持久入队，再释放全局业务锁做网络删除。断网时一个 DELETE
        # 可等 60 秒，绝不能把所有空间的上传和审核一起锁住。
        with space_txn(sid) as latest:
            latest_wanted_keys = {
                oss_key(sid, rel) for rel in _public_resource_rels(latest, space_dir(sid))
            }
            orphan_keys = sorted(wanted_keys - latest_wanted_keys)
            pending = set(latest.get("_pendingCloudDeletes") or [])
            pending.update(orphan_keys)
            if pending:
                latest["_pendingCloudDeletes"] = sorted(pending)
            else:
                latest.pop("_pendingCloudDeletes", None)
        # 保存草稿不能破坏仍在线的旧 manifest。只有能证明“上一个公开清单从未引用”
        # 的新对象才马上删；其余只入队，等主办方真正发布新清单后再清。
        immediately_safe = (
            set(orphan_keys) - published_resource_keys
            if published_keys_known else set()
        )
        deleted_or_missing = set()
        for orphan_key in sorted(immediately_safe):
            try:
                oss.delete(conf, orphan_key)
                deleted_remote += 1
                deleted_or_missing.add(orphan_key)
                ledger.pop(orphan_key, None)
            except Exception as e:
                if "HTTP 404" in str(e):
                    deleted_or_missing.add(orphan_key)
                    ledger.pop(orphan_key, None)
                    continue
                cleanup_failed = True
                stale_warnings.append(
                    f"旧轮公开素材待清理 {orphan_key}: {type(e).__name__}"
                )
        if deleted_or_missing:
            with space_txn(sid) as latest:
                active_now = {
                    oss_key(sid, rel) for rel in _public_resource_rels(latest, space_dir(sid))
                }
                # 若删除期间照片又被主办方重新批准，保留 pending。下一轮会先重传
                # 当前文件，再把这条保护性队列清掉。
                clearable = deleted_or_missing - active_now
                left = [
                    queued for queued in (latest.get("_pendingCloudDeletes") or [])
                    if queued not in clearable
                ]
                if left:
                    latest["_pendingCloudDeletes"] = left
                else:
                    latest.pop("_pendingCloudDeletes", None)
        try:
            _save_publish_ledger(ledger_path, ledger)
        except Exception as e:
            print(f"   (账本没写成,不影响发布: {e})", flush=True)
        return {
            "ok": True,
            "sid": sid,
            "spaceJson": latest_space_json_url,
            "uploaded": uploaded,
            "skipped": skipped,
            "bytes": sent_bytes,
            "elapsedS": round(time.time() - t0, 2),
            "nodes": len(public["nodes"]),
            "photos": len(public["photos"]),
            "tasks": len(public["tasks"]),
            "deletedRemote": deleted_remote,
            "inboxPrefix": snapshot_inbox_prefix,
            "expiresAt": public["expiresAt"],
            "warnings": stale_warnings,
            "stale": True,
            "manifestSkipped": True,
            "cleanupPending": cleanup_failed,
            "public": public,
        }

    uploaded += 1
    sent_bytes += len(body)
    done += 1
    if progress:
        progress(done, total, key)

    # 新清单已经生效后,再清掉这台机器账本里记录过、如今不再被引用的旧资源。
    # inbox 不进发布账本,不会被误删。即使某个 DELETE 失败,页面也已经不再引用它,
    # 下次发布仍会继续尝试。
    stale_keys = {
        key for key in ledger
        if key not in wanted_keys
        and str(key).startswith(published_delete_prefixes)
        and ".." not in str(key)[len(cloud_prefix):].split("/")
    }
    # 坏 legacy 数据可能把“待删记录”的路径串到仍被当前快照引用的同一个 key。
    # 当前引用永远优先,不能先发布新清单再把它指向的文件删掉。inbox 不进 rels,
    # 所以仍存于本地 photo 记录的原始投稿 key 也单独保护。
    protected_pending = set(pending_cloud_deletes) & (wanted_keys | protected_inbox_keys)
    pending_delete_set = set(pending_cloud_deletes) - protected_pending
    delete_keys = sorted(stale_keys | pending_delete_set)
    deleted_remote = 0
    cleanup_failed = False
    deleted_pending = []
    for stale_key in delete_keys:
        try:
            oss.delete(conf, stale_key)
            ledger.pop(stale_key, None)
            if stale_key in pending_delete_set:
                deleted_pending.append(stale_key)
            deleted_remote += 1
        except Exception as e:
            if "HTTP 404" in str(e):
                # 已经不存在等价于清理完成,但不能算作本次真的删了一个对象。
                ledger.pop(stale_key, None)
                if stale_key in pending_delete_set:
                    deleted_pending.append(stale_key)
                continue
            cleanup_failed = True
            warnings.append(
                f"待删除云端资源没清掉 {stale_key}: {type(e).__name__}"
            )

    cleared_retired_prefixes = []
    for retired_prefix in retired_inbox_prefixes:
        prefix_clean = True
        try:
            retired_objects = oss.list_keys(conf, retired_prefix)
        except Exception as e:
            cleanup_failed = True
            warnings.append(
                f"旧收件箱待清理 {retired_prefix}: {type(e).__name__}"
            )
            continue
        for item in retired_objects:
            retired_key = str(item.get("key") or "")
            suffix = retired_key[len(retired_prefix):] if retired_key.startswith(retired_prefix) else ""
            if not suffix or ".." in suffix.split("/"):
                prefix_clean = False
                cleanup_failed = True
                continue
            if retired_prefix == cloud_prefix + "inbox/" and "/" in suffix:
                # legacy 根前缀和当前 gN/ 前缀有包含关系。这里只清直接子对象，
                # 绝不能把新一代收件箱一起当旧对象删掉。
                continue
            try:
                oss.delete(conf, retired_key)
                deleted_remote += 1
            except Exception as e:
                if "HTTP 404" in str(e):
                    continue
                prefix_clean = False
                cleanup_failed = True
                warnings.append(
                    f"旧收件箱对象待清理 {retired_key}: {type(e).__name__}"
                )
        if prefix_clean and time.time() >= retired_expiry.get(retired_prefix, float("inf")):
            cleared_retired_prefixes.append(retired_prefix)

    # 本地也记一笔"已发布", 新人后台好显示状态。真值仍然在本地 space.json 里。
    stale = False
    with space_txn(sid) as space:
        try:
            current_revision = int(space.get("publishRevision") or 0)
        except (TypeError, ValueError):
            current_revision = 0
        revision_stale = current_revision != source_revision
        cleared_pending = set(deleted_pending)
        if not revision_stale:
            # 当前快照仍引用的 key 只可能是坏历史队列，清掉它即可。若发布期间真值
            # 已变化，这个 key 可能刚被删除动作重新加入队列，必须保留给下一轮清理。
            cleared_pending |= protected_pending
        if cleared_pending:
            space["_pendingCloudDeletes"] = [
                key for key in (space.get("_pendingCloudDeletes") or [])
                if key not in cleared_pending
            ]
            if not space["_pendingCloudDeletes"]:
                space.pop("_pendingCloudDeletes", None)
        if cleared_retired_prefixes:
            cleared_retired_set = set(cleared_retired_prefixes)
            remaining_retired = [
                item for item in _normal_retired_inboxes(sid, space)
                if item["prefix"] not in cleared_retired_set
            ]
            if remaining_retired:
                space["_retiredInboxPrefixes"] = remaining_retired
            else:
                space.pop("_retiredInboxPrefixes", None)
        if not revision_stale and not cleanup_failed:
            space["publishDirty"] = False
            space["publishedAt"] = public["publishedAt"]
        else:
            # 内容版本变化或旧云对象还没清干净,都不能标成完全同步。
            space["publishDirty"] = True
            stale = revision_stale

    # 落账本(不含 space.json —— 它每次内容都变, 必须每次重传)。
    # 写坏了也只是下次多打几次 head, 不影响正确性, 所以失败不抛。
    try:
        _save_publish_ledger(ledger_path, ledger)
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
        "deletedRemote": deleted_remote,
        "inboxPrefix": snapshot_inbox_prefix,
        "expiresAt": public["expiresAt"],
        "warnings": warnings,
        "stale": stale,
        "manifestSkipped": False,
        "cleanupPending": cleanup_failed,
        "public": public,
    }


def publish_space(sid, conf=None, progress=None, force=False):
    with _publish_lock(sid):
        # worker 是独立 Python 进程,单靠 threading.Lock 挡不住它和主服务同时发布。
        # 文件锁覆盖整轮上传,让同一 sid 的 OSS space.json 和本地账本跨进程也只
        # 有一个写者。锁文件本身不进公开清单。
        lock_path = os.path.join(space_dir(sid), ".publish.lock")
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                return _publish_space_locked(
                    sid, conf=conf, progress=progress, force=force,
                )
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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
