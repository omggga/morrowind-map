from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.openmw_renderer.production import (
    DATASET_ID,
    MIN_ZOOM,
    NATIVE_ZOOM,
    OPENMW_COMMIT,
    POISON_WORLD_EXTENT,
    PRODUCTION_RENDERER_VERSION,
    SNAPSHOT_ID,
    TILE_PIXELS,
    TileKey,
    _shard_center,
    _verified_provenance_fingerprint,
    cell_for_native_tile,
    native_tile_for_cell,
    plan_report,
)


COVERAGE_SCHEMA_VERSION = 1
MAP_ASSETS_SCHEMA_VERSION = 1
MAX_ZOOM = NATIVE_ZOOM
TILE_PYRAMID_ID = "poison-song-26.08.basemap"
TILE_REGIONS = ("vvardenfell", "solstheim", "tr-mainland")
TILE_RESOLUTIONS = (2048, 1024, 512, 256, 128, 64, 32, 16)
EXPECTED_TILE_COUNTS = {0: 1, 1: 4, 2: 9, 3: 25, 4: 87, 5: 296, 6: 1058, 7: 3984}
EXPECTED_FINAL_SEAM_THRESHOLDS = {
    "pairMeanExcessMax": 8.0,
    "hardPixelDelta": 32,
    "pairHardFractionMax": 0.1,
    "crossMeanMargin": 0.5,
    "crossP95Margin": 2.0,
    "absoluteMeanMax": 4.0,
    "absoluteP95Max": 8.0,
    "absoluteFlaggedFractionMax": 0.01,
    "absolutePairMeanMax": 32.0,
    "crossShardP99PixelExcessMax": 8,
    "crossShardMaximumPixelExcessMax": 32,
    "crossShardHardPixelFractionMax": 0.01,
}
EXPECTED_RAW_THRESHOLDS = {
    "overlapMeanDeltaMax": 0.5,
    "overlapP99DeltaMax": 8,
    "overlapHardPixelDelta": 8,
    "overlapHardFractionMax": 0.01,
    "overlapAlphaDifferingFractionMax": 0.02,
    "overlapMaximumOpaqueDeltaMax": 32,
    "overlapLargestHardComponentPixelsMax": 16,
    "repeatDifferingFractionMax": 0.03,
    "repeatMeanDeltaMax": 0.1,
    "repeatP99DeltaMax": 8,
    "repeatHardPixelDelta": 8,
    "repeatHardFractionMax": 0.01,
    "repeatAlphaDifferingFractionMax": 0.02,
    "repeatOpaqueDifferingPixelsMax": 0,
    "releaseMeanExcessMax": 8.0,
    "releaseP99PixelExcessMax": 8,
    "releaseMaximumPixelExcessMax": 32,
    "releaseHardPixelFractionMax": 0.01,
}
PINNED_RAW_PROBE_IDS = (
    "7/5/14:east:7/6/14",
    "7/34/80:north:7/34/79",
)
EXPECTED_PLAN_FINGERPRINT = "f291d795804b723b788ccfa16b39fa5af3a987af14c0122fb268b0d2f535e57d"
DEFAULT_PUBLIC_ROOT = Path("apps/web/public/datasets/generated")
DEFAULT_RELEASE_OUTPUT = Path("local-data/openmw-release") / DATASET_ID
DEFAULT_METADATA_ROOT = (
    Path("apps/web/public/datasets/metadata") / DATASET_ID
)
QUALITY_REPORT_RELATIVE_PATH = Path("quality-audit/report.json")
PUBLISHED_QUALITY_REPORT_NAME = "basemap-audit.json"
EXPECTED_AUDIT_VERSION = "poison-basemap-quality-binary-alpha-v3"
EXPECTED_AUDIT_SCHEMA_VERSION = 2
LEGACY_AUDIT_VERSION = "poison-basemap-quality-v2"
LEGACY_AUDIT_SCHEMA_VERSION = 1
LEGACY_AUDIT_IMPLEMENTATION_SHA256 = (
    "7f7e5704dc52110a0dcf76289bc3ebf2eeb59c64876442f621dcce501b3184ce"
)
LEGACY_GRADE_VERSION = "mim-muted-v1"
LEGACY_PRODUCTION_RENDERER_VERSION = "openmw-export-production-v1"
V4_PRESENTATION = {
    "gradeVersion": "mim-opaque-v4",
    "alphaMode": "binary-nonzero",
    "colorGrade": "baked",
}
STABILIZATION_RECEIPT_PATH = Path("seam-stabilization.json")
SOURCE_INVENTORY_PATH = Path("seam-stabilization/source-inventory.json")
TILE_TRANSFORMS_PATH = Path("seam-stabilization/tile-transforms.ndjson")
EXPECTED_QUALITY_SCOPE = {
    "tiles": 5464,
    "nativeTiles": 3984,
    "lowerZoomTiles": 1480,
    "shards": 492,
    "allFinalAdjacencies": 10467,
    "nativeAdjacencies": 7729,
    "nativeCrossShardAdjacencies": 2571,
    "rawCrossShardProbes": 16,
}
MANDATORY_QUALITY_GATES = {
    "inventory",
    "seamStabilization",
    "stateAndMigrations",
    "pyramidDerivation",
    "finalSeams",
    "runtimeResourcesCoordinates",
    "rawProbes",
}
QUALITY_REPORT_KEYS = {
    "schemaVersion",
    "datasetId",
    "snapshotId",
    "auditVersion",
    "identity",
    "scope",
    "gates",
    "artifacts",
    "contactSheet",
    "limitations",
    "passes",
    "auditSha256",
}
QUALITY_IDENTITY_KEYS = {
    "inventorySha256",
    "inventoryFileSha256",
    "provenanceFileSha256",
    "planFileSha256",
    "provenanceFingerprint",
    "planFingerprint",
    "profileFingerprint",
    "rendererFingerprint",
    "productionSourceFingerprint",
    "assetTreeFingerprint",
    "inputFingerprint",
    "stabilizationFingerprint",
    "stabilizationReceiptSha256",
    "stabilizationReceiptFileSha256",
    "stabilizerImplementationSha256",
    "sourceInventorySha256",
    "auditImplementationSha256",
}
QUALITY_DETAIL_ARTIFACTS = {
    "tiles",
    "seams",
    "resourceRuntime",
    "worstSeams",
    "seamStabilization",
    "rawRendererProvenance",
}

ProgressCallback = Callable[[str], None]
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ValidatedInventory:
    payload: dict[str, Any]
    inventory_sha256: str
    inventory_file_sha256: str
    provenance_file_sha256: str
    plan_file_sha256: str
    tile_count: int
    total_bytes: int
    tile_entries: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]
    provenance_fingerprint: str
    plan_fingerprint: str
    profile_fingerprint: str
    renderer_fingerprint: str
    production_source_fingerprint: str
    asset_tree_fingerprint: str
    input_fingerprint: str
    source_scope: dict[str, int]


@dataclass(frozen=True, slots=True)
class QualityReportArtifact:
    path: Path
    sha256: str
    byte_length: int
    audit_sha256: str


@dataclass(frozen=True, slots=True)
class PublishMetadata:
    coverage: dict[str, Any]
    map_assets: dict[str, Any]
    quality_report: QualityReportArtifact
    stabilization_receipt: Path
    stabilization_support: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class PrepareResult:
    target_root: Path
    metadata_root: Path
    inventory_sha256: str
    tile_count: int
    total_bytes: int
    created: bool
    copy_method: str


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_file_bytes(value: object) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_publication_provenance(value: Mapping[str, Any]) -> str:
    if value.get("schemaVersion") != 1 or "presentation" in value:
        return _verified_provenance_fingerprint(value)
    image = value.get("image")
    if not isinstance(image, dict):
        raise ValueError("Legacy provenance image must be an object")
    profile = value.get("profileFingerprint")
    source = value.get("productionSourceFingerprint")
    image_id = image.get("id")
    digests = image.get("repoDigests")
    magick = value.get("magickVersion")
    if (
        not isinstance(profile, str)
        or _SHA256.fullmatch(profile) is None
        or not isinstance(source, str)
        or _SHA256.fullmatch(source) is None
        or not isinstance(image_id, str)
        or not isinstance(digests, list)
        or not all(isinstance(item, str) for item in digests)
        or not isinstance(magick, str)
        or not magick
        or value.get("rendererVersion") != LEGACY_PRODUCTION_RENDERER_VERSION
    ):
        raise ValueError("Legacy provenance fingerprint inputs are malformed")
    fingerprint = _sha256_bytes(
        _canonical_json_bytes(
            {
                "datasetId": DATASET_ID,
                "snapshotId": SNAPSHOT_ID,
                "rendererVersion": LEGACY_PRODUCTION_RENDERER_VERSION,
                "profileFingerprint": profile,
                "productionSourceFingerprint": source,
                "openmwCommit": OPENMW_COMMIT,
                "imageId": image_id,
                "imageRepoDigests": sorted(set(digests)),
                "gradeVersion": LEGACY_GRADE_VERSION,
                "magickVersion": magick,
            }
        )
    )
    if value.get("provenanceFingerprint") != fingerprint:
        raise ValueError("Legacy provenance fingerprint does not recompute")
    return fingerprint


def _read_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    payload = path.read_bytes()
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value, payload


def _fingerprint(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be an exact lowercase SHA-256")
    return value


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _tile_coordinates(entry: Mapping[str, object]) -> tuple[int, int, int]:
    result: list[int] = []
    for key in ("z", "x", "y"):
        value = entry.get(key)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError(f"Inventory tile {key} must be a non-negative integer")
        result.append(value)
    z, x, y = result
    if z < MIN_ZOOM or z > MAX_ZOOM:
        raise ValueError(f"Inventory tile zoom is outside {MIN_ZOOM}..{MAX_ZOOM}")
    return z, x, y


def _validated_tile_entries(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("Inventory tiles must be a non-empty array")
    entries: list[dict[str, Any]] = []
    seen_coordinates: set[tuple[int, int, int]] = set()
    seen_paths: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Every inventory tile must be an object")
        z, x, y = _tile_coordinates(raw)
        coordinates = (z, x, y)
        if coordinates in seen_coordinates:
            raise ValueError(f"Duplicate inventory tile coordinates: {coordinates}")
        expected_path = f"tiles/{z}/{x}/{y}.webp"
        path = raw.get("path")
        if path != expected_path:
            raise ValueError(
                f"Inventory tile path mismatch: expected {expected_path!r}, got {path!r}"
            )
        if path in seen_paths:
            raise ValueError(f"Duplicate inventory tile path: {path}")
        byte_length = _positive_integer(raw.get("bytes"), f"Tile {path} bytes")
        digest = _fingerprint(raw.get("sha256"), f"Tile {path} sha256")
        entries.append(
            {
                "z": z,
                "x": x,
                "y": y,
                "path": path,
                "bytes": byte_length,
                "sha256": digest,
            }
        )
        seen_coordinates.add(coordinates)
        seen_paths.add(path)
    if entries != sorted(entries, key=lambda item: (item["z"], item["x"], item["y"])):
        raise ValueError("Inventory tiles must be sorted by z, x, y")
    return tuple(entries)


def _validate_pinned_tile_topology(
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    by_zoom: dict[int, set[tuple[int, int]]] = defaultdict(set)
    min_x, min_y, max_x, max_y = POISON_WORLD_EXTENT
    for entry in entries:
        z, x, y = _tile_coordinates(entry)
        resolution = TILE_RESOLUTIONS[z]
        world_tile = TILE_PIXELS * resolution
        columns = math.ceil((max_x - min_x) / world_tile)
        rows = math.ceil((max_y - min_y) / world_tile)
        if x >= columns or y >= rows:
            raise ValueError(f"Inventory tile is outside the pinned grid: {(z, x, y)}")
        by_zoom[z].add((x, y))
    counts = {zoom: len(by_zoom.get(zoom, set())) for zoom in range(MAX_ZOOM + 1)}
    if counts != EXPECTED_TILE_COUNTS:
        raise ValueError(f"Inventory zoom topology count mismatch: {counts}")
    for zoom in range(MAX_ZOOM):
        expected_parents = {(x // 2, y // 2) for x, y in by_zoom[zoom + 1]}
        if by_zoom[zoom] != expected_parents:
            raise ValueError(f"Inventory sparse parent topology mismatch at z{zoom}")

    all_adjacencies = 0
    native_adjacencies = 0
    native_cross_shard = 0
    for zoom, tiles in by_zoom.items():
        for x, y in tiles:
            for neighbor in ((x + 1, y), (x, y - 1)):
                if neighbor not in tiles:
                    continue
                all_adjacencies += 1
                if zoom != NATIVE_ZOOM:
                    continue
                native_adjacencies += 1
                first = TileKey(zoom, x, y)
                second = TileKey(zoom, neighbor[0], neighbor[1])
                if _shard_center(cell_for_native_tile(first)) != _shard_center(
                    cell_for_native_tile(second)
                ):
                    native_cross_shard += 1
    scope = {
        "tiles": len(entries),
        "nativeTiles": counts[NATIVE_ZOOM],
        "lowerZoomTiles": len(entries) - counts[NATIVE_ZOOM],
        "allFinalAdjacencies": all_adjacencies,
        "nativeAdjacencies": native_adjacencies,
        "nativeCrossShardAdjacencies": native_cross_shard,
    }
    for key, actual in scope.items():
        if EXPECTED_QUALITY_SCOPE.get(key) != actual:
            raise ValueError(
                f"Inventory {key} does not match the pinned quality scope: {actual}"
            )
    return scope


def _validate_tile_tree(
    root: Path,
    entries: Sequence[Mapping[str, Any]],
    *,
    progress: ProgressCallback | None = None,
) -> None:
    tile_root = root / "tiles"
    if not tile_root.is_dir() or tile_root.is_symlink():
        raise FileNotFoundError(f"Tile directory is missing or unsafe: {tile_root}")
    expected = {str(entry["path"]) for entry in entries}
    actual: set[str] = set()
    for path in tile_root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Published tile tree cannot contain symlinks: {path}")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={missing[:5]!r}")
        if extra:
            details.append(f"extra={extra[:5]!r}")
        raise ValueError("Tile tree does not match inventory: " + ", ".join(details))
    total = len(entries)
    for index, entry in enumerate(entries, start=1):
        path = root / str(entry["path"])
        stat = path.stat()
        if stat.st_size != entry["bytes"]:
            raise ValueError(f"Tile byte length mismatch: {path}")
        if _sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Tile SHA-256 mismatch: {path}")
        if progress is not None and (index == total or index % 100 == 0):
            progress(f"validated tiles [{index}/{total}]")


def _validate_identity(
    value: Mapping[str, Any],
    *,
    label: str,
    inventory: Mapping[str, Any],
) -> None:
    for key in ("datasetId", "snapshotId"):
        if value.get(key) != inventory[key]:
            raise ValueError(f"{label} {key} does not match inventory")


def validate_source(
    source_root: Path,
    *,
    progress: ProgressCallback | None = None,
) -> ValidatedInventory:
    source_root = source_root.resolve()
    inventory_path = source_root / "inventory.json"
    inventory, inventory_bytes = _read_json_object(inventory_path, "Tile inventory")
    expected_identity = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "tileFormat": "image/webp",
        "tilePixels": TILE_PIXELS,
        "minZoom": MIN_ZOOM,
        "maxZoom": MAX_ZOOM,
        "extent": list(POISON_WORLD_EXTENT),
        "origin": [-229376.0, 278528.0],
    }
    for key, expected in expected_identity.items():
        if inventory.get(key) != expected:
            raise ValueError(
                f"Inventory {key} mismatch: expected {expected!r}, got {inventory.get(key)!r}"
            )
    entries = _validated_tile_entries(inventory.get("tiles"))
    source_scope = _validate_pinned_tile_topology(entries)
    tile_count = _positive_integer(inventory.get("tileCount"), "Inventory tileCount")
    total_bytes = _positive_integer(inventory.get("totalBytes"), "Inventory totalBytes")
    if tile_count != len(entries):
        raise ValueError("Inventory tileCount does not match tiles")
    if total_bytes != sum(int(entry["bytes"]) for entry in entries):
        raise ValueError("Inventory totalBytes does not match tiles")
    logical_sha256 = _fingerprint(
        inventory.get("inventorySha256"), "Inventory inventorySha256"
    )
    core = {key: value for key, value in inventory.items() if key != "inventorySha256"}
    if _sha256_bytes(_canonical_json_bytes(core)) != logical_sha256:
        raise ValueError("Inventory logical SHA-256 does not match its payload")
    provenance_fingerprint = _fingerprint(
        inventory.get("provenanceFingerprint"), "Inventory provenanceFingerprint"
    )
    plan_fingerprint = _fingerprint(
        inventory.get("planFingerprint"), "Inventory planFingerprint"
    )
    if plan_fingerprint != EXPECTED_PLAN_FINGERPRINT:
        raise ValueError("Inventory planFingerprint does not match the pinned Poison plan")

    provenance, provenance_bytes = _read_json_object(
        source_root / "provenance.json", "Provenance"
    )
    _validate_identity(provenance, label="Provenance", inventory=inventory)
    if _verified_publication_provenance(provenance) != provenance_fingerprint:
        raise ValueError("Provenance fingerprint does not match inventory")
    if provenance.get("openmwCommit") != OPENMW_COMMIT:
        raise ValueError("Provenance OpenMW commit does not match the pinned renderer")
    profile_fingerprint = _fingerprint(
        provenance.get("profileFingerprint"), "Provenance profileFingerprint"
    )
    production_source_fingerprint = _fingerprint(
        provenance.get("productionSourceFingerprint"),
        "Provenance productionSourceFingerprint",
    )
    image = provenance.get("image")
    if not isinstance(image, dict) or not isinstance(image.get("labels"), dict):
        raise ValueError("Provenance image labels are missing")
    renderer_fingerprint = _fingerprint(
        image["labels"].get("io.morrowind-map.renderer-fingerprint"),
        "Provenance rendererFingerprint",
    )
    asset_audit = provenance.get("assetAudit")
    input_audit = provenance.get("inputAudit")
    if not isinstance(asset_audit, dict) or not isinstance(input_audit, dict):
        raise ValueError("Provenance asset/input audit is malformed")
    asset_tree_fingerprint = _sha256_bytes(_canonical_json_bytes(asset_audit))
    input_fingerprint = _sha256_bytes(_canonical_json_bytes(input_audit))

    plan, plan_bytes = _read_json_object(source_root / "plan.json", "Production plan")
    _validate_identity(plan, label="Production plan", inventory=inventory)
    if plan.get("planFingerprint") != plan_fingerprint:
        raise ValueError("Production plan fingerprint does not match inventory")
    raw_shards = plan.get("shards")
    if not isinstance(raw_shards, list):
        raise ValueError("Production plan shards are malformed")
    cells: list[tuple[int, int]] = []
    for shard in raw_shards:
        if not isinstance(shard, dict) or not isinstance(shard.get("cells"), list):
            raise ValueError("Production plan shard is malformed")
        for raw_cell in shard["cells"]:
            if (
                not isinstance(raw_cell, list)
                or len(raw_cell) != 2
                or not all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in raw_cell
                )
            ):
                raise ValueError("Production plan cell is malformed")
            cells.append((raw_cell[0], raw_cell[1]))
    if plan != plan_report(cells):
        raise ValueError("Production plan does not recompute exactly")
    native_tiles = {
        TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"]))
        for entry in entries
        if int(entry["z"]) == NATIVE_ZOOM
    }
    if native_tiles != {native_tile_for_cell(cell) for cell in cells}:
        raise ValueError("Production plan does not match the native inventory")
    source_scope["shards"] = len(raw_shards)
    source_scope["rawCrossShardProbes"] = EXPECTED_QUALITY_SCOPE[
        "rawCrossShardProbes"
    ]
    if source_scope != EXPECTED_QUALITY_SCOPE:
        raise ValueError("Production source does not match the pinned quality scope")

    _validate_tile_tree(source_root, entries, progress=progress)
    return ValidatedInventory(
        payload=inventory,
        inventory_sha256=logical_sha256,
        inventory_file_sha256=_sha256_bytes(inventory_bytes),
        provenance_file_sha256=_sha256_bytes(provenance_bytes),
        plan_file_sha256=_sha256_bytes(plan_bytes),
        tile_count=tile_count,
        total_bytes=total_bytes,
        tile_entries=entries,
        provenance=provenance,
        provenance_fingerprint=provenance_fingerprint,
        plan_fingerprint=plan_fingerprint,
        profile_fingerprint=profile_fingerprint,
        renderer_fingerprint=renderer_fingerprint,
        production_source_fingerprint=production_source_fingerprint,
        asset_tree_fingerprint=asset_tree_fingerprint,
        input_fingerprint=input_fingerprint,
        source_scope=source_scope,
    )


def _gate_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Quality audit {label} evidence is malformed")
    return value


def _require_gate_values(
    gate: Mapping[str, Any],
    expected: Mapping[str, object],
    label: str,
) -> None:
    for key, value in expected.items():
        if gate.get(key) != value:
            raise ValueError(f"Quality audit {label}.{key} evidence is invalid")


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_quality_gate_evidence(
    gates: Mapping[str, Any],
    inventory: ValidatedInventory,
    stabilization: Mapping[str, Any],
    *,
    stabilization_receipt_file_sha256: str,
    require_binary_alpha: bool,
) -> None:
    scope = inventory.source_scope
    identity = _gate_mapping(stabilization.get("identity"), "stabilization identity")
    stabilization_scope = _gate_mapping(identity.get("scope"), "stabilization scope")

    inventory_gate = _gate_mapping(gates.get("inventory"), "inventory")
    expected_inventory: dict[str, object] = {
        "passes": True,
        "tileCount": scope["tiles"],
        "totalBytes": inventory.total_bytes,
        "decoded512Rgba": scope["tiles"],
        "nonemptyTiles": scope["tiles"],
        "inventorySha256": inventory.inventory_sha256,
        "inventoryFileSha256": inventory.inventory_file_sha256,
    }
    _require_gate_values(inventory_gate, expected_inventory, "inventory")
    if require_binary_alpha:
        _require_gate_values(
            inventory_gate,
            {
                "alphaMode": "binary-nonzero",
                "binaryAlphaTiles": scope["tiles"],
                "alphaIntermediatePixels": 0,
            },
            "inventory",
        )
        transparent = inventory_gate.get("alphaTransparentPixels")
        opaque = inventory_gate.get("alphaOpaquePixels")
        if (
            not _nonnegative_integer(transparent)
            or not _nonnegative_integer(opaque)
            or int(transparent) + int(opaque)
            != scope["tiles"] * TILE_PIXELS * TILE_PIXELS
        ):
            raise ValueError("Quality audit inventory binary-alpha totals are invalid")

    stabilization_gate = _gate_mapping(
        gates.get("seamStabilization"), "seamStabilization"
    )
    touched = int(stabilization_scope["touchedTiles"])
    expected_stabilization: dict[str, object] = {
            "passes": True,
            "stabilizerVersion": stabilization["stabilizerVersion"],
            "stabilizationFingerprint": stabilization["stabilizationFingerprint"],
            "receiptSha256": stabilization["receiptSha256"],
            "receiptFileSha256": stabilization_receipt_file_sha256,
            "implementationSha256": identity["implementationSha256"],
            "postprocessToolchain": identity["postprocessToolchain"],
            "sourceInventorySha256": identity["sourceInventory"]["logicalSha256"],
            "tileTransformsSha256": identity["tileTransforms"]["sha256"],
            "scope": dict(stabilization_scope),
            "expectedTouchedTiles": touched,
            "transformRecords": touched,
            "verifiedAfterRgbaTiles": touched,
            "afterRgbaMismatches": 0,
            "mismatchExamples": [],
            "beforeRgbaValidation": "format-and-receipt-bound",
        }
    if require_binary_alpha:
        output = _gate_mapping(stabilization.get("output"), "stabilization output")
        expected_stabilization.update(
            {
                "alphaEvidence": output.get("alphaEvidence"),
                "alphaEvidenceMatchesTiles": True,
            }
        )
    _require_gate_values(
        stabilization_gate,
        expected_stabilization,
        "seamStabilization",
    )
    state = _gate_mapping(gates.get("stateAndMigrations"), "stateAndMigrations")
    _require_gate_values(
        state,
        {
            "passes": True,
            "planFingerprint": inventory.plan_fingerprint,
            "targetCount": scope["nativeTiles"],
            "shardCount": scope["shards"],
            "checkpointArtifacts": scope["nativeTiles"],
            "postprocessedNativeTiles": stabilization_scope["changedTiles"],
        },
        "stateAndMigrations",
    )
    if (
        not _nonnegative_integer(state.get("checkpointArtifactBytes"))
        or not isinstance(state.get("checkpointSha256"), str)
        or _SHA256.fullmatch(state["checkpointSha256"]) is None
        or not isinstance(state.get("migrationChain"), list)
    ):
        raise ValueError("Quality audit stateAndMigrations evidence is incomplete")
    breakdown = state.get("renderProvenanceBreakdown")
    if (
        not isinstance(breakdown, list)
        or not breakdown
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("provenanceFingerprint"), str)
            or _SHA256.fullmatch(item["provenanceFingerprint"]) is None
            or not _nonnegative_integer(item.get("tiles"))
            for item in breakdown
        )
        or sum(int(item["tiles"]) for item in breakdown) != scope["nativeTiles"]
    ):
        raise ValueError("Quality audit render provenance breakdown is incomplete")

    pyramid = _gate_mapping(gates.get("pyramidDerivation"), "pyramidDerivation")
    _require_gate_values(
        pyramid,
        {
            "passes": True,
            "parentsChecked": scope["lowerZoomTiles"],
            "expectedParents": scope["lowerZoomTiles"],
            "mismatches": [],
            "tileCountsByZoom": {
                str(zoom): count for zoom, count in EXPECTED_TILE_COUNTS.items()
            },
        },
        "pyramidDerivation",
    )

    seams = _gate_mapping(gates.get("finalSeams"), "finalSeams")
    _require_gate_values(
        seams,
        {
            "passes": True,
            "adjacencies": scope["allFinalAdjacencies"],
            "nativeAdjacencies": scope["nativeAdjacencies"],
            "nativeSameShard": scope["nativeAdjacencies"]
            - scope["nativeCrossShardAdjacencies"],
            "nativeCrossShard": scope["nativeCrossShardAdjacencies"],
            "flaggedPairsAreDiagnostic": True,
            "crossShardStructuralFailures": 0,
            "crossShardStructuralFailureIds": [],
            "thresholds": EXPECTED_FINAL_SEAM_THRESHOLDS,
            "relativePopulationPasses": True,
            "absolutePopulationPasses": True,
            "populationPasses": True,
        },
        "finalSeams",
    )
    same_population = _gate_mapping(seams.get("sameShardPopulation"), "same population")
    cross_population = _gate_mapping(
        seams.get("crossShardPopulation"), "cross population"
    )
    if (
        same_population.get("count")
        != scope["nativeAdjacencies"] - scope["nativeCrossShardAdjacencies"]
        or cross_population.get("count") != scope["nativeCrossShardAdjacencies"]
    ):
        raise ValueError("Quality audit seam population counts are incomplete")

    runtime = _gate_mapping(
        gates.get("runtimeResourcesCoordinates"), "runtimeResourcesCoordinates"
    )
    _require_gate_values(
        runtime,
        {
            "passes": True,
            "shards": scope["shards"],
            "targetMarkers": scope["nativeTiles"],
            "maximumCoordinateErrorPixels": 0.0,
            "resourceReports": scope["shards"],
            "actionableMissingResources": 0,
            "openmwCommit": OPENMW_COMMIT,
        },
        "runtimeResourcesCoordinates",
    )
    runtime_identity = _gate_mapping(runtime.get("runtime"), "runtime identity")
    _require_gate_values(
        runtime_identity,
        {"os": "linux", "architecture": "amd64", "renderer": "llvmpipe"},
        "runtimeResourcesCoordinates.runtime",
    )
    sources = runtime.get("buildManifestProductionSources")
    if (
        not isinstance(sources, dict)
        or not sources
        or any(
            not isinstance(key, str)
            or _SHA256.fullmatch(key) is None
            or not _nonnegative_integer(value)
            for key, value in sources.items()
        )
        or sum(int(value) for value in sources.values()) != scope["shards"]
    ):
        raise ValueError("Quality audit runtime production-source evidence is incomplete")
    if (
        not isinstance(runtime.get("normalizedBuildManifestSha256"), str)
        or _SHA256.fullmatch(runtime["normalizedBuildManifestSha256"]) is None
        or any(
            not _nonnegative_integer(runtime_identity.get(key))
            for key in (
                "sumContainerSeconds",
                "maximumContainerSeconds",
                "maximumMemoryPeakBytes",
            )
        )
    ):
        raise ValueError("Quality audit runtime evidence is incomplete")

    raw = _gate_mapping(gates.get("rawProbes"), "rawProbes")
    _require_gate_values(
        raw,
        {
            "passes": True,
            "status": "passed",
            "selectedCrossShardSeams": scope["rawCrossShardProbes"],
            "thresholds": EXPECTED_RAW_THRESHOLDS,
            "selectionStrategy": "pinned-plus-directional-risk-strata-v2",
            "pinnedProbeIds": list(PINNED_RAW_PROBE_IDS),
        },
        "rawProbes",
    )
    renderer = _gate_mapping(raw.get("rendererProvenance"), "raw renderer provenance")
    expected_renderer_keys = {
        "passes",
        "mode",
        "releasedProvenanceFingerprint",
        "candidateProvenanceFingerprint",
        "releasedImageId",
        "candidateImageId",
        "candidatePayloadSha256",
        "rendererContractEqual",
        "nonImageProvenanceEqual",
    }
    released_image = inventory.provenance.get("image")
    if not isinstance(released_image, dict) or not isinstance(released_image.get("id"), str):
        raise ValueError("Released renderer image identity is malformed")
    if (
        set(renderer) != expected_renderer_keys
        or renderer.get("passes") is not True
        or renderer.get("mode") not in {"exact", "manifest-rematerialization"}
        or renderer.get("releasedProvenanceFingerprint")
        != inventory.provenance_fingerprint
        or renderer.get("releasedImageId") != released_image["id"]
        or not isinstance(renderer.get("candidatePayloadSha256"), str)
        or _SHA256.fullmatch(renderer["candidatePayloadSha256"]) is None
        or renderer.get("rendererContractEqual") is not True
        or renderer.get("nonImageProvenanceEqual") is not True
    ):
        raise ValueError("Quality audit raw renderer provenance is incomplete")
    candidate_fingerprint = renderer.get("candidateProvenanceFingerprint")
    candidate_image = renderer.get("candidateImageId")
    if renderer["mode"] == "exact" and (
        candidate_fingerprint != inventory.provenance_fingerprint
        or candidate_image != released_image["id"]
        or renderer["candidatePayloadSha256"]
        != _sha256_bytes(_canonical_json_bytes(inventory.provenance))
    ):
        raise ValueError("Quality audit exact raw renderer provenance is inconsistent")
    if renderer["mode"] == "manifest-rematerialization" and (
        candidate_fingerprint == inventory.provenance_fingerprint
        or candidate_image == released_image["id"]
        or not isinstance(candidate_fingerprint, str)
        or _SHA256.fullmatch(candidate_fingerprint) is None
        or not isinstance(candidate_image, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_image) is None
    ):
        raise ValueError("Quality audit rematerialized renderer provenance is inconsistent")
    probes = raw.get("probes")
    if not isinstance(probes, list) or len(probes) != scope["rawCrossShardProbes"]:
        raise ValueError("Quality audit raw probes are incomplete")
    if (
        not _nonnegative_integer(raw.get("targetCells"))
        or raw.get("targetCells") == 0
        or raw.get("completedCells") != raw.get("targetCells")
        or raw.get("uniqueCells") != raw.get("targetCells")
        or not isinstance(raw.get("selectionSha256"), str)
        or _SHA256.fullmatch(raw["selectionSha256"]) is None
    ):
        raise ValueError("Quality audit raw completion evidence is incomplete")
    probe_ids: set[str] = set()
    for probe in probes:
        if not isinstance(probe, dict) or probe.get("passes") is not True:
            raise ValueError("Quality audit raw probe failed or is malformed")
        identifier = probe.get("id")
        repeats = probe.get("releasedRepeat")
        if (
            not isinstance(identifier, str)
            or identifier in probe_ids
            or not isinstance(repeats, list)
            or len(repeats) != 2
            or any(
                not isinstance(repeat, dict)
                or repeat.get("passes") is not True
                or repeat.get("opaqueDifferingPixels") != 0
                for repeat in repeats
            )
            or probe.get("releaseSeamPasses") is not True
        ):
            raise ValueError("Quality audit raw probe evidence is incomplete")
        if probe.get("sourceOverlapPasses") is not True and (
            probe.get("repairRequired") is not True
            or probe.get("repairCoveredByReceipt") is not True
        ):
            raise ValueError("Quality audit raw seam repair is not receipt-covered")
        probe_ids.add(identifier)
    if not set(PINNED_RAW_PROBE_IDS).issubset(probe_ids):
        raise ValueError("Quality audit pinned raw probes are missing")


def _validate_raw_renderer_provenance_artifact(
    *,
    audit_root: Path,
    artifacts: Mapping[str, Any],
    gates: Mapping[str, Any],
    inventory: ValidatedInventory,
) -> None:
    artifact = _gate_mapping(
        artifacts.get("rawRendererProvenance"),
        "raw renderer provenance artifact",
    )
    relative = artifact.get("path")
    if not isinstance(relative, str):
        raise ValueError("Raw renderer provenance artifact path is invalid")
    candidate, _ = _read_json_object(
        audit_root / relative,
        "Raw renderer provenance artifact",
    )
    raw = _gate_mapping(gates.get("rawProbes"), "rawProbes")
    renderer = _gate_mapping(raw.get("rendererProvenance"), "raw renderer provenance")
    candidate_image = candidate.get("image")
    released_image = inventory.provenance.get("image")
    if not isinstance(candidate_image, dict) or not isinstance(released_image, dict):
        raise ValueError("Raw renderer provenance image identity is malformed")
    candidate_fingerprint = _verified_publication_provenance(candidate)
    if (
        candidate_fingerprint != renderer.get("candidateProvenanceFingerprint")
        or candidate_image.get("id") != renderer.get("candidateImageId")
        or _sha256_bytes(_canonical_json_bytes(candidate))
        != renderer.get("candidatePayloadSha256")
    ):
        raise ValueError("Raw renderer provenance artifact does not match the audit gate")

    if renderer.get("mode") == "exact":
        if candidate != inventory.provenance:
            raise ValueError("Exact raw renderer provenance differs from production")
        return

    released_core = {
        key: value
        for key, value in inventory.provenance.items()
        if key not in {"provenanceFingerprint", "image"}
    }
    candidate_core = {
        key: value
        for key, value in candidate.items()
        if key not in {"provenanceFingerprint", "image"}
    }
    released_image_contract = {
        key: value
        for key, value in released_image.items()
        if key not in {"id", "repoDigests"}
    }
    candidate_image_contract = {
        key: value
        for key, value in candidate_image.items()
        if key not in {"id", "repoDigests"}
    }
    if (
        renderer.get("mode") != "manifest-rematerialization"
        or released_core != candidate_core
        or released_image_contract != candidate_image_contract
        or released_image.get("id") == candidate_image.get("id")
    ):
        raise ValueError("Rematerialized raw renderer provenance is incompatible")


def validate_quality_report(
    source_root: Path,
    inventory: ValidatedInventory,
) -> QualityReportArtifact:
    stabilization, implementation_sha256 = _validated_stabilization(
        source_root, inventory
    )
    stabilization_identity = stabilization["identity"]
    if not isinstance(stabilization_identity, dict):
        raise ValueError("Seam stabilization identity is malformed")
    path = source_root.resolve() / QUALITY_REPORT_RELATIVE_PATH
    report, report_bytes = _read_json_object(path, "Quality audit report")
    if set(report) != QUALITY_REPORT_KEYS:
        raise ValueError("Quality audit report fields do not match the pinned contract")
    current = (
        report.get("schemaVersion") == EXPECTED_AUDIT_SCHEMA_VERSION
        and report.get("auditVersion") == EXPECTED_AUDIT_VERSION
    )
    legacy = (
        report.get("schemaVersion") == LEGACY_AUDIT_SCHEMA_VERSION
        and report.get("auditVersion") == LEGACY_AUDIT_VERSION
    )
    if not current and not legacy:
        raise ValueError("Quality audit report auditVersion is unsupported")
    provenance_presentation = inventory.provenance.get("presentation")
    if current:
        if not isinstance(provenance_presentation, dict) or any(
            provenance_presentation.get(key) != value
            for key, value in V4_PRESENTATION.items()
            if key != "colorGrade"
        ):
            raise ValueError("V4 quality audit presentation provenance is invalid")
    elif provenance_presentation is not None:
        raise ValueError("Legacy quality audit cannot validate V4 presentation")
    if report.get("datasetId") != DATASET_ID or report.get("snapshotId") != SNAPSHOT_ID:
        raise ValueError("Quality audit report dataset identity does not match")
    if report.get("passes") is not True:
        raise ValueError("Quality audit report is not passing")
    if report.get("scope") != EXPECTED_QUALITY_SCOPE or report.get("scope") != inventory.source_scope:
        raise ValueError("Quality audit report scope is not the pinned full scope")
    gates = report.get("gates")
    if not isinstance(gates, dict) or set(gates) != MANDATORY_QUALITY_GATES:
        raise ValueError("Quality audit report mandatory gates are missing or unexpected")
    for name, gate in gates.items():
        if not isinstance(gate, dict) or gate.get("passes") is not True:
            raise ValueError(f"Quality audit gate {name} is not passing")
    _validate_quality_gate_evidence(
        gates,
        inventory,
        stabilization,
        stabilization_receipt_file_sha256=_sha256_file(
            source_root / STABILIZATION_RECEIPT_PATH
        ),
        require_binary_alpha=current,
    )
    raw_gate = gates["rawProbes"]
    if (
        raw_gate.get("status") != "passed"
        or raw_gate.get("selectedCrossShardSeams") != EXPECTED_QUALITY_SCOPE["rawCrossShardProbes"]
    ):
        raise ValueError("Quality audit raw-probe gate is incomplete")
    stabilization_gate = gates["seamStabilization"]
    if (
        stabilization_gate.get("stabilizationFingerprint")
        != stabilization["stabilizationFingerprint"]
        or stabilization_gate.get("receiptSha256")
        != stabilization["receiptSha256"]
        or stabilization_gate.get("postprocessToolchain")
        != stabilization_identity.get("postprocessToolchain")
    ):
        raise ValueError("Quality audit seam-stabilization gate is stale")
    audit_sha256 = _fingerprint(
        report.get("auditSha256"), "Quality audit report auditSha256"
    )
    core = {key: value for key, value in report.items() if key != "auditSha256"}
    if _sha256_bytes(_canonical_json_bytes(core)) != audit_sha256:
        raise ValueError("Quality audit logical SHA-256 does not match its payload")
    identity = report.get("identity")
    if not isinstance(identity, dict) or set(identity) != QUALITY_IDENTITY_KEYS:
        raise ValueError("Quality audit report identity does not match the pinned contract")
    expected_identity = {
        "inventorySha256": inventory.inventory_sha256,
        "inventoryFileSha256": inventory.inventory_file_sha256,
        "provenanceFileSha256": inventory.provenance_file_sha256,
        "planFileSha256": inventory.plan_file_sha256,
        "provenanceFingerprint": inventory.provenance_fingerprint,
        "planFingerprint": inventory.plan_fingerprint,
        "profileFingerprint": inventory.profile_fingerprint,
        "rendererFingerprint": inventory.renderer_fingerprint,
        "productionSourceFingerprint": inventory.production_source_fingerprint,
        "assetTreeFingerprint": inventory.asset_tree_fingerprint,
        "inputFingerprint": inventory.input_fingerprint,
        "stabilizationFingerprint": stabilization["stabilizationFingerprint"],
        "stabilizationReceiptSha256": stabilization["receiptSha256"],
        "stabilizationReceiptFileSha256": _sha256_file(
            source_root / STABILIZATION_RECEIPT_PATH
        ),
        "stabilizerImplementationSha256": implementation_sha256,
        "sourceInventorySha256": stabilization_identity["sourceInventory"][
            "logicalSha256"
        ],
        "auditImplementationSha256": (
            _sha256_file(Path(__file__).with_name("audit.py"))
            if current
            else LEGACY_AUDIT_IMPLEMENTATION_SHA256
        ),
    }
    for key, expected in expected_identity.items():
        if identity.get(key) != expected:
            raise ValueError(f"Quality audit report {key} does not match production")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != QUALITY_DETAIL_ARTIFACTS:
        raise ValueError("Quality audit detail artifacts do not match the pinned contract")
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256", "bytes"}:
            raise ValueError(f"Quality audit artifact {name} is malformed")
        relative = artifact.get("path")
        if not isinstance(relative, str):
            raise ValueError(f"Quality audit artifact {name} path is invalid")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Quality audit artifact {name} path escapes the audit root")
        detail_path = (path.parent / relative_path).resolve()
        if path.parent.resolve() not in detail_path.parents:
            raise ValueError(f"Quality audit artifact {name} path escapes the audit root")
        if not detail_path.is_file() or detail_path.is_symlink():
            raise FileNotFoundError(f"Quality audit artifact {name} is missing: {detail_path}")
        expected_bytes = _positive_integer(
            artifact.get("bytes"), f"Quality audit artifact {name} bytes"
        )
        expected_hash = _fingerprint(
            artifact.get("sha256"), f"Quality audit artifact {name} sha256"
        )
        if detail_path.stat().st_size != expected_bytes:
            raise ValueError(f"Quality audit artifact {name} byte length mismatch")
        if _sha256_file(detail_path) != expected_hash:
            raise ValueError(f"Quality audit artifact {name} SHA-256 mismatch")
    _validate_raw_renderer_provenance_artifact(
        audit_root=path.parent.resolve(),
        artifacts=artifacts,
        gates=gates,
        inventory=inventory,
    )
    return QualityReportArtifact(
        path=path,
        sha256=_sha256_bytes(report_bytes),
        byte_length=len(report_bytes),
        audit_sha256=audit_sha256,
    )


def _validated_stabilization(
    source_root: Path,
    inventory: ValidatedInventory,
) -> tuple[dict[str, Any], str]:
    from tools.openmw_renderer.stabilize import validate_stabilization_receipt

    receipt = validate_stabilization_receipt(source_root, inventory)
    identity = receipt.get("identity")
    if not isinstance(identity, dict) or not isinstance(
        identity.get("implementationSha256"), str
    ):
        raise ValueError("Seam stabilization implementation identity is malformed")
    return receipt, str(identity["implementationSha256"])


def build_tile_coverage(inventory: ValidatedInventory) -> dict[str, Any]:
    levels: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for entry in inventory.tile_entries:
        levels[int(entry["z"])][int(entry["x"])].append(int(entry["y"]))
    encoded_levels = []
    for zoom, columns in sorted(levels.items()):
        encoded_columns = []
        for x, raw_ys in sorted(columns.items()):
            ys = sorted(set(raw_ys))
            ranges: list[list[int]] = []
            start = previous = ys[0]
            for y in ys[1:]:
                if y == previous + 1:
                    previous = y
                    continue
                ranges.append([start, previous])
                start = previous = y
            ranges.append([start, previous])
            encoded_columns.append({"x": x, "yRanges": ranges})
        encoded_levels.append({"z": zoom, "columns": encoded_columns})
    return {
        "schemaVersion": COVERAGE_SCHEMA_VERSION,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "tilePyramidId": TILE_PYRAMID_ID,
        "encoding": "x-y-ranges-v1",
        "tileCount": inventory.tile_count,
        "levels": encoded_levels,
    }


def _published_presentation(
    provenance: Mapping[str, Any],
) -> dict[str, str] | None:
    presentation = provenance.get("presentation")
    if not isinstance(presentation, dict):
        return None
    if (
        presentation.get("gradeVersion") != V4_PRESENTATION["gradeVersion"]
        or presentation.get("alphaMode") != V4_PRESENTATION["alphaMode"]
    ):
        raise ValueError("Unsupported production presentation contract")
    return dict(V4_PRESENTATION)


def build_publish_metadata(
    source_root: Path,
    inventory: ValidatedInventory,
) -> PublishMetadata:
    quality = validate_quality_report(source_root, inventory)
    receipt_path = source_root.resolve() / STABILIZATION_RECEIPT_PATH
    receipt, receipt_bytes = _read_json_object(
        receipt_path, "Seam stabilization receipt"
    )
    receipt_identity = receipt.get("identity")
    if not isinstance(receipt_identity, dict):
        raise ValueError("Seam stabilization receipt identity is malformed")
    coverage = build_tile_coverage(inventory)
    coverage_bytes = _json_file_bytes(coverage)
    metadata_base_url = (
        f"/datasets/metadata/{DATASET_ID}/{inventory.inventory_sha256}"
    )
    tile_base_url = (
        f"/datasets/generated/{DATASET_ID}/{inventory.inventory_sha256}/tiles"
    )
    tile_pyramid: dict[str, Any] = {
        "id": TILE_PYRAMID_ID,
        "regionIds": list(TILE_REGIONS),
        "kind": "xyz-pyramid",
        "urlTemplate": f"{tile_base_url}/{{z}}/{{x}}/{{y}}.webp",
        "mediaType": "image/webp",
        "tileSize": TILE_PIXELS,
        "extent": list(POISON_WORLD_EXTENT),
        "origin": [-229376, 278528],
        "resolutions": list(TILE_RESOLUTIONS),
        "minZoom": MIN_ZOOM,
        "maxZoom": MAX_ZOOM,
        "sparse": True,
        "coverage": {
            "url": f"{metadata_base_url}/tile-coverage.json",
            "mediaType": "application/json",
            "sha256": _sha256_bytes(coverage_bytes),
            "bytes": len(coverage_bytes),
        },
        "qualityReport": {
            "url": f"{metadata_base_url}/{PUBLISHED_QUALITY_REPORT_NAME}",
            "mediaType": "application/json",
            "sha256": quality.sha256,
            "bytes": quality.byte_length,
        },
        "derivation": {
            "kind": "cross-shard-seam-stabilization",
            "version": str(receipt["stabilizerVersion"]),
            "sourceInventorySha256": str(
                receipt_identity["sourceInventory"]["logicalSha256"]
            ),
            "implementationSha256": str(
                receipt_identity["implementationSha256"]
            ),
            "receipt": {
                "url": f"{metadata_base_url}/{STABILIZATION_RECEIPT_PATH.as_posix()}",
                "mediaType": "application/json",
                "sha256": _sha256_bytes(receipt_bytes),
                "bytes": len(receipt_bytes),
            },
        },
        "integrity": {
            "tileCount": inventory.tile_count,
            "totalBytes": inventory.total_bytes,
            "inventorySha256": inventory.inventory_sha256,
            "inventoryFileSha256": inventory.inventory_file_sha256,
            "provenanceFingerprint": inventory.provenance_fingerprint,
            "planFingerprint": inventory.plan_fingerprint,
            "profileFingerprint": inventory.profile_fingerprint,
            "rendererFingerprint": inventory.renderer_fingerprint,
            "productionSourceFingerprint": inventory.production_source_fingerprint,
            "assetTreeFingerprint": inventory.asset_tree_fingerprint,
            "inputFingerprint": inventory.input_fingerprint,
        },
    }
    presentation = _published_presentation(inventory.provenance)
    if presentation is not None:
        tile_pyramid["presentation"] = presentation
    map_assets = {
        "schemaVersion": MAP_ASSETS_SCHEMA_VERSION,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "projection": "TES3:WORLD",
        "rasters": [],
        "tilePyramids": [tile_pyramid],
    }
    return PublishMetadata(
        coverage,
        map_assets,
        quality,
        receipt_path,
        (
            source_root.resolve() / SOURCE_INVENTORY_PATH,
            source_root.resolve() / TILE_TRANSFORMS_PATH,
        ),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _safe_metadata_relative(relative: Path) -> Path:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"Immutable metadata artifact path is unsafe: {relative}")
    return relative


def _add_immutable_artifact(
    artifacts: dict[Path, bytes],
    relative: Path,
    payload: bytes,
) -> None:
    relative = _safe_metadata_relative(relative)
    existing = artifacts.get(relative)
    if existing is not None and existing != payload:
        raise ValueError(f"Immutable metadata artifact collides: {relative}")
    artifacts[relative] = payload


def _validate_immutable_metadata_tree(
    version_root: Path,
    artifacts: Mapping[Path, bytes],
) -> None:
    if version_root.is_symlink():
        raise ValueError(
            f"Immutable metadata version root cannot be a symlink: {version_root}"
        )
    if not version_root.is_dir():
        raise ValueError(f"Immutable metadata version root is not a directory: {version_root}")
    actual: set[Path] = set()
    for directory, names, files in os.walk(version_root, followlinks=False):
        current = Path(directory)
        for name in names:
            child = current / name
            if child.is_symlink():
                raise ValueError(f"Immutable metadata tree contains a symlink: {child}")
        for name in files:
            child = current / name
            if child.is_symlink() or not child.is_file():
                raise ValueError(f"Immutable metadata artifact is not a file: {child}")
            relative = child.relative_to(version_root)
            expected = artifacts.get(relative)
            if expected is None or child.read_bytes() != expected:
                raise ValueError(f"Immutable metadata artifact differs: {child}")
            actual.add(relative)
    expected_paths = set(artifacts)
    if actual != expected_paths:
        missing = sorted(path.as_posix() for path in expected_paths - actual)
        unexpected = sorted(path.as_posix() for path in actual - expected_paths)
        raise ValueError(
            "Immutable metadata tree is incomplete or divergent: "
            f"missing={missing}, unexpected={unexpected}"
        )


def _publish_immutable_metadata_tree(
    metadata_root: Path,
    inventory_sha256: str,
    artifacts: Mapping[Path, bytes],
    *,
    pre_commit: Callable[[], None] | None = None,
) -> Path:
    version_root = metadata_root / inventory_sha256
    if version_root.is_symlink():
        raise ValueError(
            f"Immutable metadata version root cannot be a symlink: {version_root}"
        )
    if version_root.exists():
        _validate_immutable_metadata_tree(version_root, artifacts)
        return version_root

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{inventory_sha256}.",
            suffix=".tmp",
            dir=metadata_root,
        )
    )
    published = False
    try:
        for relative, payload in sorted(
            artifacts.items(), key=lambda item: item[0].as_posix()
        ):
            _atomic_write(staging / _safe_metadata_relative(relative), payload)
        _validate_immutable_metadata_tree(staging, artifacts)
        if pre_commit is not None:
            pre_commit()
        _publish_staged_directory_no_replace(staging, version_root)
        published = True
        return version_root
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _resolved_destination(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    if absolute.is_symlink():
        raise ValueError(f"{label} cannot be a symlink: {absolute}")
    return absolute.resolve(strict=False)


def _require_ignored_worktree_target(target: Path, *, repo_root: Path) -> None:
    repo_root = repo_root.resolve()
    target = target.resolve(strict=False)
    if repo_root not in target.parents:
        return
    relative = target.relative_to(repo_root)
    completed = subprocess.run(
        ("git", "-C", str(repo_root), "check-ignore", "--quiet", "--", str(relative)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"Generated tile target inside the worktree must be Git-ignored: {target}"
        )


def write_publish_metadata(
    metadata_root: Path,
    metadata: PublishMetadata,
    *,
    pre_commit: Callable[[], None] | None = None,
) -> dict[Path, bytes]:
    metadata_root = _resolved_destination(metadata_root, "Metadata root")
    metadata_root.mkdir(parents=True, exist_ok=True)
    coverage_bytes = _json_file_bytes(metadata.coverage)
    quality_bytes = metadata.quality_report.path.read_bytes()
    if _sha256_bytes(quality_bytes) != metadata.quality_report.sha256:
        raise RuntimeError("Quality audit report changed during publication")
    quality_payload = json.loads(quality_bytes)
    quality_artifacts = quality_payload.get("artifacts")
    if not isinstance(quality_artifacts, dict):
        raise RuntimeError("Quality audit detail artifacts changed during publication")
    pyramids = metadata.map_assets.get("tilePyramids")
    if not isinstance(pyramids, list) or len(pyramids) != 1:
        raise ValueError("Published map assets must contain one tile pyramid")
    integrity = pyramids[0].get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("Published tile pyramid integrity is missing")
    inventory_sha256 = integrity.get("inventorySha256")
    if not isinstance(inventory_sha256, str) or _SHA256.fullmatch(inventory_sha256) is None:
        raise ValueError("Published tile pyramid inventory identity is invalid")
    immutable_artifacts: dict[Path, bytes] = {}
    _add_immutable_artifact(
        immutable_artifacts,
        Path("tile-coverage.json"),
        coverage_bytes,
    )
    for name, artifact in quality_artifacts.items():
        if not isinstance(artifact, dict):
            raise RuntimeError(f"Quality audit artifact {name} changed during publication")
        relative = Path(str(artifact.get("path")))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Quality audit artifact {name} path is unsafe")
        source = (metadata.quality_report.path.parent / relative).resolve()
        if metadata.quality_report.path.parent.resolve() not in source.parents:
            raise RuntimeError(f"Quality audit artifact {name} path escapes its root")
        payload = source.read_bytes()
        if (
            len(payload) != artifact.get("bytes")
            or _sha256_bytes(payload) != artifact.get("sha256")
        ):
            raise RuntimeError(f"Quality audit artifact {name} changed during publication")
        _add_immutable_artifact(immutable_artifacts, relative, payload)
    derivation = pyramids[0].get("derivation")
    if not isinstance(derivation, dict) or not isinstance(
        derivation.get("receipt"), dict
    ):
        raise ValueError("Published tile pyramid derivation is missing")
    receipt_reference = derivation["receipt"]
    source_dataset_root = metadata.stabilization_receipt.parent.resolve()
    receipt_payload = metadata.stabilization_receipt.read_bytes()
    if (
        len(receipt_payload) != receipt_reference.get("bytes")
        or _sha256_bytes(receipt_payload) != receipt_reference.get("sha256")
    ):
        raise RuntimeError("Seam stabilization receipt changed during publication")
    receipt_value = json.loads(receipt_payload)
    receipt_identity = receipt_value.get("identity")
    if not isinstance(receipt_identity, dict):
        raise RuntimeError("Seam stabilization receipt changed during publication")
    support_by_path = {
        str(receipt_identity["sourceInventory"]["path"]): receipt_identity[
            "sourceInventory"
        ],
        str(receipt_identity["tileTransforms"]["path"]): receipt_identity[
            "tileTransforms"
        ],
    }
    for source in (metadata.stabilization_receipt, *metadata.stabilization_support):
        relative = source.resolve().relative_to(source_dataset_root)
        payload = source.read_bytes()
        if source != metadata.stabilization_receipt:
            expected = support_by_path.get(relative.as_posix())
            if (
                expected is None
                or len(payload) != expected.get("bytes")
                or _sha256_bytes(payload) != expected.get("sha256")
            ):
                raise RuntimeError(
                    f"Seam stabilization support artifact changed: {relative}"
                )
        _add_immutable_artifact(immutable_artifacts, relative, payload)
    _add_immutable_artifact(
        immutable_artifacts,
        Path(PUBLISHED_QUALITY_REPORT_NAME),
        quality_bytes,
    )
    _add_immutable_artifact(
        immutable_artifacts,
        Path("map-assets.json"),
        _json_file_bytes(metadata.map_assets),
    )
    _publish_immutable_metadata_tree(
        metadata_root,
        inventory_sha256,
        immutable_artifacts,
        pre_commit=pre_commit,
    )
    return immutable_artifacts


def _copy_tree(source: Path, destination: Path, *, copy_mode: str) -> str:
    if copy_mode not in {"auto", "copy"}:
        raise ValueError("copy_mode must be 'auto' or 'copy'")
    if copy_mode == "auto" and sys.platform == "darwin":
        completed = subprocess.run(
            ("cp", "-cR", str(source), str(destination)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return "apfs-clone"
        if destination.exists():
            shutil.rmtree(destination)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    return "copy"


def _publish_staged_directory_no_replace(staging: Path, destination: Path) -> None:
    source = os.fsencode(staging)
    target = os.fsencode(destination)
    libc = ctypes.CDLL(None, use_errno=True)

    if sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise RuntimeError("Atomic exclusive directory rename is unavailable on Darwin")
        renamex_np.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        renamex_np.restype = ctypes.c_int
        result = renamex_np(source, target, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise RuntimeError("Atomic exclusive directory rename is unavailable on Linux")
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, source, -100, target, 0x00000001)  # RENAME_NOREPLACE
    else:
        raise RuntimeError(
            f"Atomic exclusive directory rename is unsupported on {sys.platform}"
        )

    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(
            error_number,
            f"Immutable target appeared during publication: {destination}",
            destination,
        )
    if error_number in {errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
        raise RuntimeError(
            f"Atomic exclusive directory rename is unavailable: {os.strerror(error_number)}"
        )
    if error_number == errno.EXDEV:
        raise RuntimeError(
            "Atomic immutable publication requires staging and destination on the same filesystem"
        )
    raise OSError(
        error_number,
        f"Atomic immutable publication failed: {os.strerror(error_number)}",
        destination,
    )


def _materialize_tiles(
    source_root: Path,
    public_root: Path,
    inventory: ValidatedInventory,
    *,
    copy_mode: str,
    progress: ProgressCallback | None,
) -> tuple[Path, bool, str]:
    source_root = source_root.resolve()
    public_root = _resolved_destination(public_root, "Public dataset root")
    dataset_root = public_root / DATASET_ID
    if dataset_root.is_symlink():
        raise ValueError(f"Dataset root cannot be a symlink: {dataset_root}")
    target_root = public_root / DATASET_ID / inventory.inventory_sha256
    resolved_target = target_root.resolve(strict=False)
    if public_root not in resolved_target.parents:
        raise ValueError("Immutable tile target escapes the public dataset root")
    target_root = resolved_target
    _require_ignored_worktree_target(
        target_root,
        repo_root=Path(__file__).resolve().parents[2],
    )
    if target_root.is_symlink():
        raise ValueError(f"Immutable tile target cannot be a symlink: {target_root}")
    if target_root.exists():
        if not target_root.is_dir():
            raise ValueError(f"Immutable tile target is not a directory: {target_root}")
        _validate_tile_tree(target_root, inventory.tile_entries, progress=progress)
        return target_root, False, "existing"
    if target_root == source_root or source_root in target_root.parents:
        raise ValueError("Immutable tile target cannot be inside the production source")

    parent = target_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{inventory.inventory_sha256}.", suffix=".tmp", dir=parent)
    )
    published = False
    try:
        if progress is not None:
            progress("materializing immutable tile tree")
        copy_method = _copy_tree(
            source_root / "tiles",
            staging / "tiles",
            copy_mode=copy_mode,
        )
        _validate_tile_tree(staging, inventory.tile_entries, progress=progress)
        _publish_staged_directory_no_replace(staging, target_root)
        published = True
        return target_root, True, copy_method
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)


def prepare_dataset(
    *,
    source_root: Path = DEFAULT_RELEASE_OUTPUT,
    public_root: Path = DEFAULT_PUBLIC_ROOT,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    copy_mode: str = "auto",
    progress: ProgressCallback | None = None,
) -> PrepareResult:
    source_root = source_root.resolve()
    inventory = validate_source(source_root, progress=progress)
    metadata = build_publish_metadata(source_root, inventory)
    public_root = _resolved_destination(public_root, "Public dataset root")
    target_root = (public_root / DATASET_ID / inventory.inventory_sha256).resolve(
        strict=False
    )
    metadata_root = _resolved_destination(metadata_root, "Metadata root")
    if _paths_overlap(source_root, target_root):
        raise ValueError("Immutable tile target cannot overlap the production source")
    if _paths_overlap(metadata_root, source_root):
        raise ValueError("Metadata root cannot overlap the production source")
    if _paths_overlap(metadata_root, target_root):
        raise ValueError("Metadata root cannot overlap the immutable tile target")
    target_root, created, copy_method = _materialize_tiles(
        source_root,
        public_root,
        inventory,
        copy_mode=copy_mode,
        progress=progress,
    )
    if progress is not None:
        progress("publishing complete immutable dataset metadata")

    def revalidate_target_tiles() -> None:
        _validate_tile_tree(target_root, inventory.tile_entries, progress=progress)

    write_publish_metadata(
        metadata_root,
        metadata,
        pre_commit=revalidate_target_tiles,
    )
    return PrepareResult(
        target_root=target_root,
        metadata_root=metadata_root,
        inventory_sha256=inventory.inventory_sha256,
        tile_count=inventory.tile_count,
        total_bytes=inventory.total_bytes,
        created=created,
        copy_method=copy_method,
    )


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _result_json(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and safely prepare the Poison Song tile dataset"
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_RELEASE_OUTPUT,
        help="Audited seam-stabilized OpenMW release output",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="Validate inventory and tiles")
    validate.add_argument(
        "--require-quality",
        action="store_true",
        help="Also require and validate the passing quality audit",
    )
    prepare = subparsers.add_parser(
        "prepare", help="Materialize immutable tiles and publish metadata"
    )
    prepare.add_argument("--public-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    prepare.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    prepare.add_argument(
        "--copy-mode", choices=("auto", "copy"), default="auto"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    source_root = args.source_root.resolve()
    if args.command == "validate":
        inventory = validate_source(source_root, progress=_print_progress)
        quality = (
            validate_quality_report(source_root, inventory)
            if args.require_quality
            else None
        )
        _result_json(
            {
                "datasetId": DATASET_ID,
                "inventorySha256": inventory.inventory_sha256,
                "qualityAuditSha256": quality.audit_sha256 if quality else None,
                "sourceRoot": str(source_root),
                "tileCount": inventory.tile_count,
                "totalBytes": inventory.total_bytes,
                "valid": True,
            }
        )
        return 0
    result = prepare_dataset(
        source_root=source_root,
        public_root=args.public_root,
        metadata_root=args.metadata_root,
        copy_mode=args.copy_mode,
        progress=_print_progress,
    )
    _result_json(
        {
            "copyMethod": result.copy_method,
            "created": result.created,
            "datasetId": DATASET_ID,
            "inventorySha256": result.inventory_sha256,
            "metadataRoot": str(result.metadata_root),
            "targetRoot": str(result.target_root),
            "tileCount": result.tile_count,
            "totalBytes": result.total_bytes,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
