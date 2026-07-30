#!/usr/bin/env python3
"""固定回归: 主链照片定位必须只取 30° 网格峰值, 不许再做 ±30° 插值精修。

跑法(仓库根目录):
    .venv/bin/python -m tools.test_yaw_peak
退出码 0 = 通过, 1 = 挂了。

夹具 server/sessions/fixture 的 004.jpg 是这条缺陷的活证据:
  · 正确答案 yaw=150。肉眼复核过: 把全景按 yaw145/pitch10 切一张和 004.jpg 并排比,
    门框/吊灯/挂画全对得上; 按 yaw164.9/pitch15 切出来的整体右移了一个门洞。
  · 旧算法(tools/match.py 的 match_one)给 164.9, 偏 15 度, 而 confidence 照报 0.9265
    —— 置信度更高、位置更错, 审核的人看见 0.9265 反而不会去查它。
  · 修法: server/space.py 的 _match_grid_peak 只取峰值, 精度诚实到 ±15°,
    不伪造小数位。理由全文见该函数注释和 server/repair.py 的 score_photo。

这个测试【不写任何文件】: 自己在内存里切 12 张裁切, 不走 space._node_crop_bank
(那个会在夹具目录里落一个 crops.npz, 把仓库弄脏)。
"""
import os
import sys

import numpy as np
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from server import space  # noqa: E402
from tools.match import match_one  # noqa: E402
from tools.slice import equirect_to_perspective, FOV, CROP_W, CROP_H, YAWS  # noqa: E402

FIXTURE = os.path.join(REPO_ROOT, "server", "sessions", "fixture")
PHOTO = os.path.join(FIXTURE, "photos", "004.jpg")
PANO = os.path.join(FIXTURE, "pano.jpg")

EXPECT_YAW = 150.0        # 网格峰值, 也是肉眼复核过的正确答案
OLD_BUGGY_YAW = 164.9     # 旧插值算法给的值, 留在这里当反例


def build_bank():
    """和主链 _node_crop_bank 同一条切法: 12 个 yaw、pitch 固定 0、FOV 70、800x600。"""
    pano_np = np.asarray(Image.open(PANO).convert("RGB"))
    crops = [
        Image.fromarray(equirect_to_perspective(
            pano_np, fov_deg=FOV, yaw_deg=yaw, pitch_deg=0, out_w=CROP_W, out_h=CROP_H,
        ))
        for yaw in YAWS
    ]
    embs = space.clip_encode(crops, batch_size=12)
    return embs, np.array(["n1"] * len(YAWS)), np.array(list(YAWS), dtype=np.int32)


def main():
    for path in (PHOTO, PANO):
        if not os.path.exists(path):
            print(f"❌ 夹具缺文件: {path}")
            return 1

    bank_embs, bank_nodes, bank_yaws = build_bank()
    emb = space.clip_encode([Image.open(PHOTO).convert("RGB")], batch_size=1)[0]
    sims = bank_embs @ emb

    new_node, new_yaw, new_conf, new_sim0 = space._match_grid_peak(sims, bank_nodes, bank_yaws)
    old_node, old_yaw, old_conf, old_sim0 = match_one(sims, bank_nodes, bank_yaws)

    order = np.argsort(-sims)[:3]
    print("夹具 004.jpg 在 12 张裁切上的相似度前三:")
    for i in order:
        print(f"    yaw{int(bank_yaws[i]):3d} = {float(sims[i]):.4f}")
    print(f"\n新算法(网格峰值, 主链在用): yaw={new_yaw:.1f} confidence={new_conf:.4f}")
    print(f"旧算法(match_one 插值精修): yaw={old_yaw:.1f} confidence={old_conf:.4f}"
          f"   ← 参考值 {OLD_BUGGY_YAW}, 偏了一个门洞")

    fails = []
    if abs(new_yaw - EXPECT_YAW) > 1e-6:
        fails.append(f"主链 yaw 应为 {EXPECT_YAW}, 实得 {new_yaw}")
    if new_node != "n1":
        fails.append(f"节点应为 n1, 实得 {new_node}")
    # 这条不是"要求旧算法永远错", 而是证明这次修改是有分量的:
    # 如果两个算法给出同一个答案, 说明这条回归根本没在测东西。
    if abs(old_yaw - new_yaw) < 1e-6:
        fails.append("旧算法和新算法给了同一个 yaw, 这条回归失去意义, 请复核夹具")
    # 置信度不该被这次修改动到: match_one 的 confidence 本来就是 clip(sim0),
    # 不是插值产物, 所以 CONF_MIN/MARGIN_MIN 的标定不受影响。
    if abs(new_conf - old_conf) > 1e-9:
        fails.append(f"置信度被改动了({old_conf} -> {new_conf}), 阈值标定会失效")

    if fails:
        print("\n❌ 不通过:")
        for f in fails:
            print("   -", f)
        return 1
    print("\n✅ 通过: 主链只取 30° 网格峰值, yaw=150; 置信度口径未变, 阈值标定仍然有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
