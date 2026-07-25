#!/usr/bin/env python3
"""把 UNSEEN 的公开网页清单发布到独立 OSS 网站桶。

必须先在 OSS 控制台创建独立网站桶、绑定已备案自定义域名并托管 HTTPS 证书。
OSS 默认域名在所有地域都会强制下载 HTML,不能当网页入口。

用法:
    python3 tools/deploy_site.py --dry-run
    python3 tools/deploy_site.py --conf ~/.config/psm/aliyun-site.json \
      --domain https://unseen.example.cn

脚本只上传明确允许的公开静态文件,绝不遍历整个仓库。凭据只从文件读取且永不打印。
"""
import argparse
import concurrent.futures
import os
import secrets
import sys
import urllib.parse
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import oss  # noqa: E402

# oss.guess_type 只认站点里出现过的那几种,这里补齐剩下的。
# 类型给错的代价不是报错而是静默失效:.js 给成 octet-stream 浏览器就不执行它。
EXTRA_TYPES = {
    ".ico": "image/x-icon", ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8", ".webm": "video/webm", ".mp3": "audio/mpeg",
    ".wav": "audio/wav", ".gif": "image/gif", ".woff2": "font/woff2", ".woff": "font/woff",
    ".glb": "model/gltf-binary", ".csv": "text/csv; charset=utf-8",
}
TEXT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
              ".js": "application/javascript; charset=utf-8",
              ".json": "application/json; charset=utf-8"}

MANIFEST = os.path.join(REPO_ROOT, "deploy", "public-files.txt")
MARKER_KEY = "_unseen-site-bucket-v1.txt"
MARKER_BODY = b"UNSEEN static site bucket v1\n"
PROBE_HTML = (b"<!doctype html><meta charset=utf-8><title>UNSEEN render test</title>"
              b"<h1>RENDER-OK</h1><p>\xe8\xbf\x99\xe9\xa1\xb5\xe8\x83\xbd\xe7\x9c\x8b\xe8\xa7\x81"
              b"\xe5\xb0\xb1\xe8\xaf\xb4\xe6\x98\x8e\xe4\xb8\x8d\xe8\xa2\xab\xe5\xbc\xba\xe5\x88\xb6"
              b"\xe4\xb8\x8b\xe8\xbd\xbd\xe3\x80\x82")
ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".json", ".jpg", ".png", ".ico", ".mp4"}


def content_type(path):
    ext = os.path.splitext(path)[1].lower()
    return TEXT_TYPES.get(ext) or EXTRA_TYPES.get(ext) or oss.guess_type(path)


def normalize_domain(value):
    p = urllib.parse.urlsplit(value.strip())
    if p.scheme != "https" or not p.netloc or p.path not in ("", "/") or p.query or p.fragment:
        raise ValueError("--domain 必须是只含协议和域名的 HTTPS 地址")
    if p.username or p.password or (p.port not in (None, 443)):
        raise ValueError("--domain 不能包含账号、密码或非标准端口")
    if (p.hostname or "").lower().endswith("aliyuncs.com"):
        raise ValueError("OSS 默认域名不能渲染 HTML,请传已绑定的自定义域名")
    return f"https://{p.netloc}"


def probe(conf, domain):
    """先经自定义域名打开测试页,过了渲染生死闸才上传网站。"""
    key = f"_probe/render-{secrets.token_hex(8)}.html"
    try:
        oss.put_bytes(conf, key, PROBE_HTML, content_type="text/html; charset=utf-8",
                      oss_headers={"x-oss-object-acl": "public-read"})
        url = domain + "/" + urllib.parse.quote(key, safe="/")
        with urllib.request.urlopen(url, timeout=30) as r:
            disp = r.headers.get("Content-Disposition", "")
            body = r.read()
        ok = b"RENDER-OK" in body and "attachment" not in disp.lower()
        print("自定义域名渲染检查:", "✅ 通过" if ok else "❌ 失败")
        return ok
    except Exception:
        print("❌ 自定义域名渲染检查失败,云端错误详情已隐藏")
        return False
    finally:
        try:
            oss.delete(conf, key)
        except Exception:
            pass


def site_items():
    with open(MANIFEST, encoding="utf-8") as f:
        candidates = [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]
    if len(candidates) != len(set(candidates)):
        raise RuntimeError("公开文件清单含重复项")
    repo_real = os.path.realpath(REPO_ROOT)
    out = []
    for rel in candidates:
        if rel.startswith("/") or os.path.splitext(rel)[1].lower() not in ALLOWED_EXTENSIONS:
            raise RuntimeError("公开文件清单含不允许的路径或类型")
        full = os.path.realpath(os.path.join(REPO_ROOT, rel))
        if os.path.commonpath((repo_real, full)) != repo_real:
            raise RuntimeError("公开文件清单越出仓库")
        if os.path.islink(os.path.join(REPO_ROOT, rel)) or not os.path.isfile(full):
            raise RuntimeError("公开文件清单含缺失文件或非普通文件")
        out.append((full, rel))
    return out


def dedicated_bucket_ok(conf, allowed_keys):
    """首次只认空桶,复发只认本工具打标且不含清单外对象的站点桶。"""
    try:
        rows = oss.list_keys(conf, prefix="", max_keys=1000)
    except Exception:
        print("❌ 无法确认目标桶是否为独立网站桶,已停止")
        return False
    if len(rows) >= 1000:
        print("❌ 目标桶对象过多,无法证明它是独立网站桶,已停止")
        return False
    keys = {row.get("key", "") for row in rows}
    if not keys:
        return True
    if MARKER_KEY not in keys:
        print("❌ 目标桶不是空桶且没有 UNSEEN 站点标记,已停止")
        return False
    extras = {key for key in keys
              if key not in allowed_keys and key != MARKER_KEY
              and not (key.startswith("_probe/render-") and key.endswith(".html"))}
    if extras:
        print("❌ 目标桶含公开清单之外的对象,已停止")
        return False
    return True


def verify_site(domain):
    checks = ("portal.html", "web/join.html?s=s4", "web/show.html?s=s4", "web/demo.html")
    try:
        for path in checks:
            with urllib.request.urlopen(domain + "/" + path, timeout=30) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                body = r.read(4096).lower()
                if r.status != 200 or "text/html" not in ctype or b"<html" not in body:
                    raise RuntimeError("入口返回内容不对")
    except Exception:
        print("❌ 关键入口验收失败,云端错误详情已隐藏")
        return False
    print("关键入口验收: ✅ 4/4")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf")
    ap.add_argument("--domain")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    items = site_items()
    total = len(items)
    total_bytes = sum(os.path.getsize(full) for full, _key in items)
    print(f"公开站点清单:{total} 个文件,共 {total_bytes / 1024 / 1024:.1f} MB")
    if a.dry_run:
        return 0
    if not a.conf or not a.domain:
        ap.error("正式发布必须同时提供 --conf 和 --domain")
    if not 1 <= a.workers <= 16:
        ap.error("--workers 必须在 1 到 16 之间")

    try:
        domain = normalize_domain(a.domain)
    except ValueError as e:
        print("❌", e)
        return 2
    try:
        conf = oss.load_conf(os.path.expanduser(a.conf))
    except Exception:
        print("❌ 无法读取网站桶配置,详情已隐藏")
        return 2
    allowed_keys = {key for _full, key in items}
    if not dedicated_bucket_ok(conf, allowed_keys):
        return 2
    try:
        oss.put_bytes(conf, MARKER_KEY, MARKER_BODY, content_type="text/plain; charset=utf-8",
                      oss_headers={"x-oss-object-acl": "public-read"})
    except Exception:
        print("❌ 无法写入站点标记,云端错误详情已隐藏")
        return 2
    if not probe(conf, domain):
        print("自定义域名还不能正常渲染 HTML,未上传网站")
        return 2

    def one(item):
        full, key = item
        ct = content_type(key)
        if os.path.splitext(key)[1].lower() in {".html", ".css", ".js", ".json"}:
            with open(full, "rb") as f:
                data = f.read().replace(b"https://unseen-demo.vercel.app", domain.encode())
            oss.put_bytes(conf, key, data, content_type=ct,
                          oss_headers={"x-oss-object-acl": "public-read"}, timeout=300)
        else:
            oss.put_file(conf, key, full, content_type=ct,
                         oss_headers={"x-oss-object-acl": "public-read"}, timeout=300)
        return key

    # 先资源和脚本,再普通 HTML,最后入口页。这样更新窗口不会先出现新 HTML 配旧资源。
    def phase(item):
        key = item[1]
        if key in {"portal.html", "index.html"}:
            return 2
        return 1 if key.endswith(".html") else 0

    failed = []
    done_count = 0
    for rank in (0, 1, 2):
        batch = [item for item in items if phase(item) == rank]
        phase_failed = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
            futures = {ex.submit(one, item): item[1] for item in batch}
            for fut in concurrent.futures.as_completed(futures):
                key = futures[fut]
                try:
                    fut.result()
                except Exception:
                    phase_failed.append(key)
                done_count += 1
                if done_count % 20 == 0 or done_count == total:
                    print(f"  {done_count}/{total}")
        failed.extend(phase_failed)
        if phase_failed:
            break

    if failed:
        print(f"失败 {len(failed)} 个,未输出云端错误详情以避免泄露配置")
        for key in failed[:20]:
            print("  ", key)
        return 1

    if not verify_site(domain):
        return 1
    try:
        with open(os.path.join(REPO_ROOT, "server", "public_site_url.txt"), "w", encoding="utf-8") as f:
            f.write(domain + "\n")
    except Exception:
        print("⚠️ 网站已发布,但本机公网域名记录写入失败")
    print("✅ 网站文件已上传并通过入口验收。入口地址:")
    for p in ("portal.html", "web/join.html?s=s4", "web/show.html?s=s4", "web/demo.html"):
        print("  ", f"{domain}/{p}")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        print("发布已中止")
        code = 130
    except Exception:
        print("❌ 发布流程异常,云端错误详情已隐藏")
        code = 1
    sys.exit(code)
