#!/usr/bin/env python3
"""
tools/depth.py — run Insta360 Research's DAP (Depth Any Panoramas) model on
one or more equirectangular panorama images and dump per-image depth maps.

Usage:
    .venv-dap/bin/python tools/depth.py <img1.jpg> [<img2.jpg> ...]

For every input <path>/<basename>.<ext> this writes two files into
assets/depth/:
    <basename>.png   16-bit grayscale depth, values 0-65535, linearly
                      rescaled from the model's raw per-image [min, max]
                      float range. Near = small value, far = large value.
    <basename>.json   {"min": <float>, "max": <float>, "width": <int>,
                        "height": <int>, "model": "DAP",
                        "convention": "near_small"}
                       min/max are the *raw* model output range (before
                       the 0-65535 rescale) for that image, so the PNG can
                       be de-normalized back to the model's native units.

Notes on the model's output (see vendor/DAP/networks/dap.py and
vendor/DAP/depth_anything_v2_metric/depth_anything_v2/dpt.py):
  - DPTHead ends in a Sigmoid, so DepthAnythingV2.forward() returns values
    in [0, 1] before DAP multiplies by config max_depth (1.0 in
    config/infer.yaml). Net result: raw model output is bounded to [0, 1]
    per pixel. It is NOT metric meters — it's a bounded relative depth
    regression. DAP's own test/infer.py visualizer treats the raw value as
    "fraction of a 100m range" (see pred_to_vis(..., vis_range="100m")),
    which is a labeling convention from their training normalization, not
    a verified metric calibration. We report the model's raw min/max as-is
    and do not claim metric accuracy.
  - depth2point.py builds the equirect point cloud as `depth * direction`,
    i.e. larger value = farther along the viewing ray -> convention is
    already "near_small" (small=near, large=far), matching what this repo
    wants, so no inversion is applied.

This script mirrors the preprocessing used by vendor/DAP/test/infer.py's
infer_raw(): image is normalized to [0,1] float (NO ImageNet mean/std
normalization — that's only used by the separate DAP.infer_image() helper,
which we deliberately do NOT use, to stay faithful to the repo's documented
CLI entry point, test/infer.py). Since infer.py itself does not resize
input images (it assumes pre-sized 512x1024 dataset frames), and our
source images are much larger, we explicitly resize each input to
1024x512 (config/infer.yaml's declared input size) before inference. This
also keeps memory/compute bounded on a laptop GPU and conveniently already
matches the "downscale output to width 1024" requirement, since the
model's DPT head upsamples its prediction back to exactly the input
resolution (see DepthAnythingV2.forward in dpt.py) — no separate output
resize step is needed.
"""
import argparse
import json
import os
import resource
import sys
import time

# Must be set before torch is imported: lets ops DAP/DINOv3 don't support
# on the MPS backend silently fall back to CPU instead of hard-erroring.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DAP_ROOT = os.path.join(REPO_ROOT, "vendor", "DAP")
WEIGHTS_PATH = os.path.join(DAP_ROOT, "weights", "model.pth")
DEPTH_OUT_DIR = os.path.join(REPO_ROOT, "assets", "depth")

INFER_WIDTH = 1024
INFER_HEIGHT = 512

MODEL_ARGS = {
    "name": "dap",
    "args": {
        "midas_model_type": "vitl",
        "fine_tune_type": "hypersim",
        "min_depth": 0.01,
        "max_depth": 1.0,
        "train_decoder": True,
    },
}


def _peak_rss_mb() -> float:
    """Peak resident set size of this process so far, in MB.
    macOS ru_maxrss is bytes; Linux is KB. We only run on macOS here."""
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return ru / (1024 * 1024)
    return ru / 1024


def load_model():
    """Build the DAP model and load the checkpoint. Must run with CWD set
    to DAP_ROOT because DINOv3Adapter's torch.hub.load(repo_dir=...,
    source="local") resolves repo_dir relative to CWD, not to this file."""
    if not os.path.isfile(WEIGHTS_PATH):
        raise FileNotFoundError(
            f"DAP weights not found at {WEIGHTS_PATH}. Download "
            f"model.pth from https://huggingface.co/Insta360-Research/DAP-weights first."
        )

    prev_cwd = os.getcwd()
    os.chdir(DAP_ROOT)
    try:
        sys.path.insert(0, DAP_ROOT)
        from networks.models import make  # noqa: WPS433 (local import by design)

        model = make(MODEL_ARGS)

        state = torch.load(WEIGHTS_PATH, map_location="cpu")
        if any(k.startswith("module") for k in state.keys()):
            model = nn.DataParallel(model)
        model_state = model.state_dict()
        matched = {k: v for k, v in state.items() if k in model_state}
        missing = len(model_state) - len(matched)
        if missing:
            print(f"warning: {missing}/{len(model_state)} checkpoint keys unmatched", file=sys.stderr)
        model.load_state_dict(matched, strict=False)
        model.eval()
    finally:
        os.chdir(prev_cwd)

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    try:
        model = model.to(device)
    except Exception as exc:  # pragma: no cover - defensive fallback
        print(f"warning: could not move model to {device} ({exc}), using cpu", file=sys.stderr)
        model = model.to("cpu")
        device = "cpu"

    return model, device


def infer_depth(model, device, img_rgb_u8: np.ndarray) -> np.ndarray:
    """Faithful port of vendor/DAP/test/infer.py's infer_raw(): float32
    /255 normalize, CHW, batch of 1, forward, apply predicted mask (mask==
    background -> depth forced to 1.0), return HxW float32."""
    img = img_rgb_u8.astype(np.float32) / 255.0
    tensor = torch.from_numpy(img.transpose(2, 0, 1)).unsqueeze(0).to(device)

    with torch.inference_mode():
        outputs = model(tensor)
        if isinstance(outputs, dict) and "pred_depth" in outputs:
            if "pred_mask" in outputs:
                mask = 1 - outputs["pred_mask"]
                mask = mask > 0.5
                outputs["pred_depth"][~mask] = 1
            pred = outputs["pred_depth"][0].detach().cpu().squeeze().numpy()
        else:
            pred = outputs[0].detach().cpu().squeeze().numpy()

    return pred.astype(np.float32)


def process_image(model, device, img_path: str) -> dict:
    basename = os.path.splitext(os.path.basename(img_path))[0]
    t0 = time.time()

    img_bgr = cv2.imread(img_path, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise FileNotFoundError(f"cannot read image: {img_path}")
    orig_h, orig_w = img_bgr.shape[:2]

    img_bgr_small = cv2.resize(
        img_bgr, (INFER_WIDTH, INFER_HEIGHT), interpolation=cv2.INTER_AREA
    )
    img_rgb = cv2.cvtColor(img_bgr_small, cv2.COLOR_BGR2RGB)

    pred = infer_depth(model, device, img_rgb)

    d_min = float(pred.min())
    d_max = float(pred.max())
    if d_max > d_min:
        norm = (pred - d_min) / (d_max - d_min)
    else:
        norm = np.zeros_like(pred)
    depth_u16 = np.clip(norm * 65535.0, 0, 65535).astype(np.uint16)

    os.makedirs(DEPTH_OUT_DIR, exist_ok=True)
    png_path = os.path.join(DEPTH_OUT_DIR, f"{basename}.png")
    json_path = os.path.join(DEPTH_OUT_DIR, f"{basename}.json")

    cv2.imwrite(png_path, depth_u16)
    meta = {
        "min": d_min,
        "max": d_max,
        "width": int(pred.shape[1]),
        "height": int(pred.shape[0]),
        "model": "DAP",
        "convention": "near_small",
        "source_image": os.path.relpath(img_path, REPO_ROOT),
        "source_resolution": [orig_w, orig_h],
        "device": device,
    }
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)

    elapsed = time.time() - t0
    return {
        "basename": basename,
        "elapsed_s": elapsed,
        "min": d_min,
        "max": d_max,
        "png": png_path,
        "json": json_path,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", nargs="+", help="paths to equirectangular panorama images")
    args = parser.parse_args()

    print(f"loading DAP model (weights: {WEIGHTS_PATH}) ...")
    t0 = time.time()
    model, device = load_model()
    print(f"model ready in {time.time() - t0:.1f}s, device={device}")

    results = []
    total_t0 = time.time()
    for img_path in args.images:
        img_path = os.path.abspath(img_path)
        print(f"\n-- {img_path}")
        r = process_image(model, device, img_path)
        results.append(r)
        print(
            f"   done in {r['elapsed_s']:.2f}s  raw_depth_min={r['min']:.6f}  "
            f"raw_depth_max={r['max']:.6f}  peak_rss={_peak_rss_mb():.0f}MB"
        )

    total_elapsed = time.time() - total_t0
    print(f"\n{len(results)} image(s) processed in {total_elapsed:.2f}s total "
          f"(device={device}, peak_rss={_peak_rss_mb():.0f}MB)")


if __name__ == "__main__":
    main()
