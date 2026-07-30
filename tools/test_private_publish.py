#!/usr/bin/env python3
"""固定回归: private=true 的空间绝不能被发布成公开可读(P1-4)。

跑法(仓库根目录):
    .venv/bin/python -m tools.test_private_publish
退出码 0 = 通过, 1 = 挂了。

为什么这条要单独测: 本机访客路由确实查了 private, 但那只挡"从这台机器的 API 看它",
挡不住发布器 —— 发布器会把 space.json、全景和入选照片逐个设成 public-read。
空间 id 又是递增的 sN, 猜得到。所以"拦得住"的判据不是"报了个错",
而是【一个字节都没往 OSS 写】。

这个测试全程不碰真 OSS: 所有写操作(put_bytes/put_file/delete)都被换成会炸的桩,
一旦被调用就说明闸门漏了。用的空间是现造的 stresspriv1(stress 前缀, 跑完删掉),
不碰 s4, 也不碰任何真实空间。
"""
import json
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import oss, publish, space  # noqa: E402

SOURCE_SID = "stressexp1"       # 拿它当模板: 真节点、真素材、已发布状态
TEST_SID = "stresspriv1"        # 本测试现造的空间, 跑完删


class UploadAttempted(Exception):
    """哨兵: 只要发布器真的动手往 OSS 写, 就抛这个。"""


def install_write_traps():
    """把 OSS 的三个写入口全换成会炸的桩, 返回还原用的原函数表。"""
    originals = {name: getattr(oss, name) for name in ("put_bytes", "put_file", "delete")}

    def trap(name):
        def _boom(*a, **kw):
            key = a[1] if len(a) > 1 else kw.get("key", "?")
            raise UploadAttempted(f"oss.{name} 被调用了, key={key}")
        return _boom

    for name in originals:
        setattr(oss, name, trap(name))
    return originals


def restore(originals):
    for name, fn in originals.items():
        setattr(oss, name, fn)


def make_test_space(private):
    """按模板造一个空间, private 由参数决定, 其余一切保持"本该能发布"的状态。"""
    src = space.space_dir(SOURCE_SID)
    dst = space.space_dir(TEST_SID)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    path = os.path.join(dst, "space.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["id"] = TEST_SID
    data["private"] = private
    data["published"] = True
    data["publishDirty"] = True
    data.pop("_cloudPublishBlocked", None)
    # 发布账本按模板抄过来的话, 发布器会以为这些 key 已经在云上了。清掉, 让它老实重传
    # (虽然它根本传不出去 —— 那正是本测试要证明的)。
    for sidecar in (".published.json",):
        p = os.path.join(dst, sidecar)
        if os.path.exists(p):
            os.remove(p)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return dst


def cleanup():
    dst = space.space_dir(TEST_SID)
    # 只删自己造的那一个, 路径必须逐字对上, 免得手滑删到别人的空间。
    if os.path.basename(dst.rstrip(os.sep)) == TEST_SID and os.path.isdir(dst):
        shutil.rmtree(dst)


def main():
    if not os.path.isdir(space.space_dir(SOURCE_SID)):
        print(f"❌ 模板空间不在: {space.space_dir(SOURCE_SID)}")
        return 1

    fails = []
    originals = install_write_traps()
    try:
        # ---- 用例一: private=true 必须被拦, 且一个字节都没往 OSS 写 ----
        make_test_space(private=True)
        try:
            publish.publish_space(TEST_SID)
            fails.append("private=true 的空间竟然发布成功了(闸门完全没起作用)")
        except UploadAttempted as e:
            fails.append(f"闸门漏了: 私密空间已经开始往 OSS 写东西 —— {e}")
        except RuntimeError as e:
            if "私密" not in str(e):
                fails.append(f"是拦住了, 但报错不是私密这条(可能被别的原因挡下, 测试无效): {e}")
            else:
                print(f"✅ 用例一 private=true: 被拦住, 零 OSS 写入\n   报错原文: {e}")

        # ---- 用例二(对照组): 同一个空间改成 private=false, 必须能走到上传那一步 ----
        # 没有这一组, 用例一可能是被别的原因(草稿/素材缺失/授权)挡下的, 那样测试就是假绿。
        make_test_space(private=False)
        try:
            publish.publish_space(TEST_SID)
            fails.append("对照组: 写操作被桩掉了却还是'发布成功', 说明桩没装上, 测试无效")
        except UploadAttempted as e:
            print(f"✅ 用例二 private=false(对照组): 顺利走到上传那一步\n   证据: {e}")
        except RuntimeError as e:
            fails.append(f"对照组被别的原因挡下了, 用例一的结论不可信: {e}")

        # ---- 用例三: 授权判定本身也要对私密空间说不 ----
        probe = {"published": True, "exhibition": {"status": "published"}, "private": True}
        if space._cloud_publish_authorized(probe):
            fails.append("_cloud_publish_authorized 对 private=true 仍然放行, 工人会一轮一轮白撞")
        else:
            print("✅ 用例三: _cloud_publish_authorized 对 private=true 判否, 上游不会反复尝试")
    finally:
        restore(originals)
        cleanup()

    if fails:
        print("\n❌ 不通过:")
        for f in fails:
            print("   -", f)
        return 1
    print("\n✅ 通过: 私密空间发不出去, 而且拦在任何 OSS 写入之前")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
