#!/usr/bin/env python3
"""Deterministically import the authored AI wedding fixture as a local space.

This importer is intentionally narrower than the normal upload pipeline:

* the authoritative manifest already contains authored scene/photo angles;
* CLIP, DAP, worker startup, verification, and publishing are never invoked;
* the fixed staging SID is ``s900001``;
* an existing target is accepted only when it is the exact same fixture.

Run a read-only validation first:

    .venv/bin/python tools/import_ai_wedding_demo.py --manifest /path/to/manifest.json --check

Then create the local staging space:

    .venv/bin/python tools/import_ai_wedding_demo.py --manifest /path/to/manifest.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Any

import fcntl
from PIL import Image, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[1]
SPACES_ROOT = REPO_ROOT / "server" / "spaces"
SID = "s900001"
IMPORTER = "tools/import_ai_wedding_demo.py"
IMPORTER_SCHEMA = "psm-ai-wedding-import/1"
CONTENT_LABEL = "预置 AI 演示 · 已上传并定位"
FIXED_TIME = 0.0
THUMB_LONG_EDGE = 480


class ImportValidationError(RuntimeError):
    """A source or target failed a deterministic safety check."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImportValidationError(f"{label} 必须是有限数字")
    number = float(value)
    if not math.isfinite(number):
        raise ImportValidationError(f"{label} 必须是有限数字")
    return number


def normalized_yaw(value: Any, label: str) -> float | int:
    """Convert locator yaw to the spatial-memory coordinate convention."""
    converted = (finite_number(value, label) + 180.0) % 360.0
    rounded = round(converted, 6)
    return int(rounded) if rounded.is_integer() else rounded


def unchanged_number(value: Any, label: str) -> float | int:
    number = round(finite_number(value, label), 6)
    return int(number) if number.is_integer() else number


def load_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    if not path.is_file():
        raise ImportValidationError(f"权威 manifest 不存在: {path}")
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportValidationError(f"manifest 不是有效 UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ImportValidationError("manifest 顶层必须是对象")
    return manifest, raw


def ordered_records(
    records: Any,
    order: Any,
    *,
    label: str,
    fallback_key: str,
) -> list[dict[str, Any]]:
    if not isinstance(records, list) or not records:
        raise ImportValidationError(f"manifest.{label} 必须是非空数组")
    clean: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ImportValidationError(f"{label}[{index}] 必须是对象")
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            raise ImportValidationError(f"{label}[{index}].id 不能为空")
        if record_id in by_id:
            raise ImportValidationError(f"{label} 出现重复 id: {record_id}")
        by_id[record_id] = record
        clean.append(record)

    if order is not None:
        if not isinstance(order, list) or any(not isinstance(item, str) for item in order):
            raise ImportValidationError(f"navigation 中的 {label}Order 必须是字符串数组")
        if len(order) != len(set(order)):
            raise ImportValidationError(f"navigation 中的 {label}Order 有重复 id")
        if set(order) != set(by_id):
            raise ImportValidationError(
                f"navigation 中的 {label}Order 必须恰好覆盖全部 {label}"
            )
        return [by_id[record_id] for record_id in order]

    return sorted(
        clean,
        key=lambda record: (
            finite_number(record.get(fallback_key), f"{label}.{fallback_key}"),
            str(record["id"]),
        ),
    )


def resolve_asset(manifest_path: Path, raw_url: Any, label: str) -> Path:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ImportValidationError(f"{label} 必须是非空路径")
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ImportValidationError(f"{label} 只能是本地静态资源路径: {raw_url}")
    decoded = urllib.parse.unquote(parsed.path)
    posix = PurePosixPath(decoded)
    parts = tuple(part for part in posix.parts if part not in ("/", ""))
    if not parts or any(part in (".", "..") for part in parts):
        raise ImportValidationError(f"{label} 含不安全路径: {raw_url}")

    if decoded.startswith("/"):
        manifest_parent_parts = manifest_path.parent.parts
        # The manifest lives at e.g. public/experiences/wedding/manifest.json,
        # while an asset lives below a sibling directory such as
        # /experiences/wedding/panoramas/01.png.  Find the longest leading URL
        # prefix that is also the suffix of the manifest directory.
        shared_count = 0
        for count in range(len(parts) - 1, 0, -1):
            if tuple(manifest_parent_parts[-count:]) == parts[:count]:
                shared_count = count
                break
        if not shared_count:
            raise ImportValidationError(
                f"{label} 与 manifest 所在目录不匹配，无法确定静态根目录: {raw_url}"
            )
        public_root = manifest_path.parent
        for _ in range(shared_count):
            public_root = public_root.parent
        candidate = public_root.joinpath(*parts)
        allowed_root = public_root.resolve()
    else:
        candidate = manifest_path.parent.joinpath(*parts)
        allowed_root = manifest_path.parent.resolve()

    resolved = candidate.resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise ImportValidationError(f"{label} 越出静态资源目录: {raw_url}") from exc
    if not resolved.is_file():
        raise ImportValidationError(f"{label} 对应文件不存在: {resolved}")
    return resolved


def optional_expected_sha(record: dict[str, Any], label: str) -> str | None:
    value: Any = None
    for key in ("sha256", "checksumSha256"):
        if record.get(key) is not None:
            value = record[key]
            break
    checksum = record.get("checksum")
    if value is None and isinstance(checksum, dict):
        algorithm = str(checksum.get("algorithm") or "").lower().replace("-", "")
        if algorithm == "sha256":
            value = checksum.get("value")
    if value is None:
        return None
    value = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ImportValidationError(f"{label} 的 sha256 不是 64 位十六进制")
    return value


def optional_expected_dimensions(
    record: dict[str, Any], label: str
) -> tuple[int, int] | None:
    dimensions = record.get("dimensions")
    if isinstance(dimensions, dict):
        width, height = dimensions.get("width"), dimensions.get("height")
    else:
        width, height = record.get("width"), record.get("height")
    if width is None and height is None:
        return None
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise ImportValidationError(f"{label} 的 width/height 必须是正整数")
    return width, height


def inspect_image(
    path: Path,
    record: dict[str, Any],
    label: str,
    *,
    require_panorama: bool,
) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = str(image.format or "").upper()
    except Exception as exc:
        raise ImportValidationError(f"{label} 不是可解码图片: {path} ({exc})") from exc
    if width <= 0 or height <= 0:
        raise ImportValidationError(f"{label} 图片尺寸无效: {width}×{height}")
    if require_panorama and abs((width / float(height)) - 2.0) > 0.05:
        raise ImportValidationError(
            f"{label} 必须是 2:1 全景图，实际 {width}×{height}"
        )

    actual_sha = sha256_file(path)
    expected_sha = optional_expected_sha(record, label)
    if expected_sha and expected_sha != actual_sha:
        raise ImportValidationError(
            f"{label} sha256 不匹配: manifest={expected_sha} actual={actual_sha}"
        )
    expected_dimensions = optional_expected_dimensions(record, label)
    if expected_dimensions and expected_dimensions != (width, height):
        raise ImportValidationError(
            f"{label} 尺寸不匹配: manifest={expected_dimensions[0]}×"
            f"{expected_dimensions[1]} actual={width}×{height}"
        )
    return {
        "path": path,
        "sha256": actual_sha,
        "size": path.stat().st_size,
        "width": width,
        "height": height,
        "format": image_format,
    }


def thumbnail_bytes(path: Path) -> tuple[bytes, int, int]:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        width, height = image.size
    return output.getvalue(), width, height


def build_plan(manifest_path: Path) -> dict[str, Any]:
    if not re.fullmatch(r"s\d+", SID):
        raise ImportValidationError(f"固定 SID 不符合后端 s<数字> 契约: {SID}")
    manifest, manifest_raw = load_manifest(manifest_path)
    if str(manifest.get("angleUnit") or "") != "deg":
        raise ImportValidationError("manifest.angleUnit 必须是 deg")
    fixture_id = str(manifest.get("id") or "").strip()
    if not fixture_id:
        raise ImportValidationError("manifest.id 不能为空")

    navigation = manifest.get("navigation")
    navigation = navigation if isinstance(navigation, dict) else {}
    scenes = ordered_records(
        manifest.get("scenes"),
        navigation.get("sceneOrder"),
        label="scenes",
        fallback_key="order",
    )
    media = ordered_records(
        manifest.get("media"),
        navigation.get("mediaOrder"),
        label="media",
        fallback_key="sequence",
    )
    if len(scenes) != 4 or len(media) != 8:
        raise ImportValidationError(
            f"婚礼 fixture 必须正好是 4 个全景 / 8 张照片，实际 {len(scenes)} / {len(media)}"
        )

    scene_ids = {str(scene["id"]) for scene in scenes}
    initial_scene_id = str(manifest.get("initialSceneId") or "")
    if initial_scene_id not in scene_ids:
        raise ImportValidationError("manifest.initialSceneId 不在 scenes 中")

    manifest_sha = sha256_bytes(manifest_raw)
    disclosure = str(manifest.get("disclosure") or "").strip()
    if not disclosure:
        raise ImportValidationError("manifest.disclosure 不能为空，AI 演示必须明确声明")

    planned_files: list[dict[str, Any]] = []
    assets_by_url: dict[str, dict[str, Any]] = {}
    scene_to_node: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []

    for index, scene in enumerate(scenes, 1):
        scene_id = str(scene["id"])
        node_id = f"n{index}"
        scene_to_node[scene_id] = node_id
        source_url = scene.get("panoramaUrl")
        source_path = resolve_asset(
            manifest_path, source_url, f"scene {scene_id}.panoramaUrl"
        )
        inspected = inspect_image(
            source_path,
            scene,
            f"scene {scene_id}.panorama",
            require_panorama=True,
        )
        source_url = str(source_url)
        assets_by_url[source_url] = {
            key: inspected[key]
            for key in ("sha256", "size", "width", "height", "format")
        }
        suffix = source_path.suffix.lower()
        if suffix not in (".jpg", ".jpeg", ".png"):
            raise ImportValidationError(
                f"scene {scene_id} 全景格式不支持确定性复制: {suffix}"
            )
        destination = f"nodes/{node_id}/pano{suffix}"
        planned_files.append({
            "relative": destination,
            "data": source_path.read_bytes(),
            "source": source_url,
            "sha256": inspected["sha256"],
        })

        initial_view = scene.get("initialView")
        if not isinstance(initial_view, dict):
            raise ImportValidationError(f"scene {scene_id}.initialView 必须是对象")
        copy = scene.get("copy")
        copy = copy if isinstance(copy, dict) else {}
        node_name = str(copy.get("navTitle") or scene_id).strip()
        node_time = str(copy.get("navSubtitle") or "").strip()
        nodes.append({
            "id": node_id,
            "name": node_name,
            "time": node_time,
            "eyebrow": str(copy.get("eyebrow") or "").strip(),
            "title": str(copy.get("title") or "").strip(),
            "description": str(copy.get("description") or "").strip(),
            "panorama": destination,
            "depth": None,
            "depthJson": None,
            "initialYaw": normalized_yaw(
                initial_view.get("yawDeg"), f"scene {scene_id}.initialView.yawDeg"
            ),
            "initialPitch": unchanged_number(
                initial_view.get("pitchDeg", 0),
                f"scene {scene_id}.initialView.pitchDeg",
            ),
            "initialFov": unchanged_number(
                initial_view.get("fovDeg", manifest.get("defaultFovDeg", 64)),
                f"scene {scene_id}.initialView.fovDeg",
            ),
            "sourceSceneId": scene_id,
            "contentLabel": CONTENT_LABEL,
            "metadata": {
                "sourcePanoramaUrl": source_url,
                "sourceSha256": inspected["sha256"],
                "copy": copy,
            },
        })

    photos: list[dict[str, Any]] = []
    for index, item in enumerate(media, 1):
        media_id = str(item["id"])
        if item.get("kind") != "photo":
            raise ImportValidationError(f"media {media_id}.kind 必须是 photo")
        scene_id = str(item.get("sceneId") or "")
        if scene_id not in scene_to_node:
            raise ImportValidationError(f"media {media_id}.sceneId 不在 scenes 中")
        anchor = item.get("anchor")
        if not isinstance(anchor, dict):
            raise ImportValidationError(f"media {media_id}.anchor 必须是对象")

        source_url = item.get("src")
        source_path = resolve_asset(
            manifest_path, source_url, f"media {media_id}.src"
        )
        inspected = inspect_image(
            source_path,
            item,
            f"media {media_id}.photo",
            require_panorama=False,
        )
        source_url = str(source_url)
        assets_by_url[source_url] = {
            key: inspected[key]
            for key in ("sha256", "size", "width", "height", "format")
        }

        photo_id = f"p{index}"
        photo_destination = f"photos/{photo_id}.jpg"
        photo_data = source_path.read_bytes()
        planned_files.append({
            "relative": photo_destination,
            "data": photo_data,
            "source": source_url,
            "sha256": sha256_bytes(photo_data),
        })
        thumb_data, thumb_width, thumb_height = thumbnail_bytes(source_path)
        thumb_destination = f"thumbs/{photo_id}.jpg"
        planned_files.append({
            "relative": thumb_destination,
            "data": thumb_data,
            "source": source_url,
            "sha256": sha256_bytes(thumb_data),
        })

        source_yaw = unchanged_number(
            anchor.get("yawDeg"), f"media {media_id}.anchor.yawDeg"
        )
        pitch = unchanged_number(
            anchor.get("pitchDeg", 0), f"media {media_id}.anchor.pitchDeg"
        )
        photos.append({
            "id": photo_id,
            "src": photo_destination,
            "thumb": thumb_destination,
            "nodeId": scene_to_node[scene_id],
            "yaw": normalized_yaw(
                anchor.get("yawDeg"), f"media {media_id}.anchor.yawDeg"
            ),
            "pitch": pitch,
            "confidence": 1.0,
            "margin": 1.0,
            "state": "approved",
            "reason": (
                "预置 AI 演示：方位来自权威 manifest 的 authored anchor；"
                "未运行 CLIP，已批准用于 staging 展示"
            ),
            "contributor": "AI 演示素材",
            "taskId": None,
            "uploadedAt": float(index),
            "taskRewarded": None,
            "bountyPaid": False,
            "sourceMediaId": media_id,
            "sourceYaw": source_yaw,
            "localizationMethod": "authored",
            "approvalMethod": "fixture",
            "origin": str(item.get("origin") or "seed"),
            "title": str(item.get("title") or ""),
            "timeLabel": str(item.get("timeLabel") or ""),
            "contentLabel": CONTENT_LABEL,
            "metadata": {
                "sourcePhotoUrl": source_url,
                "sourceSha256": inspected["sha256"],
                "sourceDimensions": {
                    "width": inspected["width"],
                    "height": inspected["height"],
                },
                "thumbnailDimensions": {
                    "width": thumb_width,
                    "height": thumb_height,
                },
                "anchorFov": unchanged_number(
                    anchor.get("fovDeg", manifest.get("defaultFovDeg", 64)),
                    f"media {media_id}.anchor.fovDeg",
                ),
            },
        })

    managed_files = {
        item["relative"]: {
            "sha256": item["sha256"],
            "size": len(item["data"]),
            "source": item["source"],
        }
        for item in sorted(planned_files, key=lambda row: row["relative"])
    }
    initial_node_id = scene_to_node[initial_scene_id]
    space = {
        "schema": "psm-space/1",
        "id": SID,
        "title": str(manifest.get("title") or "庭间").strip() or "庭间",
        "couple": str(manifest.get("subtitle") or "").strip(),
        "subtitle": str(manifest.get("subtitle") or "").strip(),
        "date": "",
        "place": "",
        "cover": nodes[0]["panorama"],
        "private": False,
        "createdAt": FIXED_TIME,
        "published": False,
        "publishDirty": False,
        "publishRevision": 0,
        "_cloudPublishBlocked": True,
        "inboxGeneration": 1,
        "inboxPrefixVersion": 2,
        "_idHighWater": {"n": len(nodes), "p": len(photos), "t": 0},
        "collection": {"status": "closed", "updatedAt": FIXED_TIME},
        "exhibition": {
            "schema": "unseen-exhibition/1",
            "status": "draft",
            "revision": 0,
            "entryView": "walk",
            "views": ["walk", "photos"],
            "allowPov": True,
            "contributorVisibility": "hidden",
            "taskVisibility": "hidden",
            "updatedAt": FIXED_TIME,
        },
        "nodes": nodes,
        "tasks": [],
        "photos": photos,
        "contributors": [],
        "initialSceneId": initial_scene_id,
        "initialNodeId": initial_node_id,
        "demoDisclosure": disclosure,
        "aiDisclosure": disclosure,
        "contentLabel": CONTENT_LABEL,
        "metadata": {
            "schema": IMPORTER_SCHEMA,
            "fixtureId": fixture_id,
            "fixtureVersion": str(manifest.get("version") or ""),
            "fixtureMode": str(manifest.get("mode") or ""),
            "sourceManifest": "/experiences/wedding/manifest.json",
            "sourceManifestSha256": manifest_sha,
            "importer": IMPORTER,
            "aiGenerated": True,
            "localizationMethod": "authored",
            "angleTransform": "(sourceYawDeg + 180) % 360",
            "modelsRun": {"clip": False, "dap": False},
            "publishedByImporter": False,
            "assets": {
                key: assets_by_url[key] for key in sorted(assets_by_url)
            },
            "managedFiles": managed_files,
        },
    }
    space_json = (
        json.dumps(space, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return {
        "manifestPath": manifest_path,
        "manifestSha256": manifest_sha,
        "fixtureId": fixture_id,
        "space": space,
        "spaceJson": space_json,
        "files": sorted(planned_files, key=lambda row: row["relative"]),
    }


def inspect_existing(plan: dict[str, Any]) -> str:
    target = SPACES_ROOT / SID
    if not target.exists():
        return "absent"
    if not target.is_dir():
        raise ImportValidationError(f"目标已存在但不是目录: {target}")
    json_path = target / "space.json"
    if not json_path.is_file():
        raise ImportValidationError(
            f"拒绝覆盖 {target}：存在目录但没有可识别的 fixture space.json"
        )
    try:
        existing = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportValidationError(
            f"拒绝覆盖 {target}：现有 space.json 无法读取"
        ) from exc
    metadata = existing.get("metadata") if isinstance(existing, dict) else None
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema") != IMPORTER_SCHEMA
        or metadata.get("fixtureId") != plan["fixtureId"]
        or metadata.get("importer") != IMPORTER
    ):
        raise ImportValidationError(
            f"拒绝覆盖 {target}：它不是 {plan['fixtureId']} 的确定性 staging fixture"
        )
    if metadata.get("sourceManifestSha256") != plan["manifestSha256"]:
        raise ImportValidationError(
            "同一 fixture 的权威 manifest 已变化；请分配新 SID，不覆盖现有 staging"
        )
    # 导入后，主系统可以按正常后端流程为四个节点补 DAP 深度。它不是第二份
    # 内容源，也不应被重新导入抹掉；这里把“完整且自洽的 DAP 增强”识别为
    # 安全的 enriched 状态，其余任何字段变化仍然拒绝覆盖。
    comparable = copy.deepcopy(existing)
    expected_nodes = {
        node["id"]: node for node in plan["space"].get("nodes") or []
    }
    comparable_nodes = {
        node.get("id"): node for node in comparable.get("nodes") or []
        if isinstance(node, dict)
    }
    if set(comparable_nodes) != set(expected_nodes):
        raise ImportValidationError(
            f"拒绝覆盖 {target}：全景节点集合已被修改"
        )
    allowed_depth_files: set[str] = set()
    enriched_nodes = 0
    for node_id, node in comparable_nodes.items():
        depth = node.get("depth")
        depth_json = node.get("depthJson")
        if depth is None and depth_json is None:
            continue
        expected_depth = f"nodes/{node_id}/depth.png"
        expected_json = f"nodes/{node_id}/depth.json"
        if depth != expected_depth or depth_json != expected_json:
            raise ImportValidationError(
                f"拒绝覆盖 {target}：节点 {node_id} 的深度路径不符合标准空间契约"
            )
        depth_path = target / expected_depth
        json_path = target / expected_json
        if not depth_path.is_file() or not json_path.is_file():
            raise ImportValidationError(
                f"节点 {node_id} 声明了 DAP 深度，但文件不完整"
            )
        try:
            with Image.open(depth_path) as depth_image:
                depth_image.load()
                width, height = depth_image.size
                extrema = depth_image.getextrema()
            depth_meta = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ImportValidationError(
                f"节点 {node_id} 的 DAP 深度无法解码: {exc}"
            ) from exc
        if width != 1024 or height != 512 or not isinstance(extrema, tuple):
            raise ImportValidationError(
                f"节点 {node_id} 的 DAP 深度尺寸/像素无效: {width}×{height}"
            )
        if extrema[0] == extrema[1]:
            raise ImportValidationError(
                f"节点 {node_id} 的 DAP 深度全平，没有可用空间信息"
            )
        if (
            not isinstance(depth_meta, dict)
            or not isinstance(depth_meta.get("min"), (int, float))
            or not isinstance(depth_meta.get("max"), (int, float))
            or not float(depth_meta["min"]) < float(depth_meta["max"])
        ):
            raise ImportValidationError(
                f"节点 {node_id} 的 DAP depth.json 范围无效"
            )
        node["depth"] = None
        node["depthJson"] = None
        allowed_depth_files.update((expected_depth, expected_json))
        enriched_nodes += 1

    models_run = (comparable.get("metadata") or {}).get("modelsRun")
    if not isinstance(models_run, dict):
        raise ImportValidationError("现有 fixture 缺少 metadata.modelsRun")
    if enriched_nodes:
        if enriched_nodes != len(expected_nodes) or models_run.get("dap") is not True:
            raise ImportValidationError(
                "DAP 增强必须覆盖全部节点，并在 metadata.modelsRun.dap 标记为 true"
            )
        models_run["dap"] = False
    elif models_run.get("dap") is not False:
        raise ImportValidationError(
            "没有深度文件时 metadata.modelsRun.dap 必须为 false"
        )

    if comparable != plan["space"]:
        raise ImportValidationError(
            f"拒绝覆盖 {target}：同一 fixture 的非 DAP 字段已被修改"
        )

    expected_managed = {
        item["relative"]: item["sha256"] for item in plan["files"]
    }
    for relative, expected_sha in expected_managed.items():
        path = target / relative
        if not path.is_file():
            raise ImportValidationError(
                f"现有 fixture 不完整，缺少托管文件: {relative}"
            )
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            raise ImportValidationError(
                f"现有 fixture 文件已变化: {relative}"
            )

    actual_managed: set[str] = set()
    for managed_root in ("nodes", "photos", "thumbs", "tasks"):
        root = target / managed_root
        if root.exists():
            actual_managed.update(
                str(path.relative_to(target))
                for path in root.rglob("*")
                if path.is_file()
            )
    extras = actual_managed - set(expected_managed) - allowed_depth_files
    if extras:
        raise ImportValidationError(
            "现有 fixture 含非本导入器托管的素材，拒绝覆盖: "
            + ", ".join(sorted(extras)[:8])
        )
    return "enriched" if enriched_nodes else "exact"


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def create_target(plan: dict[str, Any]) -> str:
    SPACES_ROOT.mkdir(parents=True, exist_ok=True)
    lock_path = SPACES_ROOT / ".space-txn.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            existing_state = inspect_existing(plan)
            if existing_state in ("exact", "enriched"):
                return "already-" + existing_state

            temp_path = Path(
                tempfile.mkdtemp(prefix=f".{SID}-import-", dir=SPACES_ROOT)
            )
            try:
                for directory in ("nodes", "photos", "thumbs", "tasks"):
                    (temp_path / directory).mkdir(parents=True, exist_ok=True)
                for item in plan["files"]:
                    write_bytes(temp_path / item["relative"], item["data"])
                write_bytes(temp_path / "space.json", plan["spaceJson"])
                os.rename(temp_path, SPACES_ROOT / SID)
                directory_fd = os.open(SPACES_ROOT, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temp_path.exists():
                    shutil.rmtree(temp_path)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return "created"


def summary(plan: dict[str, Any], mode: str, target_state: str) -> dict[str, Any]:
    space = plan["space"]
    models_run = dict(space["metadata"]["modelsRun"])
    if target_state.endswith("enriched"):
        models_run["dap"] = True
    return {
        "ok": True,
        "mode": mode,
        "targetState": target_state,
        "sid": SID,
        "fixtureId": plan["fixtureId"],
        "manifest": str(plan["manifestPath"]),
        "manifestSha256": plan["manifestSha256"],
        "nodes": len(space["nodes"]),
        "photos": len(space["photos"]),
        "photoStates": sorted({photo["state"] for photo in space["photos"]}),
        "collection": space["collection"]["status"],
        "exhibition": space["exhibition"],
        "initialNodeId": space["initialNodeId"],
        "initialYawByNode": {
            node["id"]: node["initialYaw"] for node in space["nodes"]
        },
        "yawByPhoto": {
            photo["id"]: photo["yaw"] for photo in space["photos"]
        },
        "contentLabel": space["contentLabel"],
        "modelsRun": models_run,
        "published": space["published"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="确定性导入 AI 婚礼 staging space（固定 SID=s900001）"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="权威 manifest 的本地路径",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验来源和目标，不写 server/spaces",
    )
    args = parser.parse_args(argv)

    try:
        plan = build_plan(args.manifest.expanduser().resolve())
        if args.check:
            state = inspect_existing(plan)
            print(json.dumps(summary(plan, "check", state), ensure_ascii=False, indent=2))
            return 0
        state = create_target(plan)
        print(json.dumps(summary(plan, "import", state), ensure_ascii=False, indent=2))
        return 0
    except ImportValidationError as exc:
        print(
            json.dumps(
                {"ok": False, "sid": SID, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
