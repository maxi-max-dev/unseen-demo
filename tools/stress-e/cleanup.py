#!/usr/bin/env python3
"""
tools/stress-e/cleanup.py -- 批次E压测残留清理器。

只清「stress 开头」的空间, 硬编码前缀白名单挡在最前面, 别的空间一个键都碰不到。
两件事都做:
  1. 本机 server/spaces/<sid>/ 整个目录删掉(space.json、host.json、账本、节点素材)。
  2. 云端 OSS spaces/<sid>/ 前缀下的全部对象删掉(space.json、nodes/、pano-inbox/ 原图等)。

这不是 server/worker.py 的 --purge-inbox(那个只清收件箱, 保留已发布的素材,
是给还在用的真空间收尾用的)。压测空间用完就该整个消失, 所以是前缀全删,
思路照抄 --purge-inbox 的"list_keys 再逐个 delete", 范围更大。

用法:
    .venv/bin/python tools/stress-e/cleanup.py stresse0 stresse1 ...
    .venv/bin/python tools/stress-e/cleanup.py --list          # 只列出 stress* 空间, 不删
"""
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import oss, space  # noqa: E402


def list_stress_spaces():
    return sorted(
        sid for sid in os.listdir(space.SPACES_DIR)
        if sid.startswith("stress") and os.path.isdir(os.path.join(space.SPACES_DIR, sid))
    )


def cleanup_one(sid, conf):
    if not sid.startswith("stress"):
        print(f"❌ 拒绝清理 {sid}: 不是 stress 前缀, 大概率传错了参数")
        return False
    ok = True

    # 云端: 整个前缀下的对象全删
    prefix = f"spaces/{sid}/"
    try:
        keys = oss.list_keys(conf, prefix)
    except Exception as e:
        print(f"⚠️ {sid}: 列云端对象失败, 跳过云端清理: {e}")
        keys = None
        ok = False
    if keys is not None:
        deleted, failed = 0, []
        for item in keys:
            key = item["key"]
            try:
                oss.delete(conf, key)
                deleted += 1
            except Exception as e:
                failed.append((key, str(e)))
        print(f"☁️  {sid}: 云端 {prefix} 下 {len(keys)} 个对象, 删掉 {deleted} 个"
              + (f", {len(failed)} 个失败" if failed else ""))
        for key, err in failed:
            print(f"   ⚠️ 删不掉 {key}: {err}")
            ok = False

    # 本机: 整个空间目录删掉
    local_dir = space.space_dir(sid)
    if os.path.isdir(local_dir):
        shutil.rmtree(local_dir)
        print(f"🗑️  {sid}: 本机目录 {local_dir} 已删除")
    else:
        print(f"   {sid}: 本机目录本来就不在")

    return ok


def main():
    args = sys.argv[1:]
    if args == ["--list"]:
        found = list_stress_spaces()
        print(f"本机现存 {len(found)} 个 stress* 空间: {found}")
        return 0
    if not args:
        print(__doc__)
        return 1
    conf = oss.load_conf()
    all_ok = True
    for sid in args:
        all_ok = cleanup_one(sid, conf) and all_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
