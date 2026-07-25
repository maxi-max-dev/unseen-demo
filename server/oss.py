#!/usr/bin/env python3
"""
server/oss.py -- 阿里云 OSS 客户端(零依赖,只用标准库)。

为什么不用官方 SDK(oss2): 仓库铁律是零新依赖, 而我们只需要 put/get/list/delete 四个动作
加一个「浏览器直传签名」, OSS 的 V1 签名就是一段 HMAC-SHA1, 手写比引一个包划算。

为什么要 OSS: 现场在杭州, 宾客手机走移动数据。OSS 华东1(杭州)和宾客手机同城,
是全场唯一物理上不用出国的一跳。而且用【浏览器直传】之后, Max 的电脑不需要暴露到公网 ——
宾客的照片直接进 OSS, Mac 只是一个在旁边轮询、算完再写回去的后台工人。

凭据放 ~/.config/psm/aliyun.json(不进仓库、不进聊天记录):
    {"bucket": "...", "region": "oss-cn-hangzhou", "accessKeyId": "...", "accessKeySecret": "..."}

单独跑法(连通性自检):
    .venv/bin/python -m server.oss selftest
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import formatdate

CONF_PATH = os.path.expanduser("~/.config/psm/aliyun.json")

# V1 签名里要参与计算的子资源(只有这些, 普通 query 参数如 prefix/max-keys 不算)
SUB_RESOURCES = {
    "acl", "uploads", "location", "cors", "logging", "website", "referer", "lifecycle",
    "delete", "append", "tagging", "objectMeta", "uploadId", "partNumber", "security-token",
    "position", "response-content-type", "response-content-disposition", "restore",
    "callback", "callback-var", "symlink",
}


class OSSError(RuntimeError):
    pass


def load_conf(path=CONF_PATH):
    if not os.path.exists(path):
        raise OSSError(f"没找到阿里云凭据文件: {path}")
    with open(path, encoding="utf-8") as f:
        conf = json.load(f)
    for k in ("bucket", "region", "accessKeyId", "accessKeySecret"):
        if not conf.get(k):
            raise OSSError(f"凭据文件缺字段: {k}")
    return conf


def endpoint(conf):
    return f"https://{conf['bucket']}.{conf['region']}.aliyuncs.com"


def public_url(conf, key):
    return f"{endpoint(conf)}/{urllib.parse.quote(key)}"


# ---------------------------------------------------------------- 签名
def _canonical_resource(bucket, key, query=None):
    res = f"/{bucket}/{key}" if key else f"/{bucket}/"
    if query:
        subs = sorted((k, v) for k, v in query.items() if k in SUB_RESOURCES)
        if subs:
            res += "?" + "&".join(k if v in (None, "") else f"{k}={v}" for k, v in subs)
    return res


def _sign(conf, method, key, content_type="", content_md5="", date=None,
          oss_headers=None, query=None):
    """OSS V1 签名。拼串顺序是死的, 错一个换行就 403, 别乱动。"""
    date = date or formatdate(usegmt=True)
    canon_headers = ""
    for hk in sorted((oss_headers or {}).keys()):
        canon_headers += f"{hk.lower()}:{oss_headers[hk]}\n"
    to_sign = (f"{method}\n{content_md5}\n{content_type}\n{date}\n"
               f"{canon_headers}{_canonical_resource(conf['bucket'], key, query)}")
    sig = base64.b64encode(
        hmac.new(conf["accessKeySecret"].encode(), to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    return date, f"OSS {conf['accessKeyId']}:{sig}"


def _request(conf, method, key="", data=None, content_type="", query=None,
             oss_headers=None, timeout=60):
    url = endpoint(conf) + "/" + urllib.parse.quote(key)
    if query:
        url += "?" + urllib.parse.urlencode(query)

    content_md5 = ""
    if data is not None:
        content_md5 = base64.b64encode(hashlib.md5(data).digest()).decode()

    date, auth = _sign(conf, method, key, content_type=content_type,
                       content_md5=content_md5, oss_headers=oss_headers, query=query)
    headers = {"Date": date, "Authorization": auth}
    if content_type:
        headers["Content-Type"] = content_type
    if content_md5:
        headers["Content-MD5"] = content_md5
    headers.update(oss_headers or {})

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:800].decode("utf-8", "ignore")
        raise OSSError(f"OSS {method} {key or '/'} 失败 HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise OSSError(f"连不上 OSS({e.reason})——检查网络或 region 是否写错")


# ---------------------------------------------------------------- 四个基本动作
GUESS_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".mp4": "video/mp4", ".json": "application/json",
    ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
}


def guess_type(key):
    return GUESS_TYPES.get(os.path.splitext(key)[1].lower(), "application/octet-stream")


def put_bytes(conf, key, data, content_type=None, oss_headers=None, timeout=60):
    ct = content_type or guess_type(key)
    _request(conf, "PUT", key, data=data, content_type=ct, oss_headers=oss_headers,
             timeout=timeout)
    return public_url(conf, key)


def put_file(conf, key, path, content_type=None, oss_headers=None, timeout=60):
    with open(path, "rb") as f:
        return put_bytes(conf, key, f.read(), content_type, oss_headers, timeout=timeout)


def get_bytes(conf, key):
    _s, _h, body = _request(conf, "GET", key)
    return body


def head(conf, key):
    """存在就返回响应头 dict, 不存在返回 None。"""
    try:
        _s, h, _b = _request(conf, "HEAD", key)
        return h
    except OSSError as e:
        if "HTTP 404" in str(e):
            return None
        raise


def delete(conf, key):
    _request(conf, "DELETE", key)


def list_keys(conf, prefix="", max_keys=1000):
    """列完整前缀。V1 每页最多 1000 个对象，按 NextMarker 一直翻到末页。"""
    import xml.etree.ElementTree as ET

    out = []
    marker = ""
    seen_markers = set()
    while True:
        q = {"prefix": prefix, "max-keys": str(max_keys)}
        if marker:
            q["marker"] = marker
        _s, _h, body = _request(conf, "GET", "", query=q)
        root = ET.fromstring(body)

        def local_name(element):
            return element.tag.rsplit("}", 1)[-1]

        def child_text(parent, name):
            for child in parent:
                if local_name(child) == name:
                    return child.text or ""
            return ""

        page = []
        for element in root:
            if local_name(element) != "Contents":
                continue
            page.append({
                "key": child_text(element, "Key"),
                "size": int(child_text(element, "Size") or 0),
                "lastModified": child_text(element, "LastModified"),
            })
        out.extend(page)
        truncated = child_text(root, "IsTruncated").strip().lower() == "true"
        if not truncated:
            break
        next_marker = child_text(root, "NextMarker") or (page[-1]["key"] if page else "")
        if not next_marker or next_marker in seen_markers:
            raise OSSError("OSS 列目录分页标记无效")
        seen_markers.add(next_marker)
        marker = next_marker
    return out


# ---------------------------------------------------------------- 浏览器直传签名
def post_policy(conf, key_prefix, expire_s=48 * 3600, max_size=12 * 1024 * 1024):
    """生成【浏览器直传】用的 PostObject 策略。

    宾客的手机拿着这份策略, 可以把照片直接 POST 进 OSS, 不经过任何服务器 ——
    所以 Max 的电脑完全不用暴露到公网, 这是整个架构最关键的一步。

    安全边界(要如实告诉用户): 拿到这份策略的人, 在有效期内可以往 key_prefix 下面
    传 ≤max_size 的文件。它【不能】读别人的东西、不能删、不能跳出这个前缀、过期即失效。
    对一场活动来说这个代价是合理的; 活动结束把 Bucket 改回私有即可。
    """
    expiration = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + expire_s))
    policy = {
        "expiration": expiration,
        "conditions": [
            ["content-length-range", 0, max_size],
            ["starts-with", "$key", key_prefix],
            {"x-oss-object-acl": "private"},
        ],
    }
    raw = base64.b64encode(json.dumps(policy).encode()).decode()
    sig = base64.b64encode(
        hmac.new(conf["accessKeySecret"].encode(), raw.encode(), hashlib.sha1).digest()
    ).decode()
    return {
        "host": endpoint(conf),
        "OSSAccessKeyId": conf["accessKeyId"],
        "policy": raw,
        "signature": sig,
        "keyPrefix": key_prefix,
        "expiresAt": time.time() + expire_s,
        "maxSize": max_size,
    }


# ---------------------------------------------------------------- 自检
def selftest():
    conf = load_conf()
    print(f"Bucket: {conf['bucket']} @ {conf['region']}")
    print(f"域名:   {endpoint(conf)}")
    ok = True

    probe = "psm-selftest/hello.txt"
    try:
        url = put_bytes(conf, probe, "空间记忆连通性自检\n".encode(), "text/plain")
        print(f"✅ 写入成功: {url}")
    except OSSError as e:
        print(f"❌ 写入失败: {e}")
        return False

    try:
        got = get_bytes(conf, probe)
        print(f"✅ 读回成功: {got.decode().strip()}")
    except OSSError as e:
        print(f"❌ 读回失败: {e}")
        ok = False

    # 关键测试: 默认域名下图片是不是被强制下载(Content-Disposition: attachment)。
    # 如果是, 三个前端页面就没法直接 <img> 引用 OSS 上的照片, 整个方案要改。
    try:
        img_key = "psm-selftest/probe.jpg"
        tiny = base64.b64decode(
            "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
            "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
            "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")
        put_bytes(conf, img_key, tiny, "image/jpeg")
        with urllib.request.urlopen(public_url(conf, img_key), timeout=30) as r:
            disp = r.headers.get("Content-Disposition", "")
            ctype = r.headers.get("Content-Type", "")
        if "attachment" in disp.lower():
            print(f"⚠️ 图片被强制下载(Content-Disposition: {disp}) —— 前端不能直接 <img> 引用")
            ok = False
        else:
            print(f"✅ 图片可公开直读且能内联显示(Content-Type: {ctype}, Disposition: {disp or '无'})")
        delete(conf, img_key)
    except Exception as e:
        print(f"⚠️ 公开读测试失败(可能 Bucket 不是公共读): {e}")
        ok = False

    try:
        keys = list_keys(conf, prefix="psm-selftest/")
        print(f"✅ 列目录成功: {[k['key'] for k in keys]}")
    except OSSError as e:
        print(f"❌ 列目录失败: {e}")
        ok = False

    try:
        delete(conf, probe)
        print("✅ 删除成功")
    except OSSError as e:
        print(f"❌ 删除失败: {e}")
        ok = False

    p = post_policy(conf, "spaces/demo/photos/")
    print(f"✅ 直传策略已生成(前缀 {p['keyPrefix']}, 上限 {p['maxSize']//1024//1024}MB)")
    return ok


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        raise SystemExit(0 if selftest() else 1)
    print(__doc__)
