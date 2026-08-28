from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.land_renderer.terrain import RgbaImage
from tools.openmw_renderer.production import (
    DATASET_ID,
    DEFAULT_OUTPUT,
    MIN_ZOOM,
    NATIVE_ZOOM,
    SNAPSHOT_ID,
    TILE_PIXELS,
    TileKey,
    _atomic_write_bytes,
    _atomic_write_json,
    _default_webp_reader,
    _magick_version,
    _sha256_file,
    _shard_center,
    build_inventory,
    build_lower_zoom_level,
    cell_for_native_tile,
    production_source_fingerprint,
    write_native_master,
)
from tools.openmw_renderer.publish import ValidatedInventory, validate_source


STABILIZER_SCHEMA_VERSION = 2
STABILIZER_VERSION = "cross-shard-linear-feather-v1"
STABILIZATION_RECEIPT = "seam-stabilization.json"
STABILIZATION_ROOT = Path("seam-stabilization")
SOURCE_INVENTORY_PATH = STABILIZATION_ROOT / "source-inventory.json"
TILE_TRANSFORMS_PATH = STABILIZATION_ROOT / "tile-transforms.ndjson"
DEFAULT_STABILIZED_OUTPUT = Path("local-data/openmw-release") / DATASET_ID
EXPECTED_CROSS_SHARD_EDGES = 2571

ProgressCallback = Callable[[str], None]
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, order=True, slots=True)
class CrossShardEdge:
    first: TileKey
    second: TileKey
    direction: str

    @property
    def identifier(self) -> str:
        return (
            f"{self.first.z}/{self.first.x}/{self.first.y}:{self.direction}:"
            f"{self.second.z}/{self.second.x}/{self.second.y}"
        )


@dataclass(frozen=True, slots=True)
class TileEdges:
    west_inner: bytes
    east_inner: bytes
    north_inner: bytes
    south_inner: bytes


@dataclass(frozen=True, slots=True)
class StabilizationResult:
    output_root: Path
    inventory_sha256: str
    receipt_sha256: str
    cross_shard_edges: int
    touched_native_tiles: int
    changed_native_tiles: int
    created: bool


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stabilizer_implementation_sha256() -> str:
    return _sha256_file(Path(__file__).resolve())


def _webp_coder_identity(executable: str) -> str:
    completed = subprocess.run(
        (executable, "identify", "-list", "format"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )
    matches = [
        " ".join(line.split())
        for line in (completed.stdout or "").splitlines()
        if re.match(r"^\s*WEBP\*?\s+", line)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one ImageMagick WEBP coder, found {len(matches)}"
        )
    return matches[0]


def _resolve_stabilization_toolchain(
    *,
    repo_root: Path,
    magick: str,
    expected_production_source_fingerprint: str,
    expected_magick_version: str,
) -> tuple[str, dict[str, object]]:
    executable = shutil.which(magick)
    if executable is None:
        raise FileNotFoundError(f"ImageMagick executable not found: {magick}")
    resolved = str(Path(executable).resolve(strict=True))
    current_source = production_source_fingerprint(repo_root)
    current_magick = _magick_version(resolved)
    if current_source != expected_production_source_fingerprint:
        raise ValueError(
            "Seam stabilization production source differs from render provenance"
        )
    if current_magick != expected_magick_version:
        raise ValueError(
            "Seam stabilization ImageMagick differs from render provenance"
        )
    return resolved, {
        "productionSourceFingerprint": current_source,
        "imageMagick": {
            "version": current_magick,
            "webpCoder": _webp_coder_identity(resolved),
            "executableSha256": _sha256_file(Path(resolved)),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
    }


def _source_snapshot_identity(inventory: ValidatedInventory) -> dict[str, object]:
    return {
        "inventorySha256": inventory.inventory_sha256,
        "inventoryFileSha256": inventory.inventory_file_sha256,
        "provenanceFileSha256": inventory.provenance_file_sha256,
        "planFileSha256": inventory.plan_file_sha256,
        "provenanceFingerprint": inventory.provenance_fingerprint,
        "planFingerprint": inventory.plan_fingerprint,
        "tileCount": inventory.tile_count,
        "totalBytes": inventory.total_bytes,
    }


def _require_matching_source_snapshot(
    source: ValidatedInventory,
    snapshot: ValidatedInventory,
) -> None:
    if _source_snapshot_identity(source) != _source_snapshot_identity(snapshot):
        raise RuntimeError("Production dataset changed while creating stabilization snapshot")


def _require_stabilization_inputs_unchanged(
    *,
    implementation_sha256: str,
    resolved_magick: str,
    toolchain: Mapping[str, object],
    repo_root: Path,
    expected_production_source_fingerprint: str,
    expected_magick_version: str,
) -> None:
    if stabilizer_implementation_sha256() != implementation_sha256:
        raise RuntimeError("Seam stabilizer implementation changed during execution")
    current_magick, current_toolchain = _resolve_stabilization_toolchain(
        repo_root=repo_root,
        magick=resolved_magick,
        expected_production_source_fingerprint=expected_production_source_fingerprint,
        expected_magick_version=expected_magick_version,
    )
    if current_magick != resolved_magick or current_toolchain != dict(toolchain):
        raise RuntimeError("Seam stabilization toolchain changed during execution")


def _column(image: RgbaImage, x: int) -> bytes:
    result = bytearray(image.height * 4)
    for y in range(image.height):
        source = (y * image.width + x) * 4
        result[y * 4 : y * 4 + 4] = image.pixels[source : source + 4]
    return bytes(result)


def _row(image: RgbaImage, y: int) -> bytes:
    start = y * image.width * 4
    return image.pixels[start : start + image.width * 4]


def _pixel(line: bytes | bytearray, index: int) -> bytes:
    start = index * 4
    return bytes(line[start : start + 4])


def _set_pixel(line: bytearray, index: int, value: bytes) -> None:
    start = index * 4
    line[start : start + 4] = value


def _blend_pixel(first: bytes, second: bytes, *, first_weight: int) -> bytes:
    """Blend two RGBA pixels in premultiplied-alpha space with a /3 kernel."""

    if len(first) != 4 or len(second) != 4 or first_weight not in (1, 2):
        raise ValueError("Seam pixels require two RGBA values and a 1:2 kernel")
    if first == second:
        return first
    second_weight = 3 - first_weight
    alpha_weighted = first_weight * first[3] + second_weight * second[3]
    alpha = (alpha_weighted + 1) // 3
    if alpha_weighted == 0:
        return bytes((0, 0, 0, 0))
    channels = []
    for channel in range(3):
        premultiplied = (
            first_weight * first[channel] * first[3]
            + second_weight * second[channel] * second[3]
        )
        channels.append(min(255, (premultiplied + alpha_weighted // 2) // alpha_weighted))
    return bytes((*channels, alpha))


def _blend_lines(first: bytes, second: bytes, *, first_weight: int) -> bytes:
    if len(first) != len(second) or len(first) % 4:
        raise ValueError("Seam anchor lines must have equal RGBA lengths")
    result = bytearray(len(first))
    for index in range(len(first) // 4):
        _set_pixel(
            result,
            index,
            _blend_pixel(
                _pixel(first, index),
                _pixel(second, index),
                first_weight=first_weight,
            ),
        )
    return bytes(result)


def cross_shard_edges(tiles: Iterable[TileKey]) -> tuple[CrossShardEdge, ...]:
    native = {tile for tile in tiles if tile.z == NATIVE_ZOOM}
    result: list[CrossShardEdge] = []
    for tile in sorted(native):
        for direction, neighbor in (
            ("east", TileKey(tile.z, tile.x + 1, tile.y)),
            ("north", TileKey(tile.z, tile.x, tile.y - 1)),
        ):
            if neighbor not in native:
                continue
            if _shard_center(cell_for_native_tile(tile)) == _shard_center(
                cell_for_native_tile(neighbor)
            ):
                continue
            result.append(CrossShardEdge(tile, neighbor, direction))
    return tuple(sorted(result))


def border_neighbors(
    edges: Iterable[CrossShardEdge],
) -> dict[TileKey, dict[str, TileKey]]:
    result: dict[TileKey, dict[str, TileKey]] = {}
    for edge in edges:
        first = result.setdefault(edge.first, {})
        second = result.setdefault(edge.second, {})
        if edge.direction == "east":
            first["east"] = edge.second
            second["west"] = edge.first
        elif edge.direction == "north":
            first["north"] = edge.second
            second["south"] = edge.first
        else:
            raise ValueError(f"Unsupported seam direction: {edge.direction}")
    return result


def _extract_edges(image: RgbaImage) -> TileEdges:
    if (image.width, image.height) != (TILE_PIXELS, TILE_PIXELS):
        raise ValueError("Seam stabilization requires native 512px tiles")
    return TileEdges(
        west_inner=_column(image, 1),
        east_inner=_column(image, TILE_PIXELS - 2),
        north_inner=_row(image, 1),
        south_inner=_row(image, TILE_PIXELS - 2),
    )


def _corrected_anchor_row(
    tile: TileKey,
    side: str,
    *,
    edges: Mapping[TileKey, TileEdges],
    neighbors: Mapping[TileKey, Mapping[str, TileKey]],
) -> bytes:
    own = edges[tile]
    if side == "north":
        row = bytearray(own.north_inner)
        y = 1
    elif side == "south":
        row = bytearray(own.south_inner)
        y = TILE_PIXELS - 2
    else:
        raise ValueError(f"Unsupported anchor side: {side}")
    tile_neighbors = neighbors.get(tile, {})
    west = tile_neighbors.get("west")
    if west is not None:
        _set_pixel(
            row,
            0,
            _blend_pixel(
                _pixel(edges[west].east_inner, y),
                _pixel(own.west_inner, y),
                first_weight=1,
            ),
        )
    east = tile_neighbors.get("east")
    if east is not None:
        _set_pixel(
            row,
            TILE_PIXELS - 1,
            _blend_pixel(
                _pixel(own.east_inner, y),
                _pixel(edges[east].west_inner, y),
                first_weight=2,
            ),
        )
    return bytes(row)


def stabilize_native_image(
    tile: TileKey,
    image: RgbaImage,
    *,
    edges: Mapping[TileKey, TileEdges],
    neighbors: Mapping[TileKey, Mapping[str, TileKey]],
) -> RgbaImage:
    """Apply separable one-pixel feathering only at cross-shard boundaries."""

    if (image.width, image.height) != (TILE_PIXELS, TILE_PIXELS):
        raise ValueError("Seam stabilization requires native 512px tiles")
    tile_neighbors = neighbors.get(tile)
    if not tile_neighbors:
        return image
    own = edges[tile]
    pixels = bytearray(image.pixels)
    stride = TILE_PIXELS * 4

    west = tile_neighbors.get("west")
    east = tile_neighbors.get("east")
    for y in range(TILE_PIXELS):
        if west is not None:
            value = _blend_pixel(
                _pixel(edges[west].east_inner, y),
                _pixel(own.west_inner, y),
                first_weight=1,
            )
            offset = y * stride
            pixels[offset : offset + 4] = value
        if east is not None:
            value = _blend_pixel(
                _pixel(own.east_inner, y),
                _pixel(edges[east].west_inner, y),
                first_weight=2,
            )
            offset = y * stride + (TILE_PIXELS - 1) * 4
            pixels[offset : offset + 4] = value

    north = tile_neighbors.get("north")
    if north is not None:
        boundary = _blend_lines(
            _corrected_anchor_row(tile, "north", edges=edges, neighbors=neighbors),
            _corrected_anchor_row(north, "south", edges=edges, neighbors=neighbors),
            first_weight=2,
        )
        pixels[:stride] = boundary
    south = tile_neighbors.get("south")
    if south is not None:
        boundary = _blend_lines(
            _corrected_anchor_row(south, "north", edges=edges, neighbors=neighbors),
            _corrected_anchor_row(tile, "south", edges=edges, neighbors=neighbors),
            first_weight=1,
        )
        pixels[-stride:] = boundary
    return RgbaImage(TILE_PIXELS, TILE_PIXELS, bytes(pixels))


def _native_aggregate(entries: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {
            "path": entry["path"],
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
        }
        for entry in entries
        if int(entry["z"]) == NATIVE_ZOOM
    ]
    return _sha256_bytes(_canonical_json_bytes(payload))


def _clone_tree(source: Path, destination: Path) -> str:
    """Prefer filesystem CoW clones so source files can never be mutated via links."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    commands = (
        ("cp", "-cR", str(source), str(destination)),
        ("cp", "-a", "--reflink=auto", str(source), str(destination)),
    )
    for command in commands:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode == 0:
            return "copy-on-write"
        if destination.exists():
            shutil.rmtree(destination)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    return "copy"


def _publish_staged_directory_no_replace(staging: Path, destination: Path) -> None:
    token = f"morrowind-map:{os.getpid()}:{staging.name}".encode("utf-8")
    try:
        destination.mkdir()
    except FileExistsError as error:
        raise FileExistsError(
            f"Stabilization output appeared during publication: {destination}"
        ) from error
    marker = destination / ".publishing"
    _atomic_write_bytes(marker, token)
    complete = False
    try:
        for child in sorted(staging.iterdir(), key=lambda path: path.name):
            child.rename(destination / child.name)
        marker.unlink()
        staging.rmdir()
        complete = True
    finally:
        if (
            not complete
            and marker.is_file()
            and not marker.is_symlink()
            and marker.read_bytes() == token
        ):
            shutil.rmtree(destination)


def _copy_render_evidence(source: Path, destination: Path) -> str:
    destination.mkdir(parents=True)
    copy_method = _clone_tree(source / "tiles", destination / "tiles")
    for name in ("checkpoint.json", "inventory.json", "plan.json", "provenance.json"):
        shutil.copy2(source / name, destination / name)
    for name in ("logs", "runtime", "provenance-migrations"):
        path = source / name
        if path.exists():
            _clone_tree(path, destination / name)
    source_runs = source / "runs"
    if source_runs.is_dir():
        for log in source_runs.glob("*/profile/config/openmw.log"):
            relative = log.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(log, target)
    return copy_method


def _build_stabilized_pyramid(
    output_root: Path,
    native_tiles: Sequence[TileKey],
    *,
    magick: str,
) -> list[TileKey]:
    all_tiles = list(native_tiles)
    current = tuple(sorted(native_tiles))
    while current and current[0].z > MIN_ZOOM:
        current = build_lower_zoom_level(
            tile_root=output_root / "tiles",
            child_tiles=current,
            magick=magick,
        )
        all_tiles.extend(current)
        print(
            f"[stabilize:pyramid z{current[0].z}] {len(current)} tiles",
            file=sys.stderr,
            flush=True,
        )
    return all_tiles


def _inventory_from_current_native(
    output_root: Path,
    source: ValidatedInventory,
    *,
    stabilization_fingerprint: str,
    magick: str,
) -> ValidatedInventory:
    native_tiles = [
        TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"]))
        for entry in source.tile_entries
        if int(entry["z"]) == NATIVE_ZOOM
    ]
    all_tiles = _build_stabilized_pyramid(
        output_root,
        native_tiles,
        magick=magick,
    )
    built = build_inventory(
        output_root=output_root,
        tiles=all_tiles,
        provenance_fingerprint=source.provenance_fingerprint,
        plan_fingerprint_value=source.plan_fingerprint,
    )
    core = {
        key: value for key, value in built.payload.items() if key != "inventorySha256"
    }
    core["postprocess"] = {
        "type": "crossShardSeamStabilization",
        "version": STABILIZER_VERSION,
        "fingerprint": stabilization_fingerprint,
    }
    inventory = dict(core)
    inventory["inventorySha256"] = _sha256_bytes(_canonical_json_bytes(core))
    _atomic_write_json(output_root / "inventory.json", inventory)
    return validate_source(output_root)


def _receipt_with_hash(core: Mapping[str, object]) -> dict[str, object]:
    value = dict(core)
    value["receiptSha256"] = _sha256_bytes(_canonical_json_bytes(core))
    return value


def _artifact(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Tile transform line {line_number} is invalid") from error
        if not isinstance(value, dict):
            raise ValueError(f"Tile transform line {line_number} must be an object")
        result.append(value)
    return result


def validate_stabilization_receipt(
    output_root: Path,
    inventory: ValidatedInventory,
    *,
    source_inventory: ValidatedInventory | None = None,
    require_current_implementation: bool = True,
    expected_toolchain: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    path = output_root.resolve() / STABILIZATION_RECEIPT
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"Seam stabilization receipt is missing or unsafe: {path}")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("Seam stabilization receipt must be an object")
    expected_keys = {
        "schemaVersion",
        "datasetId",
        "snapshotId",
        "stabilizerVersion",
        "stabilizationFingerprint",
        "identity",
        "output",
        "receiptSha256",
    }
    if set(receipt) != expected_keys:
        raise ValueError("Seam stabilization receipt fields do not match the contract")
    core = {key: item for key, item in receipt.items() if key != "receiptSha256"}
    if receipt.get("receiptSha256") != _sha256_bytes(_canonical_json_bytes(core)):
        raise ValueError("Seam stabilization receipt logical hash does not recompute")
    expected_header = {
        "schemaVersion": STABILIZER_SCHEMA_VERSION,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "stabilizerVersion": STABILIZER_VERSION,
    }
    for key, expected in expected_header.items():
        if receipt.get(key) != expected:
            raise ValueError(f"Seam stabilization receipt {key} mismatch")
    identity = receipt.get("identity")
    if not isinstance(identity, dict) or set(identity) != {
        "algorithm",
        "implementationSha256",
        "postprocessToolchain",
        "sourceInventory",
        "tileTransforms",
        "renderCheckpointFileSha256",
        "provenanceFileSha256",
        "provenanceFingerprint",
        "planFileSha256",
        "planFingerprint",
        "scope",
    }:
        raise ValueError("Seam stabilization identity fields do not match the contract")
    fingerprint = _sha256_bytes(_canonical_json_bytes(identity))
    if receipt.get("stabilizationFingerprint") != fingerprint:
        raise ValueError("Seam stabilization fingerprint does not recompute")
    implementation = identity.get("implementationSha256")
    if (
        require_current_implementation
        and implementation != stabilizer_implementation_sha256()
    ):
        raise ValueError("Seam stabilization implementation hash is stale")
    expected_algorithm = {
        "boundaryWidthPixels": 1,
        "kernel": "linear-2:1",
        "alphaMode": "premultiplied",
        "passes": ["east-west", "north-south"],
        "nativeZoom": NATIVE_ZOOM,
        "tilePixels": TILE_PIXELS,
    }
    if identity.get("algorithm") != expected_algorithm:
        raise ValueError("Seam stabilization algorithm contract mismatch")
    toolchain = identity.get("postprocessToolchain")
    if not isinstance(toolchain, dict) or set(toolchain) != {
        "productionSourceFingerprint",
        "imageMagick",
        "python",
    }:
        raise ValueError("Seam stabilization postprocess toolchain is malformed")
    image_magick = toolchain.get("imageMagick")
    python = toolchain.get("python")
    if not isinstance(image_magick, dict) or set(image_magick) != {
        "version",
        "webpCoder",
        "executableSha256",
    }:
        raise ValueError("Seam stabilization ImageMagick identity is malformed")
    if not isinstance(python, dict) or set(python) != {"implementation", "version"}:
        raise ValueError("Seam stabilization Python identity is malformed")
    if (
        toolchain.get("productionSourceFingerprint")
        != inventory.production_source_fingerprint
        or image_magick.get("version") != inventory.provenance.get("magickVersion")
        or not isinstance(image_magick.get("webpCoder"), str)
        or not image_magick["webpCoder"]
        or not isinstance(image_magick.get("executableSha256"), str)
        or _SHA256.fullmatch(image_magick["executableSha256"]) is None
        or not all(
            isinstance(python.get(key), str) and bool(python[key])
            for key in ("implementation", "version")
        )
    ):
        raise ValueError("Seam stabilization postprocess toolchain mismatch")
    if expected_toolchain is not None and toolchain != dict(expected_toolchain):
        raise ValueError("Seam stabilization current postprocess toolchain mismatch")

    output = receipt.get("output")
    if not isinstance(output, dict) or output != {
        "inventorySha256": inventory.inventory_sha256,
        "inventoryFileSha256": inventory.inventory_file_sha256,
        "nativeAggregateSha256": _native_aggregate(inventory.tile_entries),
        "tileCount": inventory.tile_count,
        "totalBytes": inventory.total_bytes,
    }:
        raise ValueError("Seam stabilization target identity mismatch")
    postprocess = inventory.payload.get("postprocess")
    if postprocess != {
        "type": "crossShardSeamStabilization",
        "version": STABILIZER_VERSION,
        "fingerprint": fingerprint,
    }:
        raise ValueError("Inventory does not bind the seam stabilization fingerprint")
    if identity.get("provenanceFingerprint") != inventory.provenance_fingerprint:
        raise ValueError("Seam stabilization changed renderer provenance")
    if identity.get("planFingerprint") != inventory.plan_fingerprint:
        raise ValueError("Seam stabilization changed the tile plan")
    file_hashes = {
        "renderCheckpointFileSha256": output_root / "checkpoint.json",
        "provenanceFileSha256": output_root / "provenance.json",
        "planFileSha256": output_root / "plan.json",
    }
    for key, file_path in file_hashes.items():
        if identity.get(key) != _sha256_file(file_path):
            raise ValueError(f"Seam stabilization {key} mismatch")

    source_artifact = identity.get("sourceInventory")
    if not isinstance(source_artifact, dict) or set(source_artifact) != {
        "path",
        "bytes",
        "sha256",
        "logicalSha256",
    }:
        raise ValueError("Source inventory artifact is malformed")
    if source_artifact.get("path") != SOURCE_INVENTORY_PATH.as_posix():
        raise ValueError("Source inventory artifact path mismatch")
    source_path = output_root / SOURCE_INVENTORY_PATH
    if (
        not source_path.is_file()
        or source_path.is_symlink()
        or source_path.stat().st_size != source_artifact.get("bytes")
        or _sha256_file(source_path) != source_artifact.get("sha256")
    ):
        raise ValueError("Source inventory artifact changed")
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(source_payload, dict):
        raise ValueError("Source inventory artifact must be an object")
    source_logical = source_payload.get("inventorySha256")
    source_core = {
        key: item for key, item in source_payload.items() if key != "inventorySha256"
    }
    if (
        source_logical != source_artifact.get("logicalSha256")
        or source_logical != _sha256_bytes(_canonical_json_bytes(source_core))
    ):
        raise ValueError("Source inventory logical hash does not recompute")
    if (
        source_payload.get("datasetId") != DATASET_ID
        or source_payload.get("snapshotId") != SNAPSHOT_ID
        or source_payload.get("provenanceFingerprint")
        != inventory.provenance_fingerprint
        or source_payload.get("planFingerprint") != inventory.plan_fingerprint
        or "postprocess" in source_payload
    ):
        raise ValueError("Source inventory identity mismatch")
    if source_inventory is not None and (
        source_inventory.inventory_sha256 != source_logical
        or source_inventory.inventory_file_sha256 != source_artifact.get("sha256")
    ):
        raise ValueError("Archived source inventory does not match the source dataset")

    native_tiles = {
        TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"]))
        for entry in inventory.tile_entries
        if int(entry["z"]) == NATIVE_ZOOM
    }
    seam_edges = cross_shard_edges(native_tiles)
    if len(seam_edges) != EXPECTED_CROSS_SHARD_EDGES:
        raise ValueError("Seam stabilization cross-shard topology mismatch")
    neighbors = border_neighbors(seam_edges)
    expected_paths = {
        (Path("tiles") / tile.relative_path).as_posix() for tile in neighbors
    }
    transform_artifact = identity.get("tileTransforms")
    if not isinstance(transform_artifact, dict) or set(transform_artifact) != {
        "path",
        "bytes",
        "sha256",
        "records",
    }:
        raise ValueError("Tile transform artifact is malformed")
    if transform_artifact.get("path") != TILE_TRANSFORMS_PATH.as_posix():
        raise ValueError("Tile transform artifact path mismatch")
    transform_path = output_root / TILE_TRANSFORMS_PATH
    if (
        not transform_path.is_file()
        or transform_path.is_symlink()
        or transform_path.stat().st_size != transform_artifact.get("bytes")
        or _sha256_file(transform_path) != transform_artifact.get("sha256")
    ):
        raise ValueError("Tile transform artifact changed")
    records = _read_ndjson(transform_path)
    if transform_artifact.get("records") != len(records):
        raise ValueError("Tile transform record count mismatch")
    target_by_path = {str(entry["path"]): entry for entry in inventory.tile_entries}
    source_entries = source_payload.get("tiles")
    if not isinstance(source_entries, list):
        raise ValueError("Source inventory tiles are malformed")
    source_by_path = {
        str(entry.get("path")): entry
        for entry in source_entries
        if isinstance(entry, dict)
    }
    if set(source_by_path) != set(target_by_path):
        raise ValueError("Source and target inventory topology differs")
    record_paths: set[str] = set()
    changed = 0
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "z",
            "x",
            "y",
            "path",
            "sides",
            "beforeBytes",
            "beforeSha256",
            "beforeRgbaSha256",
            "afterBytes",
            "afterSha256",
            "afterRgbaSha256",
        }:
            raise ValueError("Seam stabilization tile record is malformed")
        for key in ("beforeRgbaSha256", "afterRgbaSha256"):
            field_value = record.get(key)
            if (
                not isinstance(field_value, str)
                or _SHA256.fullmatch(field_value) is None
            ):
                raise ValueError(
                    f"Seam stabilization tile {key} is not an exact SHA-256"
                )
        relative = str(record["path"])
        if relative in record_paths or relative not in expected_paths:
            raise ValueError("Seam stabilization tile record scope mismatch")
        target_entry = target_by_path.get(relative)
        source_entry = source_by_path.get(relative)
        tile = TileKey(int(record["z"]), int(record["x"]), int(record["y"]))
        if relative != (Path("tiles") / tile.relative_path).as_posix():
            raise ValueError("Seam stabilization tile coordinates do not match path")
        if record.get("sides") != sorted(neighbors[tile]):
            raise ValueError("Seam stabilization tile sides do not match topology")
        if (
            target_entry is None
            or source_entry is None
            or record["afterBytes"] != target_entry.get("bytes")
            or record["afterSha256"] != target_entry.get("sha256")
            or record["beforeBytes"] != source_entry.get("bytes")
            or record["beforeSha256"] != source_entry.get("sha256")
        ):
            raise ValueError("Seam stabilization tile output hash mismatch")
        if record["beforeSha256"] != record["afterSha256"]:
            changed += 1
        record_paths.add(relative)
    if record_paths != expected_paths:
        raise ValueError("Seam stabilization receipt does not cover every touched tile")
    for relative, source_entry in source_by_path.items():
        if int(source_entry.get("z", -1)) != NATIVE_ZOOM or relative in expected_paths:
            continue
        target_entry = target_by_path[relative]
        if (
            source_entry.get("bytes") != target_entry.get("bytes")
            or source_entry.get("sha256") != target_entry.get("sha256")
        ):
            raise ValueError("Untouched native tile changed during stabilization")
    scope = identity.get("scope")
    expected_scope = {
        "nativeTiles": len(native_tiles),
        "crossShardAdjacencies": len(seam_edges),
        "touchedTiles": len(expected_paths),
        "changedTiles": changed,
    }
    if scope != expected_scope:
        raise ValueError("Seam stabilization scope mismatch")

    checkpoint = json.loads((output_root / "checkpoint.json").read_text(encoding="utf-8"))
    completed = checkpoint.get("completed") if isinstance(checkpoint, dict) else None
    if not isinstance(completed, list) or len(completed) != len(native_tiles):
        raise ValueError("Render checkpoint is incomplete")
    checkpoint_paths: set[str] = set()
    for artifact in completed:
        if not isinstance(artifact, dict):
            raise ValueError("Render checkpoint artifact is malformed")
        relative = str(artifact.get("path"))
        source_entry = source_by_path.get(relative)
        if (
            source_entry is None
            or int(source_entry.get("z", -1)) != NATIVE_ZOOM
            or artifact.get("bytes") != source_entry.get("bytes")
            or artifact.get("sha256") != source_entry.get("sha256")
            or relative in checkpoint_paths
        ):
            raise ValueError("Render checkpoint no longer matches source inventory")
        checkpoint_paths.add(relative)
    if checkpoint_paths != {
        str(entry["path"])
        for entry in source_entries
        if isinstance(entry, dict) and int(entry.get("z", -1)) == NATIVE_ZOOM
    }:
        raise ValueError("Render checkpoint does not cover every source native tile")
    return receipt


def stabilize_dataset(
    *,
    source_root: Path = DEFAULT_OUTPUT,
    output_root: Path = DEFAULT_STABILIZED_OUTPUT,
    workers: int = 4,
    magick: str = "magick",
    progress: ProgressCallback | None = None,
) -> StabilizationResult:
    if workers <= 0:
        raise ValueError("Stabilization workers must be positive")
    implementation_sha256 = stabilizer_implementation_sha256()
    repo_root = Path(__file__).resolve().parents[2]
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if source_root == output_root or source_root in output_root.parents or output_root in source_root.parents:
        raise ValueError("Stabilization source and output must not overlap")
    source = validate_source(source_root, progress=progress)
    recorded_magick = source.provenance.get("magickVersion")
    if not isinstance(recorded_magick, str) or not recorded_magick:
        raise ValueError("Render provenance ImageMagick identity is invalid")
    resolved_magick, postprocess_toolchain = _resolve_stabilization_toolchain(
        repo_root=repo_root,
        magick=magick,
        expected_production_source_fingerprint=source.production_source_fingerprint,
        expected_magick_version=recorded_magick,
    )
    if output_root.exists():
        existing = validate_source(output_root, progress=progress)
        receipt = validate_stabilization_receipt(
            output_root,
            existing,
            source_inventory=source,
            expected_toolchain=postprocess_toolchain,
        )
        return StabilizationResult(
            output_root=output_root,
            inventory_sha256=existing.inventory_sha256,
            receipt_sha256=str(receipt["receiptSha256"]),
            cross_shard_edges=int(receipt["identity"]["scope"]["crossShardAdjacencies"]),
            touched_native_tiles=int(receipt["identity"]["scope"]["touchedTiles"]),
            changed_native_tiles=int(receipt["identity"]["scope"]["changedTiles"]),
            created=False,
        )

    native_entries = [
        entry for entry in source.tile_entries if int(entry["z"]) == NATIVE_ZOOM
    ]
    native_tiles = {
        TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"]))
        for entry in native_entries
    }
    seam_edges = cross_shard_edges(native_tiles)
    if len(seam_edges) != EXPECTED_CROSS_SHARD_EDGES:
        raise ValueError(
            f"Expected {EXPECTED_CROSS_SHARD_EDGES} cross-shard edges, got {len(seam_edges)}"
        )
    neighbors = border_neighbors(seam_edges)
    entry_by_tile = {
        TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"])): entry
        for entry in native_entries
    }

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.stabilize-", dir=output_root.parent)
    )
    # copytree requires an absent destination; mkdtemp reserves a collision-free name.
    staging.rmdir()
    try:
        copy_method = _copy_render_evidence(source_root, staging)
        if progress is not None:
            progress("[stabilize:snapshot] validating immutable source clone")
        snapshot = validate_source(staging)
        _require_matching_source_snapshot(source, snapshot)
        stabilization_root = staging / STABILIZATION_ROOT
        stabilization_root.mkdir(parents=True)
        shutil.copy2(staging / "inventory.json", staging / SOURCE_INVENTORY_PATH)
        if progress is not None:
            progress(f"[stabilize:clone] {copy_method}")

        def load_edge(tile: TileKey) -> tuple[TileKey, TileEdges]:
            image = _default_webp_reader(
                staging / "tiles" / tile.relative_path,
                magick=resolved_magick,
            )
            return tile, _extract_edges(image)

        edge_cache: dict[TileKey, TileEdges] = {}
        ordered_native = sorted(native_tiles)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="seam-edges") as pool:
            for index, (tile, tile_edges) in enumerate(
                pool.map(load_edge, ordered_native), start=1
            ):
                edge_cache[tile] = tile_edges
                if progress is not None and (index == len(ordered_native) or index % 100 == 0):
                    progress(f"[stabilize:edges {index}/{len(ordered_native)}]")

        touched = sorted(neighbors)

        def stabilize_tile(tile: TileKey) -> dict[str, object]:
            entry = entry_by_tile[tile]
            source_path = staging / str(entry["path"])
            output_path = staging / str(entry["path"])
            image = _default_webp_reader(source_path, magick=resolved_magick)
            corrected = stabilize_native_image(
                tile,
                image,
                edges=edge_cache,
                neighbors=neighbors,
            )
            after_bytes, after_sha256 = write_native_master(
                corrected,
                output_path,
                magick=resolved_magick,
            )
            return {
                "z": tile.z,
                "x": tile.x,
                "y": tile.y,
                "path": str(entry["path"]),
                "sides": sorted(neighbors[tile]),
                "beforeBytes": int(entry["bytes"]),
                "beforeSha256": str(entry["sha256"]),
                "beforeRgbaSha256": _sha256_bytes(image.pixels),
                "afterBytes": after_bytes,
                "afterSha256": after_sha256,
                "afterRgbaSha256": _sha256_bytes(corrected.pixels),
            }

        records: list[dict[str, object]] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="seam-write") as pool:
            for index, record in enumerate(pool.map(stabilize_tile, touched), start=1):
                records.append(record)
                if progress is not None and (index == len(touched) or index % 50 == 0):
                    progress(f"[stabilize:tiles {index}/{len(touched)}]")

        records.sort(key=lambda item: str(item["path"]))
        transform_bytes = b"".join(
            _canonical_json_bytes(record) + b"\n" for record in records
        )
        _atomic_write_bytes(staging / TILE_TRANSFORMS_PATH, transform_bytes)
        changed_count = sum(
            record["beforeSha256"] != record["afterSha256"] for record in records
        )
        source_artifact = _artifact(staging / SOURCE_INVENTORY_PATH, staging)
        source_artifact["logicalSha256"] = source.inventory_sha256
        transform_artifact = _artifact(staging / TILE_TRANSFORMS_PATH, staging)
        transform_artifact["records"] = len(records)
        identity = {
            "algorithm": {
                "boundaryWidthPixels": 1,
                "kernel": "linear-2:1",
                "alphaMode": "premultiplied",
                "passes": ["east-west", "north-south"],
                "nativeZoom": NATIVE_ZOOM,
                "tilePixels": TILE_PIXELS,
            },
            "implementationSha256": implementation_sha256,
            "postprocessToolchain": postprocess_toolchain,
            "sourceInventory": source_artifact,
            "tileTransforms": transform_artifact,
            "renderCheckpointFileSha256": _sha256_file(staging / "checkpoint.json"),
            "provenanceFileSha256": _sha256_file(staging / "provenance.json"),
            "provenanceFingerprint": source.provenance_fingerprint,
            "planFileSha256": _sha256_file(staging / "plan.json"),
            "planFingerprint": source.plan_fingerprint,
            "scope": {
                "nativeTiles": len(native_tiles),
                "crossShardAdjacencies": len(seam_edges),
                "touchedTiles": len(touched),
                "changedTiles": changed_count,
            },
        }
        stabilization_fingerprint = _sha256_bytes(_canonical_json_bytes(identity))
        target = _inventory_from_current_native(
            staging,
            snapshot,
            stabilization_fingerprint=stabilization_fingerprint,
            magick=resolved_magick,
        )
        receipt_core = {
            "schemaVersion": STABILIZER_SCHEMA_VERSION,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "stabilizerVersion": STABILIZER_VERSION,
            "stabilizationFingerprint": stabilization_fingerprint,
            "identity": identity,
            "output": {
                "inventorySha256": target.inventory_sha256,
                "inventoryFileSha256": target.inventory_file_sha256,
                "nativeAggregateSha256": _native_aggregate(target.tile_entries),
                "tileCount": target.tile_count,
                "totalBytes": target.total_bytes,
            },
        }
        receipt = _receipt_with_hash(receipt_core)
        _atomic_write_json(staging / STABILIZATION_RECEIPT, receipt)
        validate_stabilization_receipt(
            staging,
            target,
            source_inventory=snapshot,
            expected_toolchain=postprocess_toolchain,
        )
        _require_stabilization_inputs_unchanged(
            implementation_sha256=implementation_sha256,
            resolved_magick=resolved_magick,
            toolchain=postprocess_toolchain,
            repo_root=repo_root,
            expected_production_source_fingerprint=source.production_source_fingerprint,
            expected_magick_version=recorded_magick,
        )
        _publish_staged_directory_no_replace(staging, output_root)
        return StabilizationResult(
            output_root=output_root,
            inventory_sha256=target.inventory_sha256,
            receipt_sha256=str(receipt["receiptSha256"]),
            cross_shard_edges=len(seam_edges),
            touched_native_tiles=len(touched),
            changed_native_tiles=changed_count,
            created=True,
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create an immutable seam-stabilized Poison Song basemap dataset."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_STABILIZED_OUTPUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--magick", default="magick")
    args = parser.parse_args(argv)
    result = stabilize_dataset(
        source_root=args.source,
        output_root=args.output,
        workers=args.workers,
        magick=args.magick,
        progress=_print_progress,
    )
    print(
        json.dumps(
            {
                "outputRoot": str(result.output_root),
                "inventorySha256": result.inventory_sha256,
                "receiptSha256": result.receipt_sha256,
                "crossShardEdges": result.cross_shard_edges,
                "touchedNativeTiles": result.touched_native_tiles,
                "changedNativeTiles": result.changed_native_tiles,
                "created": result.created,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
