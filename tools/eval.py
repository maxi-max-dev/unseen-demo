#!/usr/bin/env python3
"""
eval.py -- 拿 matches.json 对 assets/photos/ground_truth.json 打分。
明晚生死闸的量尺: 节点 Top-1 正确率 >= 70%, yaw 中位绝对误差 <= 35 度 (仅统计节点判对的样本)。

用法: python tools/eval.py [--matches matches.json] [--gt assets/photos/ground_truth.json]
"""
import argparse
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MATCHES = os.path.join(ROOT, "matches.json")
DEFAULT_GT = os.path.join(ROOT, "assets", "photos", "ground_truth.json")

NODE_ACC_GATE = 0.70
YAW_ERR_GATE = 35.0


def circular_abs_err(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", default=DEFAULT_MATCHES)
    ap.add_argument("--gt", default=DEFAULT_GT)
    args = ap.parse_args()

    matches = json.load(open(args.matches, encoding="utf-8"))
    gt = json.load(open(args.gt, encoding="utf-8"))
    gt_by_file = {g["file"]: g for g in gt}

    rows = []
    for m in matches:
        fname = os.path.basename(m["src"])
        g = gt_by_file.get(fname)
        if g is None:
            print(f"  WARN: {fname} 在 ground_truth.json 里找不到, 跳过")
            continue
        node_ok = (m["node"] == g["node"])
        yaw_err = circular_abs_err(m["yaw"], g["yaw"]) if node_ok else None
        rows.append({
            "file": fname,
            "pred_node": m["node"], "gt_node": g["node"], "node_ok": node_ok,
            "pred_yaw": m["yaw"], "gt_yaw": g["yaw"], "yaw_err": yaw_err,
            "confidence": m.get("confidence"), "ms": m.get("ms"),
        })

    n = len(rows)
    node_correct = sum(1 for r in rows if r["node_ok"])
    node_acc = node_correct / n if n else 0.0
    yaw_errs = [r["yaw_err"] for r in rows if r["node_ok"]]
    yaw_median = statistics.median(yaw_errs) if yaw_errs else float("nan")
    ms_list = [r["ms"] for r in rows if r.get("ms") is not None]

    print("== 逐张明细 ==")
    print(f"{'file':10s} {'gt_node':10s} {'pred_node':10s} {'ok':4s} {'gt_yaw':7s} {'pred_yaw':9s} {'yaw_err':8s} {'conf':6s} {'ms':6s}")
    for r in rows:
        yaw_err_s = f"{r['yaw_err']:.1f}" if r["yaw_err"] is not None else "-"
        print(f"{r['file']:10s} {r['gt_node']:10s} {r['pred_node']:10s} "
              f"{'Y' if r['node_ok'] else 'N':4s} {r['gt_yaw']:<7} {r['pred_yaw']:<9} "
              f"{yaw_err_s:8s} {r['confidence']:<6} {r['ms']:<6}")

    print("\n== 汇总 ==")
    print(f"样本数: {n}")
    print(f"节点 Top-1 正确率: {node_correct}/{n} = {node_acc*100:.1f}%  (闸门 >= {NODE_ACC_GATE*100:.0f}%)")
    if yaw_errs:
        print(f"yaw 中位绝对误差 (仅节点判对样本, n={len(yaw_errs)}): {yaw_median:.1f}°  (闸门 <= {YAW_ERR_GATE:.0f}°)")
        print(f"yaw 误差范围: min={min(yaw_errs):.1f}° max={max(yaw_errs):.1f}° mean={statistics.mean(yaw_errs):.1f}°")
    else:
        print("yaw 中位绝对误差: 无节点判对样本, 无法计算")
    if ms_list:
        print(f"每张耗时: median={statistics.median(ms_list):.0f}ms mean={statistics.mean(ms_list):.0f}ms "
              f"min={min(ms_list):.0f}ms max={max(ms_list):.0f}ms")

    node_pass = node_acc >= NODE_ACC_GATE
    yaw_pass = (yaw_median <= YAW_ERR_GATE) if yaw_errs else False
    print(f"\n节点正确率闸门: {'PASS' if node_pass else 'FAIL'}")
    print(f"yaw 误差闸门: {'PASS' if yaw_pass else 'FAIL'}")
    print(f"总闸门: {'PASS' if (node_pass and yaw_pass) else 'FAIL'}")


if __name__ == "__main__":
    main()
