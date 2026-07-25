#!/usr/bin/env python3
"""用照片已落盘的真值回填历史 needs_review 文案。

默认只预览；传 --apply 才写回。只改 reason，不改照片状态、分数或判据。
阈值从 server/space.py 的默认值读取，并尊重同名环境变量。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPACE_PY = ROOT / "server" / "space.py"
SPACES = ROOT / "server" / "spaces"


def threshold(name: str) -> float:
    source = SPACE_PY.read_text(encoding="utf-8")
    match = re.search(
        rf'^{name}\s*=\s*float\(os\.environ\.get\("[^"]+",\s*"([0-9.]+)"\)\)',
        source,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"在 server/space.py 里找不到 {name} 默认值")
    env_name = "PSM_CONF_MIN" if name == "CONF_MIN" else "PSM_MARGIN_MIN"
    return float(os.environ.get(env_name, match.group(1)))


def review_reason(confidence: float, margin: float, conf_min: float, margin_min: float) -> str:
    if confidence < conf_min and margin < margin_min:
        return (
            f"匹配度 {confidence:.4f} 偏低(门槛 {conf_min:.4f}),"
            f"辨识度 {margin:.4f} 也偏低(门槛 {margin_min:.4f}),"
            "这张很可能不是在这个空间拍的,请你看一眼"
        )
    if margin < margin_min:
        return (
            f"匹配度 {confidence:.4f} 够高,但辨识度只有 {margin:.4f}"
            f"(低于门槛 {margin_min:.4f}):"
            "它跟这个空间哪个方向都差不多像,机器拿不准是不是这儿拍的"
        )
    return (
        f"辨识度 {margin:.4f} 够,但匹配度只有 {confidence:.4f}"
        f"(低于门槛 {conf_min:.4f}),方位可能不准,请你看一眼"
    )


def atomic_write(path: Path, data: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="原子写回 space.json")
    args = parser.parse_args()

    conf_min = threshold("CONF_MIN")
    margin_min = threshold("MARGIN_MIN")
    changes: list[tuple[Path, str, str, str]] = []
    changed_files: dict[Path, dict] = {}

    for path in sorted(SPACES.glob("*/space.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"跳过 {path.relative_to(ROOT)}: {exc}")
            continue
        touched = False
        for photo in data.get("photos", []):
            if photo.get("state") != "needs_review":
                continue
            confidence = photo.get("confidence")
            margin = photo.get("margin")
            if not isinstance(confidence, (int, float)) or not isinstance(margin, (int, float)):
                continue
            expected = review_reason(float(confidence), float(margin), conf_min, margin_min)
            old = str(photo.get("reason") or "")
            if old == expected:
                continue
            changes.append((path, str(photo.get("id") or ""), old, expected))
            photo["reason"] = expected
            touched = True
        if touched:
            changed_files[path] = data

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"{mode}: {len(changes)} 条, {len(changed_files)} 个空间, "
        f"CONF_MIN={conf_min:.4f}, MARGIN_MIN={margin_min:.4f}"
    )
    for path, photo_id, old, new in changes:
        rel = path.relative_to(ROOT)
        print(f"{rel} {photo_id}\n  旧: {old}\n  新: {new}")

    if args.apply:
        for path, data in changed_files.items():
            atomic_write(path, data)
        print(f"已写回 {len(changed_files)} 个 space.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
