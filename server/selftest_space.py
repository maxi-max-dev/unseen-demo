#!/usr/bin/env python3
"""
server/selftest_space.py -- 直接调 server/space.py 里的函数跑一遍完整闭环, 不走 HTTP,
免得还要先起服务器。用 assets/walkdemo/ 的宴会厅全景 + 宾客照片当素材。

跑法(cwd 必须是仓库根目录):
    .venv/bin/python server/selftest_space.py

会真跑 DAP 深度模型(几十秒正常)。加 --skip-depth 可以跳过深度只测闭环逻辑。
"""
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import space as S  # noqa: E402

DEMO = os.path.join(REPO_ROOT, "assets", "walkdemo")
PANO = os.path.join(DEMO, "ballroom.jpg")
GUESTS = [os.path.join(DEMO, f"ballroom_j{i}.jpg") for i in (1, 2, 3)]


def hr(title):
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68, flush=True)


def show_tasks(space):
    for t in space["tasks"]:
        img = t.get("briefImage") or "-"
        rng = t.get("yawRange")
        print(f"  [{t['id']}] {t['type']:4s} {t['status']:6s} 悬赏{t['bounty']:>4}  "
              f"yaw={t.get('yaw')} range={rng}")
        print(f"        「{t['title']}」{t['brief']}")
        print(f"        通缉令: {img}  filledBy={t['filledBy']}")


def show_photos(space):
    for p in space["photos"]:
        print(f"  [{p['id']}] node={p['nodeId']} yaw={p['yaw']:>6} conf={p['confidence']:.4f} "
              f"state={p['state']:12s} task={p.get('taskId')} by={p['contributor']}")
        print(f"        {p['reason']}")


def main():
    skip_depth = "--skip-depth" in sys.argv
    for f in [PANO] + GUESTS:
        assert os.path.exists(f), f"素材缺失: {f}"

    hr("1. 建空间 create_space()")
    sid = S.create_space("陈屹 ♥ 林沐 · 2026.7.26", "陈屹 & 林沐")
    print(f"  spaceId = {sid}")
    print(f"  目录     = {S.space_dir(sid)}")

    hr("2. 传全景 add_node()  —— 会真跑 DAP 深度模型")
    if skip_depth:
        S.run_depth = lambda *a, **k: (0.0, "(skipped)")
    t0 = time.time()
    nid, created, timings = S.add_node(
        sid, open(PANO, "rb").read(), "ballroom.jpg", "image/jpeg", "宴会厅", "18:00",
    )
    print(f"  nodeId = {nid}   总耗时 {time.time()-t0:.1f}s   分段耗时 {timings}")
    sp = S.get_space(sid)
    print(f"  节点记录: {json.dumps(sp['nodes'][0], ensure_ascii=False)}")
    print(f"\n  ✅ 零照片状态下自动生成了 {len(created)} 个 gap 任务:")
    show_tasks(sp)
    for t in sp["tasks"]:
        if t.get("briefImage"):
            p = os.path.join(S.space_dir(sid), t["briefImage"])
            print(f"  通缉令文件 {p}  {os.path.getsize(p)} bytes  存在={os.path.exists(p)}")

    hr("3. 覆盖盲区算法 find_coverage_gaps() 纯计算结果(零照片时)")
    print(" ", S.find_coverage_gaps(S.get_space(sid), nid))

    hr("4. 宾客上传 3 张照片 upload_photos()")
    files = [(os.path.basename(g), "image/jpeg", open(g, "rb").read()) for g in GUESTS]
    t0 = time.time()
    results = S.upload_photos(sid, files, "小明")
    print(f"  CLIP 定位 + 分流耗时 {time.time()-t0:.1f}s")
    for r in results:
        print(f"  {r['photoId']}: yaw={r['yaw']:>6} ({r['direction']}) conf={r['confidence']:.4f} "
              f"-> {r['state']}  taskFilled={r['taskFilled']}")
        print(f"        {r['reason']}")

    sp = S.get_space(sid)
    print("\n  分流统计 stats:", json.dumps(sp["stats"], ensure_ascii=False))
    print("  任务现状:")
    show_tasks(sp)
    print("  贡献榜:", json.dumps(sp["contributors"], ensure_ascii=False))

    hr("5. 覆盖盲区算法(3 张照片进空间后)")
    print(" ", S.find_coverage_gaps(S.get_space(sid), nid))

    hr("5b. 置信度分流的两条分支 —— 传一张【根本不是这个房间】的照片(咖啡馆)")
    outsider = os.path.join(DEMO, "comfy_cafe_j1.jpg")
    r = S.upload_photos(sid, [("comfy_cafe_j1.jpg", "image/jpeg", open(outsider, "rb").read())], "路人甲")[0]
    print(f"  阈值 CONF_MIN={S.CONF_MIN}(契约值)")
    print(f"  {r['photoId']}: conf={r['confidence']:.4f} -> {r['state']}")
    print(f"        {r['reason']}")
    print("  ⚠️ 外场景照片也被自动放进了空间 —— 契约阈值 0.45 太低, 实测本场景 0.87~0.95、"
          "外场景 0.61~0.79, 分界线在 0.82 附近")

    print("\n  把阈值临时调到 0.82 再传一张同样的外场景照片, 验证 needs_review 分支真的能跑:")
    old = S.CONF_MIN
    S.CONF_MIN = 0.82
    try:
        r2 = S.upload_photos(sid, [("comfy_cafe_j2.jpg", "image/jpeg",
                                    open(os.path.join(DEMO, "comfy_cafe_j2.jpg"), "rb").read())], "路人乙")[0]
        print(f"  {r2['photoId']}: conf={r2['confidence']:.4f} -> {r2['state']}")
        print(f"        {r2['reason']}")
    finally:
        S.CONF_MIN = old

    hr("6. 新人发心愿任务 create_wish_task()")
    wish = S.create_wish_task(sid, "我想要一张我妈妈笑的照片", "敬酒那会儿她一直在笑")
    print(" ", json.dumps(wish, ensure_ascii=False))

    hr("7. 新人审核 review_photos()")
    sp = S.get_space(sid)
    pending = [p for p in sp["photos"] if p["state"] == "needs_review"]
    print(f"  待审队列 {len(pending)} 张: {[p['id'] for p in pending]}")
    if pending:
        target = pending[0]
        print(f"  -> approve {target['id']}")
        n = S.review_photos(sid, [{"photoId": target["id"], "action": "approve"}])
    else:
        target = sp["photos"][0]
        print(f"  (没有待审的, 改为演示 reject 一张再 approve 回来: {target['id']})")
        S.review_photos(sid, [{"photoId": target["id"], "action": "reject"}])
        print("     reject 后 stats:", json.dumps(S.get_space(sid)["stats"], ensure_ascii=False))
        print("     reject 后缺口:", S.find_coverage_gaps(S.get_space(sid), nid))
        n = S.review_photos(sid, [{"photoId": target["id"], "action": "approve"}])
    print(f"  updated = {n}")

    sp = S.get_space(sid)
    print("  审核后 stats:", json.dumps(sp["stats"], ensure_ascii=False))
    print("  审核后贡献榜:", json.dumps(sp["contributors"], ensure_ascii=False))

    hr("8. 审核后重算的缺口 + 任务全貌")
    print("  find_coverage_gaps ->", S.find_coverage_gaps(sp, nid))
    show_tasks(sp)

    hr("9. guest 视角 vs host 视角")
    g = S.get_space(sid, role="guest")
    h = S.get_space(sid, role="host")
    print(f"  guest 看到 {len(g['photos'])} 张 (只含 auto_ok/approved), stats 字段存在={'stats' in g}")
    print(f"  host  看到 {len(h['photos'])} 张, stats={json.dumps(h['stats'], ensure_ascii=False)}")

    hr("10. 宾客链接 + 发布")
    print("  joinurl =", S.guest_url(sid))
    print("  publish =", S.publish_space(sid))
    print("  spaces  =", json.dumps(S.list_spaces(), ensure_ascii=False))

    hr("11. 最终 space.json")
    print(open(S.space_json_path(sid), encoding="utf-8").read())

    hr("12. 落盘文件清单")
    for root, _dirs, fs in os.walk(S.space_dir(sid)):
        for f in sorted(fs):
            p = os.path.join(root, f)
            print(f"  {os.path.relpath(p, S.space_dir(sid)):40s} {os.path.getsize(p):>10} bytes")


if __name__ == "__main__":
    main()
