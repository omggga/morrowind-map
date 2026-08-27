from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from tools.land_renderer.terrain import RgbaImage, decode_texture, encode_webp
from tools.land_renderer.land import load_terrain
from tools.land_renderer.tiles import (
    CELL_REFERENCE_ZOOM,
    CELL_TILE_PIXELS,
    POISON_SONG_TILE_GRID,
    TES3_CELL_SIZE,
)
from tools.openmw_renderer.images import GRADE_VERSION, apply_grade
from tools.openmw_renderer.profile import (
    CONTENT_FILES,
    DATA_DIRECTORIES,
    DOCKER_PLATFORM,
    OPENMW_COMMIT,
    PROFILE_ID,
    fingerprint_data_directories,
    profile_fingerprint,
    render_console_script,
    render_openmw_cfg,
    render_settings_cfg,
    validate_source_inputs,
)
from tools.openmw_renderer.spike import (
    GUTTER_PIXELS,
    RAW_PIXELS,
    docker_image_info as stage45_docker_image_info,
    renderer_fingerprint,
    resource_resolution_report,
)
from tools.tes3.records import iter_records, iter_subrecords


DATASET_ID = "poison-song-26.08"
SNAPSHOT_ID = "tr:poison-song-26.08:6964517551e0fcb0"
PINNED_PROFILE_FINGERPRINT = (
    "6964517551e0fcb0ab7614cf27c7099087eaf88075007ce2b10784809cfd5469"
)
PRODUCTION_RENDERER_VERSION = "openmw-export-production-v1"
CHECKPOINT_SCHEMA_VERSION = 1
INVENTORY_SCHEMA_VERSION = 1
NATIVE_ZOOM = CELL_REFERENCE_ZOOM
MIN_ZOOM = 0
TILE_PIXELS = CELL_TILE_PIXELS
DEFAULT_OUTPUT = Path("local-data/openmw-production") / PROFILE_ID
DEFAULT_STAGE45_IMAGE = "morrowind-map-openmw:0.51.0-stage45"
DEFAULT_PRODUCTION_IMAGE = "morrowind-map-openmw:0.51.0-stage5"
CONTAINER_BATCH_FILE = PurePosixPath("/profile/export-targets.tsv")
CONTAINER_OUTPUT_ROOT = PurePosixPath("/out")
POISON_WORLD_EXTENT = (-229_376, -475_136, 409_600, 278_528)
PRODUCTION_SOURCE_PATHS = (
    ".dockerignore",
    "tools/tes3/records.py",
    "tools/land_renderer/land.py",
    "tools/land_renderer/terrain.py",
    "tools/land_renderer/tiles.py",
    "tools/openmw_renderer/images.py",
    "tools/openmw_renderer/profile.py",
    "tools/openmw_renderer/spike.py",
    "tools/openmw_renderer/production.py",
    "tools/openmw_renderer/Dockerfile.production",
    "tools/openmw_renderer/entrypoint-production.sh",
    "tools/openmw_renderer/patches/openmw-0.51.0-map-export-batch.patch",
)

Cell = tuple[int, int]
ImageReader = Callable[[Path], RgbaImage]
ImageEncoder = Callable[[RgbaImage], bytes]
ProgressCallback = Callable[[int, int], None]

_SHA256 = re.compile(r"[0-9a-f]{64}")
_BENIGN_ANIMATION_BONE_WARNING = re.compile(
    r"\bWarning:\s+addAnimSource:\s+can't find bone '[^']+' in .+ "
    r"\(referenced by .+\)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True, slots=True)
class TileKey:
    z: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if not isinstance(self.z, int) or isinstance(self.z, bool) or self.z < 0:
            raise ValueError("Tile zoom must be a non-negative integer")
        for label, value in (("x", self.x), ("y", self.y)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"Tile {label} must be an integer")

    @property
    def relative_path(self) -> Path:
        return Path(str(self.z), str(self.x), f"{self.y}.webp")


@dataclass(frozen=True, slots=True)
class NativeTarget:
    cell: Cell
    tile: TileKey


@dataclass(frozen=True, slots=True)
class RenderShard:
    center: Cell
    targets: tuple[NativeTarget, ...]

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("A render shard must contain at least one target")
        if len(self.targets) > 9:
            raise ValueError("A render shard cannot contain more than nine targets")
        seen: set[Cell] = set()
        for target in self.targets:
            if target.cell in seen:
                raise ValueError(f"Duplicate render target cell: {target.cell}")
            seen.add(target.cell)
            if max(
                abs(target.cell[0] - self.center[0]),
                abs(target.cell[1] - self.center[1]),
            ) > 1:
                raise ValueError(
                    f"Cell {target.cell} is outside the 3x3 shard at {self.center}"
                )

    @property
    def key(self) -> str:
        return f"cx-{_signed_component(self.center[0])}_cy-{_signed_component(self.center[1])}"


@dataclass(frozen=True, slots=True)
class TileArtifact:
    target: NativeTarget
    relative_path: str
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class NativeBatchResult:
    targets: int
    rendered: int
    skipped: int
    checkpoint_path: Path
    planned_shards: int = 0
    selected_shards: int = 0
    workers: int = 1


@dataclass(frozen=True, slots=True)
class TileInventory:
    payload: dict[str, object]

    @property
    def sha256(self) -> str:
        return str(self.payload["inventorySha256"])


@dataclass(frozen=True, slots=True)
class ProductionImageInfo:
    image: str
    image_id: str
    repo_digests: tuple[str, ...]
    os: str
    architecture: str
    labels: dict[str, str]
    contract_errors: tuple[str, ...]

    @property
    def contract_passes(self) -> bool:
        return not self.contract_errors


@dataclass(frozen=True, slots=True)
class ProductionProvenance:
    fingerprint: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ShardRuntimeEvidence:
    shard_key: str
    elapsed_seconds: int
    memory_peak_bytes: int


def _signed_component(value: int) -> str:
    return f"p{value}" if value >= 0 else f"n{abs(value)}"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_fingerprint(value: str, label: str = "provenance fingerprint") -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be an exact lowercase SHA-256")
    return value


def production_source_fingerprint(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for relative in PRODUCTION_SOURCE_PATHS:
        path = repo_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Production renderer source is missing: {path}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def execution_provenance_fingerprint(
    *,
    profile_fingerprint: str,
    production_source_fingerprint_value: str,
    image_id: str,
    image_repo_digests: Sequence[str] = (),
    magick_version: str,
) -> str:
    """Bind resumable output to every material producer input.

    The caller obtains the Docker image identity after the production image has
    been built.  A changed source tree, image, profile, grade, or encoder then
    produces a different checkpoint identity and resume fails closed.
    """

    _validate_fingerprint(profile_fingerprint, "profile fingerprint")
    _validate_fingerprint(
        production_source_fingerprint_value,
        "production source fingerprint",
    )
    if not image_id:
        raise ValueError("Docker image ID cannot be empty")
    if not magick_version:
        raise ValueError("ImageMagick version cannot be empty")
    payload = {
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "rendererVersion": PRODUCTION_RENDERER_VERSION,
        "profileFingerprint": profile_fingerprint,
        "productionSourceFingerprint": production_source_fingerprint_value,
        "openmwCommit": OPENMW_COMMIT,
        "imageId": image_id,
        "imageRepoDigests": sorted(set(image_repo_digests)),
        "gradeVersion": GRADE_VERSION,
        "magickVersion": magick_version,
    }
    return _sha256_bytes(_canonical_json_bytes(payload))


def _magick_version(executable: str) -> str:
    completed = subprocess.run(
        (executable, "-version"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )
    value = (completed.stdout or "").strip()
    if not value:
        raise RuntimeError("ImageMagick returned an empty version string")
    return value


def production_image_info(
    image: str,
    *,
    expected_source_fingerprint: str,
) -> ProductionImageInfo:
    _validate_fingerprint(
        expected_source_fingerprint,
        "production source fingerprint",
    )
    completed = subprocess.run(
        ("docker", "image", "inspect", image),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise RuntimeError(f"Unexpected Docker image inspect response for {image}")
    item = value[0]
    labels = {
        str(key): str(label_value)
        for key, label_value in ((item.get("Config") or {}).get("Labels") or {}).items()
    }
    actual_os = str(item.get("Os", ""))
    architecture = str(item.get("Architecture", ""))
    expected_labels = {
        "org.opencontainers.image.revision": OPENMW_COMMIT,
        "io.morrowind-map.stage": "5",
        "io.morrowind-map.dataset": DATASET_ID,
        "io.morrowind-map.snapshot": SNAPSHOT_ID,
        "io.morrowind-map.production-fingerprint": expected_source_fingerprint,
        "io.morrowind-map.scene-grid": "5x5",
        "io.morrowind-map.rtt-grid": "3x3",
    }
    errors: list[str] = []
    if actual_os != "linux":
        errors.append(f"expected image OS linux, got {actual_os or 'missing'}")
    if architecture != "amd64":
        errors.append(
            f"expected image architecture amd64, got {architecture or 'missing'}"
        )
    for key, expected in expected_labels.items():
        if labels.get(key) != expected:
            errors.append(
                f"image label {key} mismatch: expected {expected!r}, "
                f"got {labels.get(key)!r}"
            )
    parent_image_id = labels.get("io.morrowind-map.stage45-image-id", "")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", parent_image_id) is None:
        errors.append("Stage 4.5 parent image ID label is missing or invalid")
    image_id = str(item.get("Id", ""))
    if not image_id:
        errors.append("image ID is missing")
    return ProductionImageInfo(
        image=image,
        image_id=image_id,
        repo_digests=tuple(str(digest) for digest in item.get("RepoDigests") or ()),
        os=actual_os,
        architecture=architecture,
        labels=labels,
        contract_errors=tuple(errors),
    )


def resolve_production_provenance(
    *,
    repo_root: Path,
    source_root: Path,
    image: str = DEFAULT_PRODUCTION_IMAGE,
    magick: str = "magick",
) -> ProductionProvenance:
    """Validate every material producer input and derive one resume identity."""

    source_hash = production_source_fingerprint(repo_root)
    image_info = production_image_info(
        image,
        expected_source_fingerprint=source_hash,
    )
    if not image_info.contract_passes:
        raise RuntimeError(
            "Production Docker image identity check failed: "
            + "; ".join(image_info.contract_errors)
        )
    input_audit = validate_source_inputs(source_root)
    asset_audit = fingerprint_data_directories(source_root)
    actual_profile_fingerprint = profile_fingerprint(
        input_audit,
        asset_audit=asset_audit,
        openmw_cfg=render_openmw_cfg(),
        settings_cfg=render_settings_cfg(),
    )
    if actual_profile_fingerprint != PINNED_PROFILE_FINGERPRINT:
        raise RuntimeError(
            "Poison Song profile fingerprint mismatch: expected "
            f"{PINNED_PROFILE_FINGERPRINT}, got {actual_profile_fingerprint}"
        )
    magick_provenance = _magick_version(magick)
    fingerprint = execution_provenance_fingerprint(
        profile_fingerprint=actual_profile_fingerprint,
        production_source_fingerprint_value=source_hash,
        image_id=image_info.image_id,
        image_repo_digests=image_info.repo_digests,
        magick_version=magick_provenance,
    )
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "rendererVersion": PRODUCTION_RENDERER_VERSION,
        "provenanceFingerprint": fingerprint,
        "profileFingerprint": actual_profile_fingerprint,
        "productionSourceFingerprint": source_hash,
        "openmwCommit": OPENMW_COMMIT,
        "image": {
            "requested": image_info.image,
            "id": image_info.image_id,
            "repoDigests": list(image_info.repo_digests),
            "os": image_info.os,
            "architecture": image_info.architecture,
            "labels": dict(sorted(image_info.labels.items())),
        },
        "magickVersion": magick_provenance,
        "inputAudit": input_audit,
        "assetAudit": asset_audit,
    }
    return ProductionProvenance(fingerprint=fingerprint, payload=payload)


def publish_provenance_receipt(
    output_root: Path,
    provenance: ProductionProvenance,
) -> Path:
    path = output_root / "provenance.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != provenance.payload:
            raise ValueError(
                f"Production provenance receipt does not match this run: {path}"
            )
        return path
    _atomic_write_json(path, provenance.payload)
    return path


def native_tile_for_cell(cell: Cell) -> TileKey:
    cell_x, cell_y = _validated_cell(cell)
    tile_x, tile_y = POISON_SONG_TILE_GRID.cell_to_tile(cell_x, cell_y)
    return TileKey(NATIVE_ZOOM, tile_x, tile_y)


def cell_for_native_tile(tile: TileKey) -> Cell:
    if tile.z != NATIVE_ZOOM:
        raise ValueError(f"Cell mapping is only defined at native zoom {NATIVE_ZOOM}")
    extent = POISON_SONG_TILE_GRID.tile_extent(tile.x, tile.y, tile.z)
    raw_x = extent.min_x / TES3_CELL_SIZE
    raw_y = extent.min_y / TES3_CELL_SIZE
    cell = (round(raw_x), round(raw_y))
    if abs(raw_x - cell[0]) > 1e-9 or abs(raw_y - cell[1]) > 1e-9:
        raise ValueError("Native tile is not aligned to TES3 exterior cells")
    if native_tile_for_cell(cell) != tile:
        raise ValueError("Native tile to cell mapping did not round-trip")
    return cell


def _validated_cell(value: object) -> Cell:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("A TES3 cell must be an x,y pair")
    x, y = value
    if any(not isinstance(item, int) or isinstance(item, bool) for item in (x, y)):
        raise ValueError("TES3 cell coordinates must be integers")
    return int(x), int(y)


def plan_native_targets(cells: Iterable[Cell]) -> tuple[NativeTarget, ...]:
    normalized = {_validated_cell(cell) for cell in cells}
    targets = [NativeTarget(cell, native_tile_for_cell(cell)) for cell in normalized]
    return tuple(sorted(targets, key=lambda item: (item.tile.y, item.tile.x)))


def _shard_center(cell: Cell) -> Cell:
    # Offset (2,2) minimizes the pinned effective LAND plan to 492 shards.  Each
    # center is divisible by three and owns [center-1, center+1].  Python //
    # preserves the same partition for negative TES3 coordinates.
    return 3 * ((cell[0] + 1) // 3), 3 * ((cell[1] + 1) // 3)


def group_targets_3x3(
    targets: Iterable[NativeTarget],
) -> tuple[RenderShard, ...]:
    grouped: dict[Cell, list[NativeTarget]] = defaultdict(list)
    seen: set[Cell] = set()
    for target in targets:
        if target.cell in seen:
            raise ValueError(f"Duplicate render target cell: {target.cell}")
        if target.tile != native_tile_for_cell(target.cell):
            raise ValueError(f"Target tile does not match cell {target.cell}")
        seen.add(target.cell)
        grouped[_shard_center(target.cell)].append(target)
    shards = [
        RenderShard(
            center,
            tuple(sorted(items, key=lambda item: (item.tile.y, item.tile.x))),
        )
        for center, items in grouped.items()
    ]
    return tuple(sorted(shards, key=lambda item: (item.center[1], item.center[0])))


def select_shards(
    shards: Sequence[RenderShard],
    *,
    shard_index: int = 0,
    shard_count: int = 1,
) -> tuple[RenderShard, ...]:
    """Select a stable modulo partition without renumbering after resume."""

    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must satisfy 0 <= index < shard_count")
    return tuple(
        shard
        for ordinal, shard in enumerate(shards)
        if ordinal % shard_count == shard_index
    )


def explicit_3x3_shard(center: Cell) -> RenderShard:
    center_x, center_y = _validated_cell(center)
    targets = plan_native_targets(
        (x, y)
        for y in range(center_y + 1, center_y - 2, -1)
        for x in range(center_x - 1, center_x + 2)
    )
    return RenderShard((center_x, center_y), targets)


def plan_fingerprint(targets: Sequence[NativeTarget]) -> str:
    ordered_targets = tuple(
        sorted(targets, key=lambda item: (item.tile.y, item.tile.x))
    )
    shards = group_targets_3x3(ordered_targets)
    payload = {
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "nativeZoom": NATIVE_ZOOM,
        "tilePixels": TILE_PIXELS,
        "origin": [POISON_SONG_TILE_GRID.origin_x, POISON_SONG_TILE_GRID.origin_y],
        "targets": [
            {
                "cell": list(target.cell),
                "tile": [target.tile.z, target.tile.x, target.tile.y],
            }
            for target in ordered_targets
        ],
        "shards": [
            {
                "center": list(shard.center),
                "cells": [list(target.cell) for target in shard.targets],
            }
            for shard in shards
        ],
    }
    return _sha256_bytes(_canonical_json_bytes(payload))


def pinned_poison_plugin_paths(source_root: Path) -> tuple[Path, ...]:
    """Resolve the exact pinned ESM load order without filesystem guessing."""

    result: list[Path] = []
    for content in CONTENT_FILES:
        candidates = [
            source_root / relative_root / content
            for relative_root in DATA_DIRECTORIES
            if (source_root / relative_root / content).is_file()
        ]
        if len(candidates) != 1:
            raise FileNotFoundError(
                f"Expected exactly one pinned {content}, found {len(candidates)}"
            )
        result.append(candidates[0])
    return tuple(result)


def derive_effective_exterior_cells(plugins: Sequence[Path]) -> tuple[Cell, ...]:
    """Apply TES3 CELL overrides/deletions in the supplied load order."""

    effective: dict[Cell, Path] = {}
    for plugin in (Path(value) for value in plugins):
        if not plugin.is_file():
            raise FileNotFoundError(f"Pinned plugin is missing: {plugin}")
        for record in iter_records(plugin):
            if record.record_type != b"CELL":
                continue
            data: bytes | None = None
            deleted = False
            for subrecord in iter_subrecords(record.payload):
                if subrecord.subrecord_type == b"FRMR":
                    break
                if subrecord.subrecord_type == b"DATA":
                    data = subrecord.payload
                elif subrecord.subrecord_type == b"DELE":
                    deleted = True
            if data is None:
                continue
            if len(data) < 12:
                raise ValueError(f"Truncated CELL DATA at {record.offset} in {plugin}")
            flags, cell_x, cell_y = struct.unpack_from("<Iii", data)
            if flags & 1:
                continue
            cell = (cell_x, cell_y)
            if deleted:
                effective.pop(cell, None)
            else:
                effective[cell] = plugin
    return tuple(sorted(effective, key=lambda item: (item[1], item[0])))


def derive_effective_land_cells(plugins: Sequence[Path]) -> tuple[Cell, ...]:
    """Return effective LAND coverage without retaining full vertex arrays."""

    dataset = load_terrain(tuple(Path(plugin) for plugin in plugins), wanted_cells=())
    return tuple(sorted(dataset.texture_usage, key=lambda item: (item[1], item[0])))


def load_supplied_cells(path: Path) -> tuple[Cell, ...]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("cells")
    if not isinstance(value, list):
        raise ValueError("Supplied cell JSON must be an array or an object with cells")
    return tuple(target.cell for target in plan_native_targets(_validated_cell(item) for item in value))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
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


def _atomic_write_json(path: Path, value: object) -> None:
    _atomic_write_bytes(path, _canonical_json_bytes(value) + b"\n")


def _atomic_write_text(path: Path, value: str) -> None:
    _atomic_write_bytes(path, value.encode("utf-8"))


def _webp_encoder(magick: str) -> ImageEncoder:
    return lambda image: encode_webp(
        image,
        executable=magick,
        lossless=True,
        quality=100,
        # Method 4 is still pixel-exact lossless. On the pinned Balmora tile it
        # is ~21x faster than method 6 for only ~1.3% more bytes.
        method=4,
    )


def _validate_webp(payload: bytes) -> None:
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        raise ValueError("Native tile encoder did not produce WebP")
    if int.from_bytes(payload[4:8], "little") + 8 != len(payload):
        raise ValueError("Native WebP has an inconsistent RIFF byte length")


def write_native_master(
    image: RgbaImage,
    output_path: Path,
    *,
    magick: str = "magick",
    encoder: ImageEncoder | None = None,
) -> tuple[int, str]:
    if (image.width, image.height) != (TILE_PIXELS, TILE_PIXELS):
        raise ValueError(
            f"Native master must be {TILE_PIXELS}x{TILE_PIXELS}, got "
            f"{image.width}x{image.height}"
        )
    encoded = (encoder or _webp_encoder(magick))(image)
    _validate_webp(encoded)
    _atomic_write_bytes(output_path, encoded)
    return len(encoded), _sha256_bytes(encoded)


def _target_relative_path(target: NativeTarget) -> str:
    return (Path("tiles") / target.tile.relative_path).as_posix()


def _artifact_for_file(output_root: Path, target: NativeTarget) -> TileArtifact:
    relative = _target_relative_path(target)
    path = output_root / relative
    if not path.is_file():
        raise FileNotFoundError(f"Completed tile is missing: {path}")
    return TileArtifact(
        target=target,
        relative_path=relative,
        byte_length=path.stat().st_size,
        sha256=_sha256_file(path),
    )


def _parse_checkpoint_artifact(
    value: object,
    *,
    targets_by_cell: Mapping[Cell, NativeTarget],
) -> TileArtifact:
    if not isinstance(value, dict):
        raise ValueError("Checkpoint artifact must be an object")
    cell = _validated_cell(value.get("cell"))
    target = targets_by_cell.get(cell)
    if target is None:
        raise ValueError(f"Checkpoint contains a cell outside its plan: {cell}")
    tile_value = value.get("tile")
    if not isinstance(tile_value, list) or len(tile_value) != 3:
        raise ValueError("Checkpoint tile must be a z,x,y array")
    tile = TileKey(*tile_value)
    if tile != target.tile:
        raise ValueError(f"Checkpoint tile mismatch for cell {cell}")
    relative = value.get("path")
    if relative != _target_relative_path(target):
        raise ValueError(f"Checkpoint path mismatch for cell {cell}")
    byte_length = value.get("bytes")
    digest = value.get("sha256")
    if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
        raise ValueError("Checkpoint artifact bytes must be positive")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError("Checkpoint artifact sha256 is invalid")
    return TileArtifact(target, relative, byte_length, digest)


def _validated_checkpoint_artifacts(
    *,
    output_root: Path,
    value: object,
    provenance_fingerprint: str,
    targets: Sequence[NativeTarget],
) -> dict[Cell, TileArtifact]:
    if not isinstance(value, dict):
        raise ValueError("Production checkpoint must be a JSON object")
    targets_by_cell = {target.cell: target for target in targets}
    expected_identity = {
        "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "rendererVersion": PRODUCTION_RENDERER_VERSION,
        "provenanceFingerprint": _validate_fingerprint(provenance_fingerprint),
        "planFingerprint": plan_fingerprint(targets),
    }
    for key, expected in expected_identity.items():
        if value.get(key) != expected:
            raise ValueError(
                f"Production checkpoint {key} mismatch: expected {expected!r}, "
                f"got {value.get(key)!r}"
            )
    completed = value.get("completed")
    if not isinstance(completed, list):
        raise ValueError("Production checkpoint completed must be an array")
    artifacts: dict[Cell, TileArtifact] = {}
    for item in completed:
        artifact = _parse_checkpoint_artifact(item, targets_by_cell=targets_by_cell)
        if artifact.target.cell in artifacts:
            raise ValueError(f"Duplicate checkpoint cell: {artifact.target.cell}")
        actual = _artifact_for_file(output_root, artifact.target)
        if (
            actual.relative_path != artifact.relative_path
            or actual.byte_length != artifact.byte_length
            or actual.sha256 != artifact.sha256
        ):
            raise ValueError(
                f"Checkpoint artifact mismatch for cell {artifact.target.cell}"
            )
        artifacts[artifact.target.cell] = artifact
    return artifacts


class _CheckpointSession:
    def __init__(
        self,
        *,
        output_root: Path,
        provenance_fingerprint: str,
        targets: Sequence[NativeTarget],
    ) -> None:
        self.output_root = output_root
        self.targets = tuple(targets)
        self.provenance_fingerprint = _validate_fingerprint(provenance_fingerprint)
        self.plan_fingerprint = plan_fingerprint(self.targets)
        self.path = output_root / "checkpoint.json"
        self._targets_by_cell = {target.cell: target for target in self.targets}
        self.completed: dict[Cell, TileArtifact] = {}
        self._load_or_create()

    @property
    def pending(self) -> tuple[NativeTarget, ...]:
        return tuple(target for target in self.targets if target.cell not in self.completed)

    def _load_or_create(self) -> None:
        if not self.path.exists():
            self._write()
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Production checkpoint is unreadable: {self.path}") from error
        self.completed.update(
            _validated_checkpoint_artifacts(
                output_root=self.output_root,
                value=value,
                provenance_fingerprint=self.provenance_fingerprint,
                targets=self.targets,
            )
        )

    def publish(
        self,
        target: NativeTarget,
        image: RgbaImage,
        *,
        magick: str,
        encoder: ImageEncoder | None = None,
    ) -> TileArtifact:
        if target not in self.targets:
            raise ValueError(f"Cannot publish a target outside the plan: {target.cell}")
        if target.cell in self.completed:
            return self.completed[target.cell]
        path = self.output_root / _target_relative_path(target)
        write_native_master(image, path, magick=magick, encoder=encoder)
        artifact = _artifact_for_file(self.output_root, target)
        self.completed[target.cell] = artifact
        self._write()
        return artifact

    def _write(self) -> None:
        completed = sorted(
            self.completed.values(),
            key=lambda item: (item.target.tile.y, item.target.tile.x),
        )
        payload = {
            "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "rendererVersion": PRODUCTION_RENDERER_VERSION,
            "provenanceFingerprint": self.provenance_fingerprint,
            "planFingerprint": self.plan_fingerprint,
            "targetCount": len(self.targets),
            "completed": [
                {
                    "cell": list(item.target.cell),
                    "tile": [item.target.tile.z, item.target.tile.x, item.target.tile.y],
                    "path": item.relative_path,
                    "bytes": item.byte_length,
                    "sha256": item.sha256,
                }
                for item in completed
            ],
        }
        _atomic_write_json(self.path, payload)


def _read_json_object(path: Path, label: str) -> tuple[bytes, dict[str, object]]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload, value


def _verified_provenance_fingerprint(value: Mapping[str, object]) -> str:
    image = value.get("image")
    if not isinstance(image, dict):
        raise ValueError("Production provenance image must be an object")
    profile_hash = value.get("profileFingerprint")
    source_hash = value.get("productionSourceFingerprint")
    image_id = image.get("id")
    repo_digests = image.get("repoDigests")
    magick_version = value.get("magickVersion")
    if not isinstance(profile_hash, str) or not isinstance(source_hash, str):
        raise ValueError("Production provenance source/profile fingerprint is invalid")
    if not isinstance(image_id, str) or not isinstance(magick_version, str):
        raise ValueError("Production provenance image/Magick identity is invalid")
    if not isinstance(repo_digests, list) or not all(
        isinstance(item, str) for item in repo_digests
    ):
        raise ValueError("Production provenance image repo digests are invalid")
    computed = execution_provenance_fingerprint(
        profile_fingerprint=profile_hash,
        production_source_fingerprint_value=source_hash,
        image_id=image_id,
        image_repo_digests=repo_digests,
        magick_version=magick_version,
    )
    if value.get("provenanceFingerprint") != computed:
        raise ValueError("Production provenance fingerprint does not recompute")
    return computed


def _validate_resume_provenance_compatibility(
    old: Mapping[str, object],
    new: Mapping[str, object],
) -> None:
    for key in (
        "schemaVersion",
        "datasetId",
        "snapshotId",
        "rendererVersion",
        "profileFingerprint",
        "openmwCommit",
        "magickVersion",
        "inputAudit",
        "assetAudit",
    ):
        if old.get(key) != new.get(key):
            raise ValueError(f"Resume migration changes incompatible provenance field {key}")
    old_image = old.get("image")
    new_image = new.get("image")
    if not isinstance(old_image, dict) or not isinstance(new_image, dict):
        raise ValueError("Resume migration provenance image is invalid")
    for key in ("requested", "os", "architecture"):
        if old_image.get(key) != new_image.get(key):
            raise ValueError(f"Resume migration changes incompatible image field {key}")
    old_labels = old_image.get("labels")
    new_labels = new_image.get("labels")
    if not isinstance(old_labels, dict) or not isinstance(new_labels, dict):
        raise ValueError("Resume migration image labels are invalid")
    ignored_label = "io.morrowind-map.production-fingerprint"
    if {k: v for k, v in old_labels.items() if k != ignored_label} != {
        k: v for k, v in new_labels.items() if k != ignored_label
    }:
        raise ValueError("Resume migration changes renderer image contract labels")
    if old.get("productionSourceFingerprint") == new.get(
        "productionSourceFingerprint"
    ):
        raise ValueError("Resume migration requires a changed production source")


def _write_immutable_backup(path: Path, payload: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise ValueError(f"Resume migration backup does not match: {path}")
        return
    _atomic_write_bytes(path, payload)


def migrate_resume_state(
    *,
    output_root: Path,
    cells: Iterable[Cell],
    new_provenance: ProductionProvenance,
    from_provenance_fingerprint: str,
    reason: str,
) -> dict[str, object]:
    """Explicitly adopt verified tiles after an output-compatible host change.

    Normal rendering never calls this function and remains fail-closed.  This
    migration requires the exact previous fingerprint, verifies every tile,
    preserves byte-identical backups, and records the old/new producer truth.
    """

    old_fingerprint = _validate_fingerprint(from_provenance_fingerprint)
    if not reason.strip():
        raise ValueError("Resume migration reason cannot be empty")
    if new_provenance.payload.get("provenanceFingerprint") != new_provenance.fingerprint:
        raise ValueError("New production provenance payload/fingerprint mismatch")
    _verified_provenance_fingerprint(new_provenance.payload)
    output_root = output_root.resolve()
    checkpoint_path = output_root / "checkpoint.json"
    provenance_path = output_root / "provenance.json"
    migration_root = output_root / "provenance-migrations" / old_fingerprint
    checkpoint_backup = migration_root / "checkpoint.json"
    provenance_backup = migration_root / "provenance.json"

    active_checkpoint_bytes, active_checkpoint = _read_json_object(
        checkpoint_path, "Production checkpoint"
    )
    active_provenance_bytes, active_provenance = _read_json_object(
        provenance_path, "Production provenance"
    )
    if checkpoint_backup.is_file():
        old_checkpoint_bytes, old_checkpoint = _read_json_object(
            checkpoint_backup, "Resume migration checkpoint backup"
        )
    else:
        old_checkpoint_bytes, old_checkpoint = active_checkpoint_bytes, active_checkpoint
    if provenance_backup.is_file():
        old_provenance_bytes, old_provenance = _read_json_object(
            provenance_backup, "Resume migration provenance backup"
        )
    else:
        old_provenance_bytes, old_provenance = active_provenance_bytes, active_provenance

    if _verified_provenance_fingerprint(old_provenance) != old_fingerprint:
        raise ValueError("Resume migration source provenance does not match --from-provenance")
    _validate_resume_provenance_compatibility(
        old_provenance,
        new_provenance.payload,
    )
    targets = plan_native_targets(cells)
    artifacts = _validated_checkpoint_artifacts(
        output_root=output_root,
        value=old_checkpoint,
        provenance_fingerprint=old_fingerprint,
        targets=targets,
    )
    new_checkpoint = dict(old_checkpoint)
    new_checkpoint["provenanceFingerprint"] = new_provenance.fingerprint
    new_checkpoint_bytes = _canonical_json_bytes(new_checkpoint) + b"\n"
    new_provenance_bytes = _canonical_json_bytes(new_provenance.payload) + b"\n"
    allowed_checkpoint_states = (old_checkpoint_bytes, new_checkpoint_bytes)
    allowed_provenance_states = (old_provenance_bytes, new_provenance_bytes)
    if active_checkpoint_bytes not in allowed_checkpoint_states:
        raise ValueError("Active checkpoint is neither pre- nor post-migration state")
    if active_provenance_bytes not in allowed_provenance_states:
        raise ValueError("Active provenance is neither pre- nor post-migration state")

    completed = old_checkpoint.get("completed")
    assert isinstance(completed, list)
    report: dict[str, object] = {
        "schemaVersion": 1,
        "status": "prepared",
        "reason": reason.strip(),
        "fromProvenanceFingerprint": old_fingerprint,
        "toProvenanceFingerprint": new_provenance.fingerprint,
        "planFingerprint": plan_fingerprint(targets),
        "completedArtifacts": len(artifacts),
        "completedArtifactBytes": sum(item.byte_length for item in artifacts.values()),
        "completedArtifactsSha256": _sha256_bytes(_canonical_json_bytes(completed)),
        "checkpointBeforeSha256": _sha256_bytes(old_checkpoint_bytes),
        "checkpointAfterSha256": _sha256_bytes(new_checkpoint_bytes),
        "provenanceBeforeSha256": _sha256_bytes(old_provenance_bytes),
        "provenanceAfterSha256": _sha256_bytes(new_provenance_bytes),
        "checkpointBackup": str(checkpoint_backup.relative_to(output_root)),
        "provenanceBackup": str(provenance_backup.relative_to(output_root)),
    }
    _write_immutable_backup(checkpoint_backup, old_checkpoint_bytes)
    _write_immutable_backup(provenance_backup, old_provenance_bytes)
    receipt_path = migration_root / "migration.json"
    _atomic_write_json(receipt_path, report)
    _atomic_write_bytes(checkpoint_path, new_checkpoint_bytes)
    _atomic_write_bytes(provenance_path, new_provenance_bytes)
    _validated_checkpoint_artifacts(
        output_root=output_root,
        value=new_checkpoint,
        provenance_fingerprint=new_provenance.fingerprint,
        targets=targets,
    )
    report["status"] = "complete"
    report["receipt"] = str(receipt_path.relative_to(output_root))
    _atomic_write_json(receipt_path, report)
    return report


def run_native_batch(
    *,
    output_root: Path,
    cells: Iterable[Cell],
    provenance_fingerprint: str,
    render_target: Callable[[NativeTarget], RgbaImage],
    magick: str = "magick",
    encoder: ImageEncoder | None = None,
) -> NativeBatchResult:
    """Testable/native producer seam with the same fail-closed checkpoint."""

    targets = plan_native_targets(cells)
    session = _CheckpointSession(
        output_root=output_root,
        provenance_fingerprint=provenance_fingerprint,
        targets=targets,
    )
    skipped = len(session.completed)
    rendered = 0
    for target in session.pending:
        session.publish(
            target,
            render_target(target),
            magick=magick,
            encoder=encoder,
        )
        rendered += 1
    return NativeBatchResult(len(targets), rendered, skipped, session.path)


def render_shard_manifest(
    shard: RenderShard,
    *,
    container_output_root: PurePosixPath = CONTAINER_OUTPUT_ROOT,
) -> str:
    lines = []
    for target in shard.targets:
        raw_path = _container_raw_path(target, container_output_root)
        lines.append(f"{target.cell[0]},{target.cell[1]}\t{raw_path}")
    return "\n".join(lines) + "\n"


def _container_raw_path(
    target: NativeTarget,
    output_root: PurePosixPath = CONTAINER_OUTPUT_ROOT,
) -> PurePosixPath:
    return (
        output_root
        / "raw"
        / str(target.tile.z)
        / str(target.tile.x)
        / f"{target.tile.y}.png"
    )


def prepare_shard_profile(output_root: Path, shard: RenderShard) -> Path:
    profile_root = output_root / "runs" / shard.key / "profile"
    if profile_root.exists():
        shutil.rmtree(profile_root)
    config_root = profile_root / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    (profile_root / "user-data").mkdir(parents=True, exist_ok=True)
    _atomic_write_text(config_root / "openmw.cfg", render_openmw_cfg())
    _atomic_write_text(config_root / "settings.cfg", render_settings_cfg())
    _atomic_write_text(profile_root / "commands.txt", render_console_script(shard.center))
    _atomic_write_text(profile_root / "export-targets.tsv", render_shard_manifest(shard))
    return profile_root


def _container_name(shard: RenderShard) -> str:
    return f"mwm5-{os.getpid()}-{shard.key}"[:128]


def docker_batch_command(
    *,
    image: str,
    source_root: Path,
    profile_root: Path,
    output_root: Path,
    shard: RenderShard,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        _container_name(shard),
        "--platform",
        DOCKER_PLATFORM,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "512",
        "--memory",
        "4g",
        "--tmpfs",
        "/tmp:rw,nosuid,size=1g",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--security-opt",
        "no-new-privileges",
    ]
    for relative in DATA_DIRECTORIES:
        command.extend(
            (
                "--mount",
                f"type=bind,src={source_root / relative},dst=/game/{relative},readonly",
            )
        )
    command.extend(
        (
            "--mount",
            f"type=bind,src={profile_root},dst=/profile",
            "--mount",
            f"type=bind,src={output_root},dst=/out",
            "--env",
            f"MWMAP_EXPORT_BATCH_FILE={CONTAINER_BATCH_FILE}",
            "--env",
            f"MWMAP_EXPORT_BATCH_CENTER={shard.center[0]},{shard.center[1]}",
            "--env",
            f"MWMAP_EXPORT_BATCH_ID={shard.key}",
            "--env",
            f"MWMAP_EXPORT_GUTTER_PIXELS={GUTTER_PIXELS}",
            "--env",
            "LIBGL_ALWAYS_SOFTWARE=1",
            "--env",
            "GALLIUM_DRIVER=llvmpipe",
            "--env",
            "OPENMW_DONT_PRECOMPILE=1",
            "--env",
            "OSG_THREADING=SingleThreaded",
            image,
        )
    )
    return command


def docker_build_command(
    *,
    repo_root: Path,
    image: str = DEFAULT_PRODUCTION_IMAGE,
    stage45_image: str = DEFAULT_STAGE45_IMAGE,
    stage45_image_id: str = "unverified",
) -> list[str]:
    source_hash = production_source_fingerprint(repo_root)
    return [
        "docker",
        "build",
        "--platform",
        DOCKER_PLATFORM,
        "--file",
        str(repo_root / "tools/openmw_renderer/Dockerfile.production"),
        "--tag",
        image,
        "--build-arg",
        f"STAGE45_IMAGE={stage45_image}",
        "--build-arg",
        f"STAGE45_IMAGE_ID={stage45_image_id}",
        "--build-arg",
        f"PRODUCTION_FINGERPRINT={source_hash}",
        str(repo_root),
    ]


def _raw_path(output_root: Path, target: NativeTarget) -> Path:
    return output_root / "raw" / str(target.tile.z) / str(target.tile.x) / f"{target.tile.y}.png"


def process_raw_master(raw_path: Path, *, magick: str = "magick") -> RgbaImage:
    raw = decode_texture(raw_path.read_bytes(), ".png", executable=magick)
    if (raw.width, raw.height) != (RAW_PIXELS, RAW_PIXELS):
        raise RuntimeError(
            f"Expected atomic OpenMW raw {RAW_PIXELS}x{RAW_PIXELS}, got "
            f"{raw.width}x{raw.height}: {raw_path}"
        )
    native = raw.crop(GUTTER_PIXELS, GUTTER_PIXELS, TILE_PIXELS, TILE_PIXELS)
    return apply_grade(native)


def production_resource_resolution_report(
    output_root: Path,
    *,
    expected_logs: Sequence[str],
) -> dict[str, object]:
    """Keep production fail-closed while auditing a known OpenMW NIF warning.

    OpenMW emits ``addAnimSource: can't find bone`` only after both the NIF and
    KF resources have loaded.  It skips that unmatched controller and continues;
    this is not evidence of a missing file.  Preserve every such line in the
    report, but do not mix it with actionable missing-resource messages.
    """

    report = resource_resolution_report(
        output_root,
        expected_logs=expected_logs,
    )
    missing = report.get("missingResourceMessages")
    if not isinstance(missing, list):
        raise RuntimeError("Resource resolution report has invalid messages")
    ignored: list[dict[str, str]] = []
    actionable: list[dict[str, str]] = []
    for item in missing:
        if not isinstance(item, dict) or not isinstance(item.get("line"), str):
            raise RuntimeError("Resource resolution report has an invalid message")
        if _BENIGN_ANIMATION_BONE_WARNING.search(item["line"]):
            ignored.append(item)
        else:
            actionable.append(item)
    report["missingResourceMessages"] = actionable
    report["ignoredCompatibilityWarnings"] = ignored
    report["passes"] = (
        bool(report.get("logsInspected"))
        and not report.get("missingExpectedLogs")
        and not actionable
    )
    return report


def _run_shard_process(
    *,
    image: str,
    source_root: Path,
    output_root: Path,
    shard: RenderShard,
    timeout_seconds: int,
) -> None:
    if timeout_seconds <= 0:
        raise ValueError("OpenMW shard timeout must be positive")
    profile_root = prepare_shard_profile(output_root, shard)
    raw_paths = [_raw_path(output_root, target) for target in shard.targets]
    for path in raw_paths:
        path.unlink(missing_ok=True)
        path.with_name(f"{path.name}.tmp.png").unlink(missing_ok=True)
    command = docker_batch_command(
        image=image,
        source_root=source_root,
        profile_root=profile_root,
        output_root=output_root,
        shard=shard,
    )
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        subprocess.run(
            ("docker", "rm", "-f", _container_name(shard)),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        output = error.stdout or ""
        _atomic_write_text(output_root / "logs" / f"{shard.key}.log", str(output))
        raise TimeoutError(f"OpenMW shard {shard.key} timed out") from error
    wrapper_log = output_root / "logs" / f"{shard.key}.log"
    _atomic_write_text(wrapper_log, completed.stdout or "")
    if completed.returncode != 0:
        raise RuntimeError(
            f"OpenMW shard {shard.key} failed with exit code {completed.returncode}"
        )
    engine_log = profile_root / "config/openmw.log"
    if not engine_log.is_file():
        raise RuntimeError(f"OpenMW shard {shard.key} produced no engine log")
    evidence = (completed.stdout or "") + "\n" + engine_log.read_text(
        encoding="utf-8",
        errors="replace",
    )
    missing_evidence: list[str] = []
    for target in shard.targets:
        target_marker = f"MWMAP export target {target.cell[0]},{target.cell[1]}:"
        complete_path = str(_container_raw_path(target))
        if target_marker not in evidence:
            missing_evidence.append(target_marker)
        if re.search(
            rf'MWMAP export complete:\s+"?{re.escape(complete_path)}"?', evidence
        ) is None:
            missing_evidence.append(f"MWMAP export complete: {complete_path}")
    if missing_evidence:
        raise RuntimeError(
            f"OpenMW shard {shard.key} is missing exact capture evidence: "
            + ", ".join(missing_evidence)
        )
    resource_audit = production_resource_resolution_report(
        output_root,
        expected_logs=(
            str(wrapper_log.relative_to(output_root)),
            str(engine_log.relative_to(output_root)),
        ),
    )
    _atomic_write_json(
        output_root / "runtime" / shard.key / "resource-resolution.json",
        resource_audit,
    )
    if not resource_audit["passes"]:
        raise RuntimeError(
            f"OpenMW shard {shard.key} reported missing resources: "
            + json.dumps(resource_audit, ensure_ascii=False, sort_keys=True)
        )
    missing = [str(path) for path in raw_paths if not path.is_file()]
    if missing:
        raise RuntimeError(
            f"OpenMW shard {shard.key} returned success with missing atomic outputs: "
            + ", ".join(missing)
        )
    temporary_outputs = [
        str(path.with_name(f"{path.name}.tmp.png"))
        for path in raw_paths
        if path.with_name(f"{path.name}.tmp.png").exists()
    ]
    if temporary_outputs:
        raise RuntimeError(
            f"OpenMW shard {shard.key} left unpublished raw files: "
            + ", ".join(temporary_outputs)
        )
    runtime_root = output_root / "runtime" / shard.key
    for name in (
        "memory.peak",
        "process.json",
        "glxinfo.txt",
        "resource-resolution.json",
    ):
        if not (runtime_root / name).is_file():
            raise RuntimeError(
                f"OpenMW shard {shard.key} is missing runtime evidence {name}"
            )
    read_shard_runtime(output_root, shard.key)


def read_shard_runtime(output_root: Path, shard_key: str) -> ShardRuntimeEvidence:
    runtime_root = output_root / "runtime" / shard_key
    try:
        memory_text = (runtime_root / "memory.peak").read_text(
            encoding="ascii"
        ).strip()
        process = json.loads(
            (runtime_root / "process.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"OpenMW shard {shard_key} has unreadable runtime evidence"
        ) from error
    if not memory_text.isdigit() or int(memory_text) <= 0:
        raise RuntimeError(
            f"OpenMW shard {shard_key} has no usable cgroup memory peak"
        )
    if not isinstance(process, dict):
        raise RuntimeError(f"OpenMW shard {shard_key} process evidence is not an object")
    elapsed = process.get("elapsedSeconds")
    exit_code = process.get("exitCode")
    if (
        not isinstance(elapsed, int)
        or isinstance(elapsed, bool)
        or elapsed <= 0
        or exit_code != 0
    ):
        raise RuntimeError(
            f"OpenMW shard {shard_key} has invalid process evidence: {process!r}"
        )
    return ShardRuntimeEvidence(
        shard_key=shard_key,
        elapsed_seconds=elapsed,
        memory_peak_bytes=int(memory_text),
    )


def run_openmw_production(
    *,
    source_root: Path,
    output_root: Path,
    cells: Iterable[Cell],
    provenance_fingerprint: str,
    image: str = DEFAULT_PRODUCTION_IMAGE,
    magick: str = "magick",
    timeout_seconds: int = 15 * 60,
    retain_raw: bool = False,
    max_shards: int | None = None,
    workers: int = 1,
    shard_index: int = 0,
    shard_count: int = 1,
    progress: ProgressCallback | None = None,
) -> NativeBatchResult:
    if workers <= 0:
        raise ValueError("workers must be positive")
    targets = plan_native_targets(cells)
    session = _CheckpointSession(
        output_root=output_root,
        provenance_fingerprint=provenance_fingerprint,
        targets=targets,
    )
    skipped = len(session.completed)
    if progress is not None:
        progress(skipped, len(targets))
    planned_shards = group_targets_3x3(targets)
    selected_shards = select_shards(
        planned_shards,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    pending_cells = {target.cell for target in session.pending}
    shards = [
        RenderShard(
            shard.center,
            tuple(target for target in shard.targets if target.cell in pending_cells),
        )
        for shard in selected_shards
        if any(target.cell in pending_cells for target in shard.targets)
    ]
    if max_shards is not None:
        if max_shards <= 0:
            raise ValueError("max_shards must be positive")
        shards = shards[:max_shards]
    rendered = 0

    def execute(shard: RenderShard) -> RenderShard:
        _run_shard_process(
            image=image,
            source_root=source_root,
            output_root=output_root,
            shard=shard,
            timeout_seconds=timeout_seconds,
        )
        return shard

    def completed_shards() -> Iterable[RenderShard]:
        if workers == 1:
            for shard in shards:
                yield execute(shard)
            return
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="openmw-shard",
        ) as executor:
            pending: deque[tuple[RenderShard, Future[RenderShard]]] = deque()
            iterator = iter(shards)
            for _ in range(workers):
                try:
                    shard = next(iterator)
                except StopIteration:
                    break
                pending.append((shard, executor.submit(execute, shard)))
            while pending:
                shard, future = pending.popleft()
                completed = future.result()
                try:
                    next_shard = next(iterator)
                except StopIteration:
                    pass
                else:
                    pending.append((next_shard, executor.submit(execute, next_shard)))
                # Keep the renderer queue full while the caller crops, grades,
                # encodes and publishes the completed shard.
                yield completed

    for shard in completed_shards():
        # Decode every result before publishing any of the shard. A partial or
        # malformed OpenMW batch therefore cannot advance the checkpoint.
        def prepare_output(target: NativeTarget) -> tuple[RgbaImage, bytes]:
            image = process_raw_master(_raw_path(output_root, target), magick=magick)
            encoded = _webp_encoder(magick)(image)
            _validate_webp(encoded)
            return image, encoded

        if workers == 1:
            prepared = {target: prepare_output(target) for target in shard.targets}
        else:
            with ThreadPoolExecutor(
                max_workers=min(workers, len(shard.targets)),
                thread_name_prefix="webp-tile",
            ) as encoder_pool:
                prepared = dict(
                    zip(
                        shard.targets,
                        encoder_pool.map(prepare_output, shard.targets),
                        strict=True,
                    )
                )
        for target in shard.targets:
            native_image, encoded = prepared[target]
            session.publish(
                target,
                native_image,
                magick=magick,
                encoder=lambda _image, payload=encoded: payload,
            )
            rendered += 1
        if not retain_raw:
            for target in shard.targets:
                _raw_path(output_root, target).unlink(missing_ok=True)
        if progress is not None:
            progress(skipped + rendered, len(targets))
    return NativeBatchResult(
        len(targets),
        rendered,
        skipped,
        session.path,
        len(planned_shards),
        len(selected_shards),
        workers,
    )


def _downsample_half(image: RgbaImage) -> RgbaImage:
    if image.width % 2 or image.height % 2:
        raise ValueError("Pyramid child dimensions must be even")
    target_width = image.width // 2
    target_height = image.height // 2
    result = bytearray(target_width * target_height * 4)
    source = image.pixels
    source_stride = image.width * 4
    for target_y in range(target_height):
        source_y = target_y * 2
        for target_x in range(target_width):
            source_x = target_x * 2
            offsets = (
                source_y * source_stride + source_x * 4,
                source_y * source_stride + (source_x + 1) * 4,
                (source_y + 1) * source_stride + source_x * 4,
                (source_y + 1) * source_stride + (source_x + 1) * 4,
            )
            alpha_sum = sum(source[offset + 3] for offset in offsets)
            target_offset = (target_y * target_width + target_x) * 4
            if alpha_sum:
                for channel in range(3):
                    weighted = sum(
                        source[offset + channel] * source[offset + 3]
                        for offset in offsets
                    )
                    result[target_offset + channel] = (
                        weighted + alpha_sum // 2
                    ) // alpha_sum
            result[target_offset + 3] = (alpha_sum + 2) // 4
    return RgbaImage(target_width, target_height, bytes(result))


def compose_parent(children: Mapping[tuple[int, int], RgbaImage]) -> RgbaImage:
    """Compose sparse XYZ children into top-left-origin parent quadrants."""

    allowed = {(0, 0), (1, 0), (0, 1), (1, 1)}
    if not children or not set(children).issubset(allowed):
        raise ValueError("Parent children must use one or more XYZ quadrants")
    parent = bytearray(TILE_PIXELS * TILE_PIXELS * 4)
    quadrant_pixels = TILE_PIXELS // 2
    parent_stride = TILE_PIXELS * 4
    row_bytes = quadrant_pixels * 4
    for (quadrant_x, quadrant_y), child in children.items():
        if (child.width, child.height) != (TILE_PIXELS, TILE_PIXELS):
            raise ValueError("Every pyramid child must be a native 512px tile")
        half = _downsample_half(child)
        for row in range(quadrant_pixels):
            source_offset = row * row_bytes
            target_offset = (
                (quadrant_y * quadrant_pixels + row) * parent_stride
                + quadrant_x * row_bytes
            )
            parent[target_offset : target_offset + row_bytes] = half.pixels[
                source_offset : source_offset + row_bytes
            ]
    return RgbaImage(TILE_PIXELS, TILE_PIXELS, bytes(parent))


def _default_webp_reader(path: Path, *, magick: str) -> RgbaImage:
    image = decode_texture(path.read_bytes(), ".webp", executable=magick)
    if (image.width, image.height) != (TILE_PIXELS, TILE_PIXELS):
        raise ValueError(f"Pyramid child is not 512px: {path}")
    return image


def build_lower_zoom_level(
    *,
    tile_root: Path,
    child_tiles: Iterable[TileKey],
    magick: str = "magick",
    reader: ImageReader | None = None,
    encoder: ImageEncoder | None = None,
) -> tuple[TileKey, ...]:
    children = tuple(sorted(set(child_tiles)))
    if not children:
        return ()
    child_zoom = children[0].z
    if child_zoom <= 0 or any(tile.z != child_zoom for tile in children):
        raise ValueError("Lower zoom input must contain one positive zoom level")
    grouped: dict[TileKey, dict[tuple[int, int], TileKey]] = defaultdict(dict)
    for child in children:
        parent = TileKey(child.z - 1, child.x // 2, child.y // 2)
        quadrant = (child.x - parent.x * 2, child.y - parent.y * 2)
        grouped[parent][quadrant] = child
    read = reader or (lambda path: _default_webp_reader(path, magick=magick))
    parents: list[TileKey] = []
    for parent in sorted(grouped):
        images = {
            quadrant: read(tile_root / child.relative_path)
            for quadrant, child in grouped[parent].items()
        }
        composed = compose_parent(images)
        write_native_master(
            composed,
            tile_root / parent.relative_path,
            magick=magick,
            encoder=encoder,
        )
        parents.append(parent)
    return tuple(parents)


def build_pyramid(
    *,
    tile_root: Path,
    native_tiles: Iterable[TileKey],
    min_zoom: int = MIN_ZOOM,
    magick: str = "magick",
    reader: ImageReader | None = None,
    encoder: ImageEncoder | None = None,
) -> tuple[TileKey, ...]:
    if not 0 <= min_zoom <= NATIVE_ZOOM:
        raise ValueError("Minimum pyramid zoom is outside the supported range")
    current = tuple(sorted(set(native_tiles)))
    if any(tile.z != NATIVE_ZOOM for tile in current):
        raise ValueError("Pyramid masters must all be native z7 tiles")
    all_tiles = list(current)
    while current and current[0].z > min_zoom:
        current = build_lower_zoom_level(
            tile_root=tile_root,
            child_tiles=current,
            magick=magick,
            reader=reader,
            encoder=encoder,
        )
        all_tiles.extend(current)
    return tuple(sorted(all_tiles))


def build_inventory(
    *,
    output_root: Path,
    tiles: Iterable[TileKey],
    provenance_fingerprint: str,
    plan_fingerprint_value: str,
) -> TileInventory:
    _validate_fingerprint(provenance_fingerprint)
    _validate_fingerprint(plan_fingerprint_value, "plan fingerprint")
    entries = []
    for tile in sorted(set(tiles)):
        relative = Path("tiles") / tile.relative_path
        path = output_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Inventory tile is missing: {path}")
        entries.append(
            {
                "z": tile.z,
                "x": tile.x,
                "y": tile.y,
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    core = {
        "schemaVersion": INVENTORY_SCHEMA_VERSION,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "rendererVersion": PRODUCTION_RENDERER_VERSION,
        "provenanceFingerprint": provenance_fingerprint,
        "planFingerprint": plan_fingerprint_value,
        "tileFormat": "image/webp",
        "tilePixels": TILE_PIXELS,
        "minZoom": min((entry["z"] for entry in entries), default=MIN_ZOOM),
        "maxZoom": max((entry["z"] for entry in entries), default=NATIVE_ZOOM),
        "origin": [POISON_SONG_TILE_GRID.origin_x, POISON_SONG_TILE_GRID.origin_y],
        "extent": list(POISON_WORLD_EXTENT),
        "tileCount": len(entries),
        "totalBytes": sum(int(entry["bytes"]) for entry in entries),
        "tiles": entries,
    }
    payload = dict(core)
    payload["inventorySha256"] = _sha256_bytes(_canonical_json_bytes(core))
    return TileInventory(payload)


def finalize_production(
    *,
    output_root: Path,
    cells: Iterable[Cell],
    provenance_fingerprint: str,
    min_zoom: int = MIN_ZOOM,
    magick: str = "magick",
) -> TileInventory:
    targets = plan_native_targets(cells)
    session = _CheckpointSession(
        output_root=output_root,
        provenance_fingerprint=provenance_fingerprint,
        targets=targets,
    )
    if session.pending:
        raise RuntimeError(
            f"Cannot finalize with {len(session.pending)} native tiles still pending"
        )
    tiles = build_pyramid(
        tile_root=output_root / "tiles",
        native_tiles=(target.tile for target in targets),
        min_zoom=min_zoom,
        magick=magick,
    )
    inventory = build_inventory(
        output_root=output_root,
        tiles=tiles,
        provenance_fingerprint=provenance_fingerprint,
        plan_fingerprint_value=session.plan_fingerprint,
    )
    _atomic_write_json(output_root / "inventory.json", inventory.payload)
    return inventory


def plan_report(cells: Iterable[Cell]) -> dict[str, object]:
    targets = plan_native_targets(cells)
    shards = group_targets_3x3(targets)
    return {
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "nativeZoom": NATIVE_ZOOM,
        "tilePixels": TILE_PIXELS,
        "targetCount": len(targets),
        "shardCount": len(shards),
        "planFingerprint": plan_fingerprint(targets),
        "shards": [
            {
                "key": shard.key,
                "center": list(shard.center),
                "targetCount": len(shard.targets),
                "cells": [list(target.cell) for target in shard.targets],
            }
            for shard in shards
        ],
    }


def _cells_for_args(args: argparse.Namespace) -> tuple[Cell, ...]:
    if args.cells is not None:
        return load_supplied_cells(args.cells)
    plugins = pinned_poison_plugin_paths(args.source_root.resolve())
    if args.coverage == "cell":
        return derive_effective_exterior_cells(plugins)
    return derive_effective_land_cells(plugins)


def _parse_cell(value: str) -> Cell:
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("cell must use exact x,y syntax")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as error:
        raise argparse.ArgumentTypeError("cell coordinates must be integers") from error


def _add_source_and_cells(parser: argparse.ArgumentParser, repo_root: Path) -> None:
    parser.add_argument(
        "--source-root",
        type=Path,
        default=repo_root.parent / "morr-dev",
    )
    parser.add_argument(
        "--cells",
        type=Path,
        help="Optional deterministic JSON cell set; otherwise derive pinned CELL coverage.",
    )
    parser.add_argument(
        "--coverage",
        choices=("land", "cell"),
        default="land",
        help="Default derivation source when --cells is omitted (default: effective LAND).",
    )


def _add_runtime_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--image", default=DEFAULT_PRODUCTION_IMAGE)
    parser.add_argument("--magick", default="magick")
    parser.add_argument(
        "--provenance-fingerprint",
        help=(
            "Optional expected SHA-256. The runner always derives the exact "
            "profile/source/image/encoder identity and rejects a mismatch."
        ),
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Stage 5 Poison Song production renderer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Derive and print the immutable coverage/shard plan")
    _add_source_and_cells(plan, repo_root)
    plan.add_argument("--output-plan", type=Path)

    build = subparsers.add_parser("build", help="Build the incremental Stage 5 OpenMW image")
    build.add_argument("--image", default=DEFAULT_PRODUCTION_IMAGE)
    build.add_argument("--stage45-image", default=DEFAULT_STAGE45_IMAGE)

    provenance = subparsers.add_parser(
        "provenance",
        help="Validate the exact profile/image/encoder and print its resume identity.",
    )
    provenance.add_argument("--source-root", type=Path, default=repo_root.parent / "morr-dev")
    provenance.add_argument("--output", type=Path)
    _add_runtime_identity(provenance)

    for name in ("render", "finalize"):
        command = subparsers.add_parser(name)
        _add_source_and_cells(command, repo_root)
        command.add_argument("--output", type=Path, default=repo_root / DEFAULT_OUTPUT)
        _add_runtime_identity(command)

    render = subparsers.choices["render"]
    render.add_argument("--timeout-seconds", type=int, default=15 * 60)
    render.add_argument("--retain-raw", action="store_true")
    render.add_argument("--max-shards", type=int)
    render.add_argument("--workers", type=int, default=1)
    render.add_argument("--shard-index", type=int, default=0)
    render.add_argument("--shard-count", type=int, default=1)

    finalize = subparsers.choices["finalize"]
    finalize.add_argument("--min-zoom", type=int, default=MIN_ZOOM)

    migrate = subparsers.add_parser(
        "migrate-resume",
        help="Explicitly adopt a verified checkpoint after an output-compatible host change.",
    )
    _add_source_and_cells(migrate, repo_root)
    migrate.add_argument("--output", type=Path, default=repo_root / DEFAULT_OUTPUT)
    _add_runtime_identity(migrate)
    migrate.add_argument("--from-provenance", required=True)
    migrate.add_argument("--reason", required=True)

    smoke = subparsers.add_parser(
        "smoke",
        help="Render one explicit nine-target 3x3 shard in one OpenMW process.",
    )
    smoke.add_argument("--source-root", type=Path, default=repo_root.parent / "morr-dev")
    smoke.add_argument("--output", type=Path, default=repo_root / DEFAULT_OUTPUT / "smoke")
    smoke.add_argument("--center", type=_parse_cell, default=(-3, -3))
    _add_runtime_identity(smoke)
    smoke.add_argument("--timeout-seconds", type=int, default=15 * 60)
    smoke.add_argument("--retain-raw", action="store_true")
    return parser.parse_args(argv)


def _resolve_cli_provenance(
    args: argparse.Namespace,
    *,
    repo_root: Path,
) -> ProductionProvenance:
    provenance = _derive_cli_provenance(args, repo_root=repo_root)
    if args.output is not None:
        publish_provenance_receipt(args.output.resolve(), provenance)
    return provenance


def _derive_cli_provenance(
    args: argparse.Namespace,
    *,
    repo_root: Path,
) -> ProductionProvenance:
    provenance = resolve_production_provenance(
        repo_root=repo_root,
        source_root=args.source_root.resolve(),
        image=args.image,
        magick=args.magick,
    )
    expected = args.provenance_fingerprint
    if expected is not None:
        _validate_fingerprint(expected)
        if expected != provenance.fingerprint:
            raise ValueError(
                "Expected provenance fingerprint does not match the validated run: "
                f"expected {expected}, got {provenance.fingerprint}"
            )
    return provenance


def _print_render_progress(completed: int, total: int) -> None:
    print(f"[{completed}/{total}]", file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    if args.command == "build":
        base_info = stage45_docker_image_info(
            args.stage45_image,
            expected_renderer_hash=renderer_fingerprint(repo_root),
        )
        if not base_info.contract_passes:
            raise RuntimeError(
                "Stage 4.5 base image identity check failed: "
                + "; ".join(base_info.contract_errors)
            )
        immutable_base = (
            "morrowind-map-openmw:stage45-parent-"
            + base_info.image_id.removeprefix("sha256:")[:16]
        )
        subprocess.run(
            ("docker", "tag", base_info.image_id, immutable_base),
            check=True,
        )
        completed = subprocess.run(
            docker_build_command(
                repo_root=repo_root,
                image=args.image,
                stage45_image=immutable_base,
                stage45_image_id=base_info.image_id,
            ),
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
        image_info = production_image_info(
            args.image,
            expected_source_fingerprint=production_source_fingerprint(repo_root),
        )
        if not image_info.contract_passes:
            raise RuntimeError(
                "Built production image identity check failed: "
                + "; ".join(image_info.contract_errors)
            )
        print(json.dumps(asdict(image_info), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "provenance":
        provenance = _resolve_cli_provenance(args, repo_root=repo_root)
        print(json.dumps(provenance.payload, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "smoke":
        if args.center != _shard_center(args.center):
            raise ValueError("Smoke center must be divisible by three for the offset-(2,2) grid")
        shard = explicit_3x3_shard(args.center)
        provenance = _resolve_cli_provenance(args, repo_root=repo_root)
        result = run_openmw_production(
            source_root=args.source_root.resolve(),
            output_root=args.output.resolve(),
            cells=(target.cell for target in shard.targets),
            provenance_fingerprint=provenance.fingerprint,
            image=args.image,
            magick=args.magick,
            timeout_seconds=args.timeout_seconds,
            retain_raw=args.retain_raw,
            max_shards=1,
        )
        print(json.dumps(asdict(result), default=str, sort_keys=True))
        return 0

    cells = _cells_for_args(args)
    if args.command == "migrate-resume":
        print(
            "[setup] validating new renderer identity and existing checkpoint",
            file=sys.stderr,
            flush=True,
        )
        provenance = _derive_cli_provenance(args, repo_root=repo_root)
        report = migrate_resume_state(
            output_root=args.output.resolve(),
            cells=cells,
            new_provenance=provenance,
            from_provenance_fingerprint=args.from_provenance,
            reason=args.reason,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "plan":
        report = plan_report(cells)
        if args.output_plan is not None:
            _atomic_write_json(args.output_plan.resolve(), report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "render":
        print(
            "[setup] validating renderer image, profile and assets",
            file=sys.stderr,
            flush=True,
        )
        provenance = _resolve_cli_provenance(args, repo_root=repo_root)
        result = run_openmw_production(
            source_root=args.source_root.resolve(),
            output_root=args.output.resolve(),
            cells=cells,
            provenance_fingerprint=provenance.fingerprint,
            image=args.image,
            magick=args.magick,
            timeout_seconds=args.timeout_seconds,
            retain_raw=args.retain_raw,
            max_shards=args.max_shards,
            workers=args.workers,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            progress=_print_render_progress,
        )
        print(json.dumps(asdict(result), default=str, sort_keys=True))
        return 0
    if args.command == "finalize":
        provenance = _resolve_cli_provenance(args, repo_root=repo_root)
        inventory = finalize_production(
            output_root=args.output.resolve(),
            cells=cells,
            provenance_fingerprint=provenance.fingerprint,
            min_zoom=args.min_zoom,
            magick=args.magick,
        )
        print(json.dumps(inventory.payload, ensure_ascii=False, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
