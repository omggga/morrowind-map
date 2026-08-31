from __future__ import annotations

import argparse
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
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.land_renderer.terrain import RgbaImage, encode_webp
from tools.openmw_renderer.images import pixel_difference, seam_overlap
from tools.openmw_renderer.production import (
    DATASET_ID,
    DEFAULT_PRODUCTION_IMAGE,
    GUTTER_PIXELS,
    NATIVE_ZOOM,
    OPENMW_COMMIT,
    ProductionProvenance,
    RAW_PIXELS,
    SNAPSHOT_ID,
    TILE_PIXELS,
    TileKey,
    _canonical_json_bytes,
    _raw_path,
    _shard_center,
    _verified_provenance_fingerprint,
    cell_for_native_tile,
    compose_parent,
    native_tile_for_cell,
    plan_report,
    process_raw_master,
    production_resource_resolution_report,
    publish_provenance_receipt,
    read_shard_runtime,
    resolve_production_provenance,
    run_openmw_production,
)
from tools.openmw_renderer.publish import ValidatedInventory, validate_source
from tools.openmw_renderer.stabilize import (
    DEFAULT_STABILIZED_OUTPUT,
    SOURCE_INVENTORY_PATH,
    STABILIZATION_RECEIPT,
    STABILIZATION_ROOT,
    TILE_TRANSFORMS_PATH,
    _clone_tree,
    _copy_render_evidence,
    _require_matching_source_snapshot,
    _resolve_stabilization_toolchain,
    _source_snapshot_identity,
    stabilizer_implementation_sha256,
    validate_stabilization_receipt,
)


AUDIT_SCHEMA_VERSION = 2
AUDIT_VERSION = "poison-basemap-quality-binary-alpha-v4"
EXPECTED_TILE_COUNTS = {0: 1, 1: 4, 2: 9, 3: 25, 4: 87, 5: 296, 6: 1058, 7: 3984}
EXPECTED_ADJACENCIES = {
    (1, "east"): 2,
    (1, "north"): 2,
    (2, "east"): 6,
    (2, "north"): 6,
    (3, "east"): 19,
    (3, "north"): 19,
    (4, "east"): 75,
    (4, "north"): 74,
    (5, "east"): 269,
    (5, "north"): 269,
    (6, "east"): 998,
    (6, "north"): 999,
    (7, "east"): 3862,
    (7, "north"): 3867,
}
EXPECTED_TOTAL_TILES = 5464
EXPECTED_NATIVE_TILES = 3984
EXPECTED_SHARDS = 492
EXPECTED_TOTAL_ADJACENCIES = 10467
EXPECTED_NATIVE_ADJACENCIES = 7729
EXPECTED_NATIVE_CROSS_SHARD = 2571

PAIR_MEAN_EXCESS_MAX = 8.0
PAIR_HARD_PIXEL_DELTA = 32
PAIR_HARD_FRACTION_MAX = 0.10
POPULATION_CROSS_MEAN_MARGIN = 0.5
POPULATION_CROSS_P95_MARGIN = 2.0

RAW_MEAN_DELTA_MAX = 0.5
RAW_P99_DELTA_MAX = 8
RAW_HARD_PIXEL_DELTA = 8
RAW_HARD_FRACTION_MAX = 0.01
RAW_ALPHA_DIFFERING_FRACTION_MAX = 0.02
RAW_MAX_OPAQUE_DELTA_MAX = 32
RAW_LARGEST_HARD_COMPONENT_MAX = 16
REPEAT_DIFFERING_FRACTION_MAX = 0.03
REPEAT_MEAN_DELTA_MAX = 0.10
REPEAT_P99_DELTA_MAX = 8
REPEAT_HARD_PIXEL_DELTA = 8
REPEAT_HARD_FRACTION_MAX = 0.01
REPEAT_ALPHA_DIFFERING_FRACTION_MAX = 0.02
REPEAT_MAX_OPAQUE_DELTA_MAX = 48
REPEAT_LARGEST_HARD_COMPONENT_MAX = 16
PINNED_RAW_PROBE_IDS = (
    "7/5/14:east:7/6/14",
    "7/34/80:north:7/34/79",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")

CROSS_SHARD_P99_EXCESS_MAX = 8
CROSS_SHARD_MAX_EXCESS_MAX = 32
CROSS_SHARD_HARD_FRACTION_MAX = 0.01

ABSOLUTE_POPULATION_MEAN_MAX = 4.0
ABSOLUTE_POPULATION_P95_MAX = 8.0
ABSOLUTE_POPULATION_FLAGGED_FRACTION_MAX = 0.01
ABSOLUTE_PAIR_MEAN_MAX = 32.0

EXPECTED_SCOPE = {
    "tiles": EXPECTED_TOTAL_TILES,
    "nativeTiles": EXPECTED_NATIVE_TILES,
    "lowerZoomTiles": EXPECTED_TOTAL_TILES - EXPECTED_NATIVE_TILES,
    "shards": EXPECTED_SHARDS,
    "allFinalAdjacencies": EXPECTED_TOTAL_ADJACENCIES,
    "nativeAdjacencies": EXPECTED_NATIVE_ADJACENCIES,
    "nativeCrossShardAdjacencies": EXPECTED_NATIVE_CROSS_SHARD,
    "rawCrossShardProbes": 16,
}
EXPECTED_GATES = {
    "inventory",
    "seamStabilization",
    "stateAndMigrations",
    "pyramidDerivation",
    "finalSeams",
    "runtimeResourcesCoordinates",
    "rawProbes",
}
EXPECTED_REPORT_KEYS = {
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

ProgressCallback = Callable[[str], None]

_TARGET_RE = re.compile(
    r"MWMAP export target (?P<cell_x>-?\d+),(?P<cell_y>-?\d+): "
    r"(?P<pixels>\d+)px over (?P<world_units>\d+) world units; "
    r"center=\((?P<center_x>-?\d+),(?P<center_y>-?\d+)\); "
    r"bounds=\[(?P<min_x>-?\d+),(?P<max_x>-?\d+)\]x"
    r"\[(?P<min_y>-?\d+),(?P<max_y>-?\d+)\]; "
    r"raster=top-left,\+x,-y,flipVertical=false -> "
    r"/out/raw/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)\.png"
)


@dataclass(frozen=True, slots=True)
class TileEdges:
    west_boundary: bytes
    west_inner: bytes
    east_inner: bytes
    east_boundary: bytes
    north_boundary: bytes
    north_inner: bytes
    south_inner: bytes
    south_boundary: bytes


@dataclass(frozen=True, slots=True)
class Adjacency:
    first: TileKey
    second: TileKey
    direction: str

    @property
    def identifier(self) -> str:
        return (
            f"{self.first.z}/{self.first.x}/{self.first.y}:"
            f"{self.direction}:{self.second.z}/{self.second.x}/{self.second.y}"
        )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


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


def _write_json(path: Path, value: object) -> None:
    _atomic_write(path, _json_bytes(value))


def _write_ndjson(path: Path, values: Iterable[Mapping[str, object]]) -> None:
    payload = b"".join(_canonical_json_bytes(value) + b"\n" for value in values)
    _atomic_write(path, payload)


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"NDJSON artifact is missing or unsafe: {path}")
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line:
            raise ValueError(f"NDJSON line {line_number} is empty: {path}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"NDJSON line {line_number} is invalid: {path}") from error
        if not isinstance(value, dict):
            raise ValueError(f"NDJSON line {line_number} must be an object: {path}")
        result.append(value)
    return result


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    payload = path.read_bytes()
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value, payload


def _round(value: float) -> float:
    return round(value, 9)


def _percentile(values: Sequence[float | int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _identify_image(path: Path, *, magick: str) -> tuple[str, int, int]:
    completed = subprocess.run(
        (magick, "identify", "-ping", "-format", "%m %w %h", str(path)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"ImageMagick failed to identify {path}: {completed.stderr.strip()}"
        )
    parts = completed.stdout.strip().split()
    if len(parts) != 3:
        raise ValueError(f"ImageMagick returned invalid identity for {path}")
    try:
        return parts[0].upper(), int(parts[1]), int(parts[2])
    except ValueError as error:
        raise ValueError(f"ImageMagick returned invalid dimensions for {path}") from error


def _decode_rgba(path: Path, *, pixels: int, magick: str) -> RgbaImage:
    expected_format = {".webp": "WEBP", ".png": "PNG"}.get(path.suffix.lower())
    actual_format, width, height = _identify_image(path, magick=magick)
    if expected_format is None or actual_format != expected_format:
        raise ValueError(
            f"Image format mismatch for {path}: expected {expected_format}, got {actual_format}"
        )
    if (width, height) != (pixels, pixels):
        raise ValueError(
            f"Image dimensions mismatch for {path}: expected {pixels}x{pixels}, "
            f"got {width}x{height}"
        )
    completed = subprocess.run(
        (
            magick,
            str(path),
            "-alpha",
            "on",
            "-colorspace",
            "sRGB",
            "-depth",
            "8",
            "rgba:-",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ImageMagick failed to decode {path}: {message}")
    expected = pixels * pixels * 4
    if len(completed.stdout) != expected:
        raise ValueError(
            f"Decoded image must be {pixels}x{pixels} RGBA: {path} "
            f"returned {len(completed.stdout)} bytes"
        )
    return RgbaImage(pixels, pixels, completed.stdout)


def _premultiply(line: bytes) -> bytes:
    output = bytearray(len(line))
    for offset in range(0, len(line), 4):
        alpha = line[offset + 3]
        output[offset] = (line[offset] * alpha + 127) // 255
        output[offset + 1] = (line[offset + 1] * alpha + 127) // 255
        output[offset + 2] = (line[offset + 2] * alpha + 127) // 255
        output[offset + 3] = alpha
    return bytes(output)


def _premultiplied_image(image: RgbaImage) -> RgbaImage:
    return RgbaImage(image.width, image.height, _premultiply(image.pixels))


def _alpha_statistics(image: RgbaImage) -> dict[str, int]:
    alpha = image.pixels[3::4]
    transparent = alpha.count(0)
    opaque = alpha.count(255)
    return {
        "alphaTransparentPixels": transparent,
        "alphaNonzeroPixels": len(alpha) - transparent,
        "alphaOpaquePixels": opaque,
        "alphaIntermediatePixels": len(alpha) - transparent - opaque,
    }


def _column(image: RgbaImage, x: int) -> bytes:
    result = bytearray(image.height * 4)
    for y in range(image.height):
        source = (y * image.width + x) * 4
        target = y * 4
        result[target : target + 4] = image.pixels[source : source + 4]
    return bytes(result)


def _row(image: RgbaImage, y: int) -> bytes:
    start = y * image.width * 4
    return image.pixels[start : start + image.width * 4]


def _tile_decode_task(
    source_root: str,
    entry: Mapping[str, Any],
    magick: str,
) -> tuple[TileKey, dict[str, object], TileEdges]:
    root = Path(source_root)
    path = root / str(entry["path"])
    image = _decode_rgba(path, pixels=TILE_PIXELS, magick=magick)
    tile = TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"]))
    record: dict[str, object] = {
        "z": tile.z,
        "x": tile.x,
        "y": tile.y,
        "path": str(entry["path"]),
        "bytes": int(entry["bytes"]),
        "sha256": str(entry["sha256"]),
        "rgbaSha256": _sha256_bytes(image.pixels),
        "width": image.width,
        "height": image.height,
        **_alpha_statistics(image),
    }
    edges = TileEdges(
        west_boundary=_column(image, 0),
        west_inner=_column(image, 1),
        east_inner=_column(image, image.width - 2),
        east_boundary=_column(image, image.width - 1),
        north_boundary=_row(image, 0),
        north_inner=_row(image, 1),
        south_inner=_row(image, image.height - 2),
        south_boundary=_row(image, image.height - 1),
    )
    return tile, record, edges


def audit_tiles(
    source_root: Path,
    inventory: ValidatedInventory,
    *,
    workers: int,
    magick: str,
    progress: ProgressCallback | None,
) -> tuple[list[dict[str, object]], dict[TileKey, TileEdges]]:
    records: list[dict[str, object]] = []
    edges: dict[TileKey, TileEdges] = {}
    total = len(inventory.tile_entries)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="audit-decode") as pool:
        results = pool.map(
            _tile_decode_task,
            (str(source_root) for _ in inventory.tile_entries),
            inventory.tile_entries,
            (magick for _ in inventory.tile_entries),
        )
        for index, (tile, record, tile_edges) in enumerate(results, start=1):
            records.append(record)
            edges[tile] = tile_edges
            if progress is not None and (index == total or index % 100 == 0):
                progress(f"[audit:tiles {index}/{total}]")
    if len(edges) != EXPECTED_TOTAL_TILES:
        raise ValueError(f"Decoded tile count mismatch: {len(edges)}")
    records.sort(key=lambda value: (int(value["z"]), int(value["x"]), int(value["y"])))
    return records, edges


def _binary_alpha_gate(
    tile_records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    binary_alpha_tiles = sum(
        int(record["alphaIntermediatePixels"]) == 0 for record in tile_records
    )
    transparent_pixels = sum(
        int(record["alphaTransparentPixels"]) for record in tile_records
    )
    opaque_pixels = sum(int(record["alphaOpaquePixels"]) for record in tile_records)
    intermediate_pixels = sum(
        int(record["alphaIntermediatePixels"]) for record in tile_records
    )
    return {
        "passes": (
            binary_alpha_tiles == len(tile_records) and intermediate_pixels == 0
        ),
        "alphaMode": "binary-nonzero",
        "binaryAlphaTiles": binary_alpha_tiles,
        "alphaTransparentPixels": transparent_pixels,
        "alphaOpaquePixels": opaque_pixels,
        "alphaIntermediatePixels": intermediate_pixels,
    }


def _stabilization_rgba_gate(
    transform_records: Sequence[Mapping[str, object]],
    tile_records: Sequence[Mapping[str, object]],
    *,
    expected_touched_tiles: int,
) -> dict[str, object]:
    decoded_by_path = {str(record["path"]): record for record in tile_records}
    seen: set[str] = set()
    mismatches: list[str] = []
    verified = 0
    for record in transform_records:
        path = str(record.get("path"))
        if path in seen:
            mismatches.append(f"duplicate:{path}")
            continue
        seen.add(path)
        decoded = decoded_by_path.get(path)
        if decoded is None:
            mismatches.append(f"missing:{path}")
            continue
        if record.get("afterRgbaSha256") != decoded.get("rgbaSha256"):
            mismatches.append(f"rgba:{path}")
            continue
        verified += 1
    count_matches = len(transform_records) == expected_touched_tiles
    return {
        "passes": count_matches and verified == expected_touched_tiles and not mismatches,
        "expectedTouchedTiles": expected_touched_tiles,
        "transformRecords": len(transform_records),
        "verifiedAfterRgbaTiles": verified,
        "afterRgbaMismatches": len(mismatches),
        "mismatchExamples": mismatches[:20],
        "beforeRgbaValidation": "format-and-receipt-bound",
    }


def build_adjacencies(tiles: Iterable[TileKey]) -> tuple[Adjacency, ...]:
    available = set(tiles)
    result: list[Adjacency] = []
    for tile in sorted(available):
        east = TileKey(tile.z, tile.x + 1, tile.y)
        if east in available:
            result.append(Adjacency(tile, east, "east"))
        north = TileKey(tile.z, tile.x, tile.y - 1)
        if north in available:
            result.append(Adjacency(tile, north, "north"))
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.first.z,
                item.first.y,
                item.first.x,
                0 if item.direction == "east" else 1,
            ),
        )
    )


def seam_metrics(
    first_boundary: bytes,
    first_inner: bytes,
    second_boundary: bytes,
    second_inner: bytes,
) -> dict[str, object]:
    first_boundary = _premultiply(first_boundary)
    first_inner = _premultiply(first_inner)
    second_boundary = _premultiply(second_boundary)
    second_inner = _premultiply(second_inner)
    lengths = {
        len(first_boundary),
        len(first_inner),
        len(second_boundary),
        len(second_inner),
    }
    if len(lengths) != 1 or not lengths or next(iter(lengths)) % 4:
        raise ValueError("Seam edge lines must have equal RGBA lengths")
    pixel_count = next(iter(lengths)) // 4
    comparable_pixels = 0
    unmatched_alpha_pixels = 0
    boundary_total = 0
    baseline_total = 0
    excess_total = 0
    hard_pixels = 0
    pixel_excesses: list[int] = []
    maximum = 0
    for offset in range(0, pixel_count * 4, 4):
        if (first_boundary[offset + 3] == 0) != (second_boundary[offset + 3] == 0):
            unmatched_alpha_pixels += 1
        comparable_pixels += 1
        pixel_max = 0
        for channel in range(4):
            index = offset + channel
            boundary = abs(first_boundary[index] - second_boundary[index])
            baseline = max(
                abs(first_boundary[index] - first_inner[index]),
                abs(second_inner[index] - second_boundary[index]),
            )
            excess = max(0, boundary - baseline)
            boundary_total += boundary
            baseline_total += baseline
            excess_total += excess
            pixel_max = max(pixel_max, excess)
            maximum = max(maximum, excess)
        pixel_excesses.append(pixel_max)
        if pixel_max > PAIR_HARD_PIXEL_DELTA:
            hard_pixels += 1
    channels = comparable_pixels * 4
    mean_excess = excess_total / channels if channels else 0.0
    hard_fraction = hard_pixels / comparable_pixels if comparable_pixels else 0.0
    return {
        "pixels": pixel_count,
        "comparablePixels": comparable_pixels,
        "unmatchedAlphaPixels": unmatched_alpha_pixels,
        "boundaryMeanChannelDelta": _round(boundary_total / channels if channels else 0.0),
        "localMeanChannelDelta": _round(baseline_total / channels if channels else 0.0),
        "meanExcessChannelDelta": _round(mean_excess),
        "hardPixelFraction": _round(hard_fraction),
        "p95PixelExcess": _round(_percentile(pixel_excesses, 0.95)),
        "p99PixelExcess": _round(_percentile(pixel_excesses, 0.99)),
        "maximumPixelExcess": maximum,
        "flagged": mean_excess > PAIR_MEAN_EXCESS_MAX
        or hard_fraction > PAIR_HARD_FRACTION_MAX,
    }


def _adjacency_lines(
    adjacency: Adjacency,
    edges: Mapping[TileKey, TileEdges],
) -> tuple[bytes, bytes, bytes, bytes]:
    first = edges[adjacency.first]
    second = edges[adjacency.second]
    if adjacency.direction == "east":
        return (
            first.east_boundary,
            first.east_inner,
            second.west_boundary,
            second.west_inner,
        )
    return (
        first.north_boundary,
        first.north_inner,
        second.south_boundary,
        second.south_inner,
    )


def audit_seams(
    edges: Mapping[TileKey, TileEdges],
    *,
    progress: ProgressCallback | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    adjacencies = build_adjacencies(edges)
    if len(adjacencies) != EXPECTED_TOTAL_ADJACENCIES:
        raise ValueError(f"Adjacency count mismatch: {len(adjacencies)}")
    records: list[dict[str, object]] = []
    total = len(adjacencies)
    for index, adjacency in enumerate(adjacencies, start=1):
        metrics = seam_metrics(*_adjacency_lines(adjacency, edges))
        same_shard: bool | None = None
        if adjacency.first.z == NATIVE_ZOOM:
            same_shard = _shard_center(cell_for_native_tile(adjacency.first)) == _shard_center(
                cell_for_native_tile(adjacency.second)
            )
        record: dict[str, object] = {
            "id": adjacency.identifier,
            "z": adjacency.first.z,
            "direction": adjacency.direction,
            "first": [adjacency.first.x, adjacency.first.y],
            "second": [adjacency.second.x, adjacency.second.y],
            "sameShard": same_shard,
            "crossShard": None if same_shard is None else not same_shard,
            **metrics,
        }
        records.append(record)
        if progress is not None and (index == total or index % 250 == 0):
            progress(f"[audit:seams {index}/{total}]")

    expected_counts: dict[tuple[int, str], int] = defaultdict(int)
    for record in records:
        expected_counts[(int(record["z"]), str(record["direction"]))] += 1
    if dict(expected_counts) != EXPECTED_ADJACENCIES:
        raise ValueError("Per-zoom adjacency topology does not match the pinned dataset")

    native = [record for record in records if record["z"] == NATIVE_ZOOM]
    cross = [record for record in native if record["crossShard"] is True]
    same = [record for record in native if record["sameShard"] is True]
    if len(native) != EXPECTED_NATIVE_ADJACENCIES or len(cross) != EXPECTED_NATIVE_CROSS_SHARD:
        raise ValueError("Native same/cross-shard topology does not match the pinned plan")

    def population(values: Sequence[Mapping[str, object]]) -> dict[str, object]:
        means = [float(value["meanExcessChannelDelta"]) for value in values]
        flagged_pairs = sum(bool(value["flagged"]) for value in values)
        return {
            "count": len(values),
            "meanExcess": _round(sum(means) / len(means) if means else 0.0),
            "p95MeanExcess": _round(_percentile(means, 0.95)),
            "maximumMeanExcess": _round(max(means, default=0.0)),
            "flaggedPairs": flagged_pairs,
            "flaggedFraction": _round(flagged_pairs / len(values) if values else 0.0),
        }

    same_population = population(same)
    cross_population = population(cross)
    relative_population_passes = (
        float(cross_population["meanExcess"])
        <= float(same_population["meanExcess"]) + POPULATION_CROSS_MEAN_MARGIN
        and float(cross_population["p95MeanExcess"])
        <= float(same_population["p95MeanExcess"]) + POPULATION_CROSS_P95_MARGIN
    )
    absolute_population_passes = all(
        float(value["meanExcess"]) <= ABSOLUTE_POPULATION_MEAN_MAX
        and float(value["p95MeanExcess"]) <= ABSOLUTE_POPULATION_P95_MAX
        and float(value["maximumMeanExcess"]) <= ABSOLUTE_PAIR_MEAN_MAX
        and float(value["flaggedFraction"])
        <= ABSOLUTE_POPULATION_FLAGGED_FRACTION_MAX
        for value in (same_population, cross_population)
    )
    structural_failures = [
        record
        for record in cross
        if float(record["meanExcessChannelDelta"]) > PAIR_MEAN_EXCESS_MAX
        or float(record["p99PixelExcess"]) > CROSS_SHARD_P99_EXCESS_MAX
        or int(record["maximumPixelExcess"]) > CROSS_SHARD_MAX_EXCESS_MAX
        or float(record["hardPixelFraction"])
        > CROSS_SHARD_HARD_FRACTION_MAX
    ]
    population_passes = relative_population_passes and absolute_population_passes
    flagged = [record for record in records if record["flagged"]]
    gate = {
        # Per-pair alerts remain diagnostic: sparse lower zooms and real map
        # features can legitimately cross a tile boundary. The release gate is
        # the same-vs-cross population test plus raw duplicate-gutter controls
        # for the deterministic worst cross-shard pairs.
        "passes": population_passes and not structural_failures,
        "adjacencies": len(records),
        "nativeAdjacencies": len(native),
        "nativeSameShard": len(same),
        "nativeCrossShard": len(cross),
        "flaggedPairs": len(flagged),
        "flaggedPairsAreDiagnostic": True,
        "crossShardStructuralFailures": len(structural_failures),
        "crossShardStructuralFailureIds": [
            str(record["id"]) for record in structural_failures[:20]
        ],
        "thresholds": {
            "pairMeanExcessMax": PAIR_MEAN_EXCESS_MAX,
            "hardPixelDelta": PAIR_HARD_PIXEL_DELTA,
            "pairHardFractionMax": PAIR_HARD_FRACTION_MAX,
            "crossMeanMargin": POPULATION_CROSS_MEAN_MARGIN,
            "crossP95Margin": POPULATION_CROSS_P95_MARGIN,
            "absoluteMeanMax": ABSOLUTE_POPULATION_MEAN_MAX,
            "absoluteP95Max": ABSOLUTE_POPULATION_P95_MAX,
            "absoluteFlaggedFractionMax": ABSOLUTE_POPULATION_FLAGGED_FRACTION_MAX,
            "absolutePairMeanMax": ABSOLUTE_PAIR_MEAN_MAX,
            "crossShardP99PixelExcessMax": CROSS_SHARD_P99_EXCESS_MAX,
            "crossShardMaximumPixelExcessMax": CROSS_SHARD_MAX_EXCESS_MAX,
            "crossShardHardPixelFractionMax": CROSS_SHARD_HARD_FRACTION_MAX,
        },
        "sameShardPopulation": same_population,
        "crossShardPopulation": cross_population,
        "relativePopulationPasses": relative_population_passes,
        "absolutePopulationPasses": absolute_population_passes,
        "populationPasses": population_passes,
    }
    return records, gate


def _pyramid_task(
    source_root: str,
    parent_value: tuple[int, int, int],
    child_values: tuple[tuple[int, int, int], ...],
    magick: str,
) -> dict[str, object]:
    root = Path(source_root) / "tiles"
    parent = TileKey(*parent_value)
    children: dict[tuple[int, int], RgbaImage] = {}
    for child_value in child_values:
        child = TileKey(*child_value)
        quadrant = (child.x - parent.x * 2, child.y - parent.y * 2)
        children[quadrant] = _decode_rgba(
            root / child.relative_path,
            pixels=TILE_PIXELS,
            magick=magick,
        )
    expected = compose_parent(children)
    actual = _decode_rgba(root / parent.relative_path, pixels=TILE_PIXELS, magick=magick)
    matches = expected.pixels == actual.pixels
    result: dict[str, object] = {
        "path": (Path("tiles") / parent.relative_path).as_posix(),
        "children": [list(value) for value in child_values],
        "matches": matches,
    }
    if not matches:
        difference = pixel_difference(expected, actual)
        result["difference"] = {
            "differingPixels": difference.differing_pixels,
            "differingFraction": _round(difference.differing_fraction),
            "meanAbsoluteChannelDelta": _round(difference.mean_absolute_channel_delta),
            "maximumChannelDelta": difference.maximum_channel_delta,
        }
    return result


def audit_pyramid(
    source_root: Path,
    tiles: Iterable[TileKey],
    *,
    workers: int,
    magick: str,
    progress: ProgressCallback | None,
) -> dict[str, object]:
    by_zoom: dict[int, set[TileKey]] = defaultdict(set)
    for tile in tiles:
        by_zoom[tile.z].add(tile)
    counts = {zoom: len(by_zoom.get(zoom, set())) for zoom in range(NATIVE_ZOOM + 1)}
    if counts != EXPECTED_TILE_COUNTS:
        raise ValueError(f"Tile topology count mismatch: {counts}")
    tasks: list[tuple[TileKey, tuple[TileKey, ...]]] = []
    for zoom in range(NATIVE_ZOOM - 1, -1, -1):
        children = by_zoom[zoom + 1]
        expected_parents = {
            TileKey(zoom, child.x // 2, child.y // 2) for child in children
        }
        if by_zoom[zoom] != expected_parents:
            raise ValueError(f"Sparse parent topology mismatch at z{zoom}")
        for parent in sorted(expected_parents):
            child_tiles = tuple(
                child
                for child in (
                    TileKey(zoom + 1, parent.x * 2 + dx, parent.y * 2 + dy)
                    for dy in (0, 1)
                    for dx in (0, 1)
                )
                if child in children
            )
            tasks.append((parent, child_tiles))
    total = len(tasks)
    mismatches: list[dict[str, object]] = []
    # Each task delegates decoding to ImageMagick subprocesses. Threads retain
    # that parallelism without requiring POSIX process semaphores, which are
    # unavailable in restricted macOS and minimal container environments.
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="audit-pyramid") as pool:
        results = pool.map(
            _pyramid_task,
            (str(source_root) for _ in tasks),
            ((parent.z, parent.x, parent.y) for parent, _ in tasks),
            (
                tuple((child.z, child.x, child.y) for child in children)
                for _, children in tasks
            ),
            (magick for _ in tasks),
            chunksize=1,
        )
        for index, result in enumerate(results, start=1):
            if result["matches"] is not True:
                mismatches.append(result)
            if progress is not None and (index == total or index % 50 == 0):
                progress(f"[audit:pyramid {index}/{total}]")
    return {
        "passes": not mismatches and total == EXPECTED_TOTAL_TILES - EXPECTED_NATIVE_TILES,
        "parentsChecked": total,
        "expectedParents": EXPECTED_TOTAL_TILES - EXPECTED_NATIVE_TILES,
        "mismatches": mismatches[:20],
        "tileCountsByZoom": {str(key): value for key, value in counts.items()},
    }


def _checkpoint_artifact_key(value: Mapping[str, Any]) -> TileKey:
    tile = value.get("tile")
    if not isinstance(tile, list) or len(tile) != 3 or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in tile
    ):
        raise ValueError("Checkpoint artifact has an invalid tile")
    return TileKey(*tile)


def _validate_completed_artifacts(
    completed: object,
    *,
    inventory_by_tile: Mapping[TileKey, Mapping[str, Any]],
) -> tuple[dict[TileKey, str], int]:
    if not isinstance(completed, list):
        raise ValueError("Checkpoint completed must be an array")
    seen: set[TileKey] = set()
    total_bytes = 0
    for artifact in completed:
        if not isinstance(artifact, dict):
            raise ValueError("Checkpoint artifact must be an object")
        tile = _checkpoint_artifact_key(artifact)
        if tile in seen:
            raise ValueError(f"Duplicate checkpoint artifact: {tile}")
        entry = inventory_by_tile.get(tile)
        if entry is None:
            raise ValueError(f"Checkpoint artifact is absent from inventory: {tile}")
        expected = {
            "path": entry["path"],
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
        }
        for key, value in expected.items():
            if artifact.get(key) != value:
                raise ValueError(f"Checkpoint artifact {tile} {key} mismatch")
        cell = artifact.get("cell")
        if not isinstance(cell, list) or len(cell) != 2:
            raise ValueError(f"Checkpoint artifact {tile} has invalid cell")
        if native_tile_for_cell((int(cell[0]), int(cell[1]))) != tile:
            raise ValueError(f"Checkpoint artifact {tile} cell does not round-trip")
        total_bytes += int(entry["bytes"])
        seen.add(tile)
    return {
        tile: str(inventory_by_tile[tile]["sha256"]) for tile in sorted(seen)
    }, total_bytes


def _validate_checkpoint_identity(
    checkpoint: Mapping[str, Any],
    *,
    provenance_fingerprint: str,
    plan_fingerprint: str,
    target_count: int,
    label: str,
) -> None:
    expected = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "provenanceFingerprint": provenance_fingerprint,
        "planFingerprint": plan_fingerprint,
        "targetCount": target_count,
    }
    for key, value in expected.items():
        if checkpoint.get(key) != value:
            raise ValueError(f"{label} {key} mismatch")


def audit_state_and_migrations(
    source_root: Path,
    inventory: ValidatedInventory,
    *,
    render_inventory_entries: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, object], tuple[tuple[int, int], ...], tuple[str, ...]]:
    plan, _ = _read_json(source_root / "plan.json", "Production plan")
    shards = plan.get("shards")
    if not isinstance(shards, list):
        raise ValueError("Production plan shards are invalid")
    cells: list[tuple[int, int]] = []
    shard_keys: list[str] = []
    for shard in shards:
        if not isinstance(shard, dict) or not isinstance(shard.get("cells"), list):
            raise ValueError("Production plan shard is invalid")
        key = shard.get("key")
        if not isinstance(key, str):
            raise ValueError("Production plan shard key is invalid")
        shard_keys.append(key)
        for cell in shard["cells"]:
            if not isinstance(cell, list) or len(cell) != 2:
                raise ValueError("Production plan cell is invalid")
            cells.append((int(cell[0]), int(cell[1])))
    rebuilt_plan = plan_report(cells)
    if plan != rebuilt_plan:
        raise ValueError("Production plan does not recompute exactly")
    if len(cells) != EXPECTED_NATIVE_TILES or len(shard_keys) != EXPECTED_SHARDS:
        raise ValueError("Production plan size does not match the pinned scope")

    inventory_by_tile = {
        TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"])): entry
        for entry in inventory.tile_entries
    }
    native_inventory = {
        tile: entry for tile, entry in inventory_by_tile.items() if tile.z == NATIVE_ZOOM
    }
    if set(native_inventory) != {native_tile_for_cell(cell) for cell in cells}:
        raise ValueError("Native inventory does not match the production plan")
    render_inventory_by_tile = (
        {
            TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"])): entry
            for entry in render_inventory_entries
            if int(entry["z"]) == NATIVE_ZOOM
        }
        if render_inventory_entries is not None
        else native_inventory
    )
    if set(render_inventory_by_tile) != set(native_inventory):
        raise ValueError("Render inventory does not match the native production plan")

    checkpoint, checkpoint_bytes = _read_json(source_root / "checkpoint.json", "Checkpoint")
    _validate_checkpoint_identity(
        checkpoint,
        provenance_fingerprint=inventory.provenance_fingerprint,
        plan_fingerprint=inventory.plan_fingerprint,
        target_count=EXPECTED_NATIVE_TILES,
        label="Checkpoint",
    )
    completed_artifacts, completed_bytes = _validate_completed_artifacts(
        checkpoint.get("completed"), inventory_by_tile=render_inventory_by_tile
    )
    completed_count = len(completed_artifacts)
    if completed_count != EXPECTED_NATIVE_TILES:
        raise ValueError("Checkpoint is not complete")

    provenance, provenance_bytes = _read_json(source_root / "provenance.json", "Provenance")
    if _verified_provenance_fingerprint(provenance) != inventory.provenance_fingerprint:
        raise ValueError("Current provenance does not recompute")

    migration_root = source_root / "provenance-migrations"
    migrations: dict[str, dict[str, Any]] = {}
    migration_payloads: dict[str, tuple[dict[str, Any], bytes, dict[str, Any], bytes]] = {}
    migration_artifacts: dict[str, dict[TileKey, str]] = {}
    if migration_root.is_dir():
        for directory in sorted(path for path in migration_root.iterdir() if path.is_dir()):
            receipt, _ = _read_json(directory / "migration.json", "Migration receipt")
            old_checkpoint, old_checkpoint_bytes = _read_json(
                directory / "checkpoint.json", "Migration checkpoint backup"
            )
            old_provenance, old_provenance_bytes = _read_json(
                directory / "provenance.json", "Migration provenance backup"
            )
            old_fingerprint = _verified_provenance_fingerprint(old_provenance)
            if directory.name != old_fingerprint:
                raise ValueError("Migration directory does not match old provenance")
            if receipt.get("fromProvenanceFingerprint") != old_fingerprint:
                raise ValueError("Migration receipt from fingerprint mismatch")
            if receipt.get("status") != "complete":
                raise ValueError("Migration receipt is incomplete")
            if receipt.get("planFingerprint") != inventory.plan_fingerprint:
                raise ValueError("Migration receipt plan fingerprint mismatch")
            _validate_checkpoint_identity(
                old_checkpoint,
                provenance_fingerprint=old_fingerprint,
                plan_fingerprint=inventory.plan_fingerprint,
                target_count=EXPECTED_NATIVE_TILES,
                label="Migration checkpoint backup",
            )
            if _sha256_bytes(old_checkpoint_bytes) != receipt.get("checkpointBeforeSha256"):
                raise ValueError("Migration checkpoint backup hash mismatch")
            if _sha256_bytes(old_provenance_bytes) != receipt.get("provenanceBeforeSha256"):
                raise ValueError("Migration provenance backup hash mismatch")
            artifact_map, byte_count = _validate_completed_artifacts(
                old_checkpoint.get("completed"), inventory_by_tile=render_inventory_by_tile
            )
            count = len(artifact_map)
            if count != receipt.get("completedArtifacts") or byte_count != receipt.get(
                "completedArtifactBytes"
            ):
                raise ValueError("Migration completed artifact totals mismatch")
            completed = old_checkpoint.get("completed")
            if _sha256_bytes(_canonical_json_bytes(completed)) != receipt.get(
                "completedArtifactsSha256"
            ):
                raise ValueError("Migration completed artifact hash mismatch")
            new_checkpoint = dict(old_checkpoint)
            new_checkpoint["provenanceFingerprint"] = receipt.get(
                "toProvenanceFingerprint"
            )
            if _sha256_bytes(_json_bytes(new_checkpoint)) != receipt.get(
                "checkpointAfterSha256"
            ):
                raise ValueError("Migration reconstructed checkpoint hash mismatch")
            migrations[old_fingerprint] = receipt
            migration_payloads[old_fingerprint] = (
                old_checkpoint,
                old_checkpoint_bytes,
                old_provenance,
                old_provenance_bytes,
            )
            migration_artifacts[old_fingerprint] = artifact_map

    incoming = {str(value["toProvenanceFingerprint"]): key for key, value in migrations.items()}
    starts = sorted(set(migrations) - set(incoming))
    ordered: list[dict[str, object]] = []
    if migrations:
        if len(starts) != 1:
            raise ValueError("Migration receipts do not form one continuous chain")
        current = starts[0]
        visited: set[str] = set()
        while current in migrations:
            if current in visited:
                raise ValueError("Migration chain contains a cycle")
            visited.add(current)
            receipt = migrations[current]
            target = str(receipt["toProvenanceFingerprint"])
            target_provenance_bytes: bytes | None = None
            if target == inventory.provenance_fingerprint:
                target_provenance_bytes = provenance_bytes
            elif target in migration_payloads:
                target_provenance_bytes = migration_payloads[target][3]
            if target_provenance_bytes is None:
                raise ValueError("Migration chain target provenance is missing")
            if _sha256_bytes(target_provenance_bytes) != receipt.get(
                "provenanceAfterSha256"
            ):
                raise ValueError("Migration target provenance hash mismatch")
            ordered.append(
                {
                    "fromProvenanceFingerprint": current,
                    "toProvenanceFingerprint": target,
                    "completedArtifacts": receipt["completedArtifacts"],
                    "completedArtifactBytes": receipt["completedArtifactBytes"],
                    "reason": receipt["reason"],
                }
            )
            current = target
        if visited != set(migrations) or current != inventory.provenance_fingerprint:
            raise ValueError("Migration chain does not terminate at current provenance")

    producer_counts: list[dict[str, object]] = []
    previous_artifacts: dict[TileKey, str] = {}
    for item in ordered:
        fingerprint = str(item["fromProvenanceFingerprint"])
        artifacts = migration_artifacts[fingerprint]
        if not set(previous_artifacts).issubset(artifacts):
            raise ValueError("Migration checkpoints are not monotonic subsets")
        for tile, digest in previous_artifacts.items():
            if artifacts[tile] != digest:
                raise ValueError("Migration checkpoint changes a completed tile hash")
        producer_counts.append(
            {
                "provenanceFingerprint": fingerprint,
                "tiles": len(set(artifacts) - set(previous_artifacts)),
            }
        )
        previous_artifacts = artifacts
    if not set(previous_artifacts).issubset(completed_artifacts):
        raise ValueError("Current checkpoint does not contain all migrated tiles")
    for tile, digest in previous_artifacts.items():
        if completed_artifacts[tile] != digest:
            raise ValueError("Current checkpoint changes a migrated tile hash")
    producer_counts.append(
        {
            "provenanceFingerprint": inventory.provenance_fingerprint,
            "tiles": len(set(completed_artifacts) - set(previous_artifacts)),
        }
    )
    if sum(int(value["tiles"]) for value in producer_counts) != EXPECTED_NATIVE_TILES:
        raise ValueError("Migration producer breakdown does not cover the native inventory")
    return (
        {
            "passes": True,
            "planFingerprint": inventory.plan_fingerprint,
            "targetCount": len(cells),
            "shardCount": len(shard_keys),
            "checkpointSha256": _sha256_bytes(checkpoint_bytes),
            "checkpointArtifacts": completed_count,
            "checkpointArtifactBytes": completed_bytes,
            "postprocessedNativeTiles": sum(
                render_inventory_by_tile[tile].get("sha256")
                != native_inventory[tile].get("sha256")
                for tile in native_inventory
            ),
            "migrationChain": ordered,
            "renderProvenanceBreakdown": producer_counts,
        },
        tuple(cells),
        tuple(shard_keys),
    )


def _expected_target(cell: tuple[int, int]) -> dict[str, int]:
    tile = native_tile_for_cell(cell)
    center_x = cell[0] * 8192 + 4096
    center_y = cell[1] * 8192 + 4096
    half = RAW_PIXELS * 16 // 2
    return {
        "cell_x": cell[0],
        "cell_y": cell[1],
        "pixels": RAW_PIXELS,
        "world_units": RAW_PIXELS * 16,
        "center_x": center_x,
        "center_y": center_y,
        "min_x": center_x - half,
        "max_x": center_x + half,
        "min_y": center_y - half,
        "max_y": center_y + half,
        "z": tile.z,
        "x": tile.x,
        "y": tile.y,
    }


def audit_runtime(
    source_root: Path,
    *,
    shard_keys: Sequence[str],
    progress: ProgressCallback | None,
) -> dict[str, object]:
    plan, _ = _read_json(source_root / "plan.json", "Production plan")
    plan_shards = plan.get("shards")
    assert isinstance(plan_shards, list)
    expected_by_key = {str(item["key"]): item for item in plan_shards}
    expected_set = set(shard_keys)
    actual_logs = {path.stem for path in (source_root / "logs").glob("*.log")}
    actual_runs = {
        path.name for path in (source_root / "runs").iterdir() if path.is_dir()
    }
    actual_runtime = {
        path.name for path in (source_root / "runtime").iterdir() if path.is_dir()
    }
    if actual_logs != expected_set or actual_runs != expected_set or actual_runtime != expected_set:
        raise ValueError("Runtime/log/run shard directories do not exactly match the plan")

    normalized_build_hashes: set[str] = set()
    build_variants: dict[str, int] = defaultdict(int)
    allowed_production_sources: set[str] = set()
    current_provenance, _ = _read_json(source_root / "provenance.json", "Provenance")
    current_source = current_provenance.get("productionSourceFingerprint")
    if isinstance(current_source, str):
        allowed_production_sources.add(current_source)
    migration_root = source_root / "provenance-migrations"
    if migration_root.is_dir():
        for path in migration_root.glob("*/provenance.json"):
            old_provenance, _ = _read_json(path, "Migration provenance backup")
            old_source = old_provenance.get("productionSourceFingerprint")
            if isinstance(old_source, str):
                allowed_production_sources.add(old_source)
    target_count = 0
    maximum_coordinate_error = 0.0
    total_elapsed = 0
    maximum_elapsed = 0
    maximum_memory = 0
    ignored_warning_lines: set[str] = set()
    total = len(shard_keys)
    for index, key in enumerate(shard_keys, start=1):
        shard = expected_by_key[key]
        runtime_root = source_root / "runtime" / key
        wrapper = source_root / "logs" / f"{key}.log"
        engine = source_root / "runs" / key / "profile/config/openmw.log"
        required = (
            runtime_root / "resource-resolution.json",
            runtime_root / "memory.peak",
            runtime_root / "process.json",
            runtime_root / "glxinfo.txt",
            runtime_root / "openmw-build-manifest.txt",
            wrapper,
            engine,
        )
        if any(not path.is_file() for path in required):
            missing = [str(path) for path in required if not path.is_file()]
            raise FileNotFoundError(f"Shard {key} runtime evidence is missing: {missing}")
        runtime = read_shard_runtime(source_root, key)
        total_elapsed += runtime.elapsed_seconds
        maximum_elapsed = max(maximum_elapsed, runtime.elapsed_seconds)
        maximum_memory = max(maximum_memory, runtime.memory_peak_bytes)
        glxinfo = (runtime_root / "glxinfo.txt").read_text(
            encoding="utf-8", errors="replace"
        )
        if "OpenGL renderer string: llvmpipe" not in glxinfo:
            raise ValueError(f"Shard {key} did not use llvmpipe")
        build_manifest = runtime_root / "openmw-build-manifest.txt"
        build_text = build_manifest.read_text(encoding="utf-8", errors="strict")
        if f"openmw_commit={OPENMW_COMMIT}" not in build_text:
            raise ValueError(f"Shard {key} build manifest has the wrong OpenMW commit")
        production_lines = [
            line for line in build_text.splitlines() if line.startswith("production_fingerprint=")
        ]
        if len(production_lines) != 1:
            raise ValueError(f"Shard {key} build manifest production fingerprint is invalid")
        production_source = production_lines[0].partition("=")[2]
        if production_source not in allowed_production_sources:
            raise ValueError(f"Shard {key} used an unaudited production source")
        build_variants[production_source] += 1
        normalized_build = build_text.replace(
            production_lines[0], "production_fingerprint=<audited-migration>"
        )
        normalized_build_hashes.add(_sha256_bytes(normalized_build.encode("utf-8")))

        expected_logs = (
            str(wrapper.relative_to(source_root)),
            str(engine.relative_to(source_root)),
        )
        recomputed = production_resource_resolution_report(
            source_root, expected_logs=expected_logs
        )
        stored, _ = _read_json(
            runtime_root / "resource-resolution.json", "Resource resolution report"
        )
        normalized_stored = dict(stored)
        normalized_stored.setdefault("ignoredCompatibilityWarnings", [])
        if recomputed != normalized_stored or recomputed.get("passes") is not True:
            raise ValueError(f"Shard {key} resource audit does not recompute")
        missing_messages = recomputed.get("missingResourceMessages")
        if missing_messages != []:
            raise ValueError(f"Shard {key} has actionable missing resources")
        warnings = recomputed.get("ignoredCompatibilityWarnings")
        if not isinstance(warnings, list):
            raise ValueError(f"Shard {key} warning evidence is invalid")
        for warning in warnings:
            if isinstance(warning, dict) and isinstance(warning.get("line"), str):
                ignored_warning_lines.add(str(warning["line"]))

        text = wrapper.read_text(encoding="utf-8", errors="replace")
        parsed = [
            {name: int(value) for name, value in match.groupdict().items()}
            for match in _TARGET_RE.finditer(text)
        ]
        expected_cells = {
            (int(cell[0]), int(cell[1])) for cell in shard["cells"]
        }
        if len(parsed) != len(expected_cells):
            raise ValueError(f"Shard {key} target marker count mismatch")
        parsed_cells = {(item["cell_x"], item["cell_y"]) for item in parsed}
        if parsed_cells != expected_cells:
            raise ValueError(f"Shard {key} target marker cells mismatch")
        for item in parsed:
            cell = (item["cell_x"], item["cell_y"])
            expected = _expected_target(cell)
            for field, expected_value in expected.items():
                difference = abs(item[field] - expected_value)
                if field in {
                    "center_x",
                    "center_y",
                    "min_x",
                    "max_x",
                    "min_y",
                    "max_y",
                }:
                    maximum_coordinate_error = max(
                        maximum_coordinate_error, difference / 16
                    )
                if item[field] != expected_value:
                    raise ValueError(
                        f"Shard {key} target {cell} {field} mismatch: "
                        f"{item[field]} != {expected_value}"
                    )
        target_count += len(parsed)
        if progress is not None and (index == total or index % 25 == 0):
            progress(f"[audit:runtime {index}/{total}]")
    if len(normalized_build_hashes) != 1 or target_count != EXPECTED_NATIVE_TILES:
        raise ValueError("Runtime build/target evidence is not uniform and complete")
    return {
        "passes": True,
        "shards": len(shard_keys),
        "targetMarkers": target_count,
        "maximumCoordinateErrorPixels": _round(maximum_coordinate_error),
        "resourceReports": len(shard_keys),
        "actionableMissingResources": 0,
        "ignoredCompatibilityWarningEvents": len(ignored_warning_lines),
        "normalizedBuildManifestSha256": next(iter(normalized_build_hashes)),
        "buildManifestProductionSources": dict(sorted(build_variants.items())),
        "openmwCommit": OPENMW_COMMIT,
        "runtime": {
            "sumContainerSeconds": total_elapsed,
            "maximumContainerSeconds": maximum_elapsed,
            "maximumMemoryPeakBytes": maximum_memory,
            "os": "linux",
            "architecture": "amd64",
            "renderer": "llvmpipe",
        },
    }


def _adjacency_from_record(record: Mapping[str, object]) -> Adjacency:
    z = int(record["z"])
    first = record["first"]
    second = record["second"]
    if not isinstance(first, list) or not isinstance(second, list):
        raise ValueError("Seam record coordinates are invalid")
    return Adjacency(
        TileKey(z, int(first[0]), int(first[1])),
        TileKey(z, int(second[0]), int(second[1])),
        str(record["direction"]),
    )


def _visual_difference(
    left: RgbaImage,
    right: RgbaImage,
    *,
    hard_pixel_delta: int,
    ignored_border_sides: Iterable[str] = (),
) -> dict[str, object]:
    if (left.width, left.height) != (right.width, right.height):
        raise ValueError("Images must have the same dimensions")
    left_visible = _premultiplied_image(left)
    right_visible = _premultiplied_image(right)
    ignored = frozenset(ignored_border_sides)
    if not ignored.issubset({"west", "east", "north", "south"}):
        raise ValueError("Ignored border sides are invalid")
    pixel_count = left.width * left.height
    compared_pixels = 0
    ignored_pixels = 0
    differing_pixels = 0
    alpha_differing_pixels = 0
    opaque_differing_pixels = 0
    hard_pixels = 0
    total_delta = 0
    maximum_delta = 0
    maximum_opaque_delta = 0
    pixel_deltas: list[int] = []
    hard_coordinates: set[tuple[int, int]] = set()
    for pixel_index, offset in enumerate(range(0, len(left_visible.pixels), 4)):
        x = pixel_index % left.width
        y = pixel_index // left.width
        if (
            (x == 0 and "west" in ignored)
            or (x == left.width - 1 and "east" in ignored)
            or (y == 0 and "north" in ignored)
            or (y == left.height - 1 and "south" in ignored)
        ):
            ignored_pixels += 1
            continue
        compared_pixels += 1
        deltas = [
            abs(left_visible.pixels[offset + channel] - right_visible.pixels[offset + channel])
            for channel in range(4)
        ]
        pixel_delta = max(deltas)
        pixel_deltas.append(pixel_delta)
        total_delta += sum(deltas)
        maximum_delta = max(maximum_delta, pixel_delta)
        if pixel_delta:
            differing_pixels += 1
            if (
                left.pixels[offset + 3] == 255
                and right.pixels[offset + 3] == 255
            ):
                opaque_differing_pixels += 1
                maximum_opaque_delta = max(maximum_opaque_delta, pixel_delta)
        if left.pixels[offset + 3] != right.pixels[offset + 3]:
            alpha_differing_pixels += 1
        if pixel_delta > hard_pixel_delta:
            hard_pixels += 1
            hard_coordinates.add((x, y))
    largest_component = 0
    hard_component_count = 0
    remaining = set(hard_coordinates)
    while remaining:
        hard_component_count += 1
        pending = [remaining.pop()]
        size = 0
        while pending:
            x, y = pending.pop()
            size += 1
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    neighbor = (x + dx, y + dy)
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        pending.append(neighbor)
        largest_component = max(largest_component, size)
    denominator = max(1, compared_pixels)
    return {
        "pixels": pixel_count,
        "comparedPixels": compared_pixels,
        "ignoredPixels": ignored_pixels,
        "ignoredBorderSides": sorted(ignored),
        "differingPixels": differing_pixels,
        "differingFraction": _round(differing_pixels / denominator),
        "alphaDifferingPixels": alpha_differing_pixels,
        "alphaDifferingFraction": _round(alpha_differing_pixels / denominator),
        "opaqueDifferingPixels": opaque_differing_pixels,
        "meanAbsoluteChannelDelta": _round(total_delta / (denominator * 4)),
        "p99PixelDelta": _round(_percentile(pixel_deltas, 0.99)),
        "hardPixelDelta": hard_pixel_delta,
        "hardPixels": hard_pixels,
        "hardPixelFraction": _round(hard_pixels / denominator),
        "hardComponentCount": hard_component_count,
        "largestHardComponentPixels": largest_component,
        "maximumChannelDelta": maximum_delta,
        "maximumOpaqueChannelDelta": maximum_opaque_delta,
    }


def _repeat_result(
    left: RgbaImage,
    right: RgbaImage,
    *,
    ignored_border_sides: Iterable[str] = (),
) -> dict[str, object]:
    difference = _visual_difference(
        left,
        right,
        hard_pixel_delta=REPEAT_HARD_PIXEL_DELTA,
        ignored_border_sides=ignored_border_sides,
    )
    passes = (
        float(difference["differingFraction"]) <= REPEAT_DIFFERING_FRACTION_MAX
        and float(difference["alphaDifferingFraction"])
        <= REPEAT_ALPHA_DIFFERING_FRACTION_MAX
        and float(difference["meanAbsoluteChannelDelta"]) <= REPEAT_MEAN_DELTA_MAX
        and float(difference["p99PixelDelta"]) <= REPEAT_P99_DELTA_MAX
        and float(difference["hardPixelFraction"]) <= REPEAT_HARD_FRACTION_MAX
        and int(difference["maximumOpaqueChannelDelta"])
        <= REPEAT_MAX_OPAQUE_DELTA_MAX
        and int(difference["largestHardComponentPixels"])
        <= REPEAT_LARGEST_HARD_COMPONENT_MAX
    )
    return {"passes": passes, **difference}


def _select_raw_probe_records(
    candidates: Sequence[Mapping[str, object]],
    probe_count: int,
) -> list[Mapping[str, object]]:
    if probe_count < len(PINNED_RAW_PROBE_IDS) or probe_count < 2:
        raise ValueError("Raw probe count is too small for pinned and directional controls")
    by_id = {str(record["id"]): record for record in candidates}
    missing_pinned = [identifier for identifier in PINNED_RAW_PROBE_IDS if identifier not in by_id]
    if missing_pinned:
        raise ValueError(f"Pinned raw controls are absent: {missing_pinned}")
    selected: list[Mapping[str, object]] = [by_id[value] for value in PINNED_RAW_PROBE_IDS]
    seen = set(PINNED_RAW_PROBE_IDS)
    metric_keys = (
        "meanExcessChannelDelta",
        "hardPixelFraction",
        "maximumPixelExcess",
        "unmatchedAlphaPixels",
    )

    def ranked(direction: str, metric: str) -> list[Mapping[str, object]]:
        return sorted(
            (record for record in candidates if record.get("direction") == direction),
            key=lambda value: (-float(value[metric]), str(value["id"])),
        )

    direction_target = probe_count // 2
    for direction in ("east", "north"):
        orders = [ranked(direction, metric) for metric in metric_keys]
        rank = 0
        while (
            sum(record.get("direction") == direction for record in selected)
            < direction_target
        ):
            added = False
            for order in orders:
                if (
                    sum(record.get("direction") == direction for record in selected)
                    >= direction_target
                ):
                    break
                if rank < len(order):
                    identifier = str(order[rank]["id"])
                    if identifier not in seen:
                        selected.append(order[rank])
                        seen.add(identifier)
                        added = True
                        if len(selected) == probe_count:
                            return selected
            rank += 1
            if not added and rank >= max(map(len, orders), default=0):
                break

    combined_orders = [
        sorted(
            candidates,
            key=lambda value, metric=metric: (-float(value[metric]), str(value["id"])),
        )
        for metric in metric_keys
    ]
    rank = 0
    while len(selected) < probe_count:
        added = False
        for order in combined_orders:
            if rank < len(order):
                identifier = str(order[rank]["id"])
                if identifier not in seen:
                    selected.append(order[rank])
                    seen.add(identifier)
                    added = True
                    if len(selected) == probe_count:
                        break
        rank += 1
        if not added and rank >= max(map(len, combined_orders), default=0):
            break
    if len(selected) != probe_count:
        raise ValueError("Not enough distinct cross-shard seams for raw controls")
    return selected


def _raw_probe_provenance_compatibility(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, object]:
    """Allow only BuildKit manifest rematerialization of the exact renderer."""

    released_core = {
        key: value
        for key, value in released.items()
        if key not in {"provenanceFingerprint", "image"}
    }
    candidate_core = {
        key: value
        for key, value in candidate.items()
        if key not in {"provenanceFingerprint", "image"}
    }
    released_image = released.get("image")
    candidate_image = candidate.get("image")
    if not isinstance(released_image, dict) or not isinstance(candidate_image, dict):
        raise ValueError("Raw-probe renderer image provenance is malformed")
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
    passes = (
        released_core == candidate_core
        and released_image_contract == candidate_image_contract
        and released_image.get("id") != candidate_image.get("id")
    )
    return {
        "passes": passes,
        "mode": "manifest-rematerialization" if passes else "incompatible",
        "releasedProvenanceFingerprint": released.get("provenanceFingerprint"),
        "candidateProvenanceFingerprint": candidate.get("provenanceFingerprint"),
        "releasedImageId": released_image.get("id"),
        "candidateImageId": candidate_image.get("id"),
        "candidatePayloadSha256": _sha256_bytes(_canonical_json_bytes(candidate)),
        "rendererContractEqual": released_image_contract == candidate_image_contract,
        "nonImageProvenanceEqual": released_core == candidate_core,
    }


def _require_final_raw_probe_provenance(
    report: Mapping[str, object],
    candidate: ProductionProvenance,
) -> None:
    gates = report.get("gates")
    raw = gates.get("rawProbes") if isinstance(gates, dict) else None
    renderer = raw.get("rendererProvenance") if isinstance(raw, dict) else None
    image = candidate.payload.get("image")
    if not isinstance(renderer, dict) or not isinstance(image, dict):
        raise RuntimeError("Quality audit raw renderer provenance is malformed")
    if (
        renderer.get("candidateProvenanceFingerprint") != candidate.fingerprint
        or renderer.get("candidateImageId") != image.get("id")
        or renderer.get("candidatePayloadSha256")
        != _sha256_bytes(_canonical_json_bytes(candidate.payload))
    ):
        raise RuntimeError("Game assets or raw renderer provenance changed during audit")


def _raw_probe_cache_name(
    selection_sha256: str,
    provenance_fingerprint: str,
) -> str:
    """Keep reusable raw renders isolated by both selection and renderer identity."""

    for label, value in (
        ("selection", selection_sha256),
        ("provenance", provenance_fingerprint),
    ):
        if _SHA256.fullmatch(value) is None:
            raise ValueError(f"Raw-probe {label} fingerprint is invalid")
    return f"raw-probes-{selection_sha256[:16]}-{provenance_fingerprint[:16]}"


def _canonical_raw_completion(
    *,
    target_cells: int,
    rendered: int,
    skipped: int,
) -> dict[str, int]:
    if target_cells <= 0 or rendered < 0 or skipped < 0 or rendered + skipped != target_cells:
        raise ValueError("Raw-probe render completion does not cover every target cell")
    return {"targetCells": target_cells, "completedCells": target_cells}


def audit_raw_probes(
    *,
    repo_root: Path,
    production_root: Path,
    game_source_root: Path,
    audit_root: Path,
    inventory: ValidatedInventory,
    seam_records: Sequence[Mapping[str, object]],
    probe_count: int,
    render_workers: int,
    image: str,
    magick: str,
    timeout_seconds: int,
    stabilization_verified: bool,
    progress: ProgressCallback | None,
) -> dict[str, object]:
    candidates = [record for record in seam_records if record.get("crossShard") is True]
    selected = _select_raw_probe_records(candidates, probe_count)
    adjacencies = [_adjacency_from_record(record) for record in selected]
    stabilized_sides: dict[TileKey, set[str]] = defaultdict(set)
    for candidate in candidates:
        edge = _adjacency_from_record(candidate)
        if edge.direction == "east":
            stabilized_sides[edge.first].add("east")
            stabilized_sides[edge.second].add("west")
        else:
            stabilized_sides[edge.first].add("north")
            stabilized_sides[edge.second].add("south")
    selection_sha256 = _sha256_bytes(
        _canonical_json_bytes([adjacency.identifier for adjacency in adjacencies])
    )
    cells = sorted(
        {
            cell_for_native_tile(tile)
            for adjacency in adjacencies
            for tile in (adjacency.first, adjacency.second)
        },
        key=lambda value: (value[1], value[0]),
    )
    provenance = resolve_production_provenance(
        repo_root=repo_root,
        source_root=game_source_root,
        image=image,
        magick=magick,
    )
    lexical_raw_root = audit_root / _raw_probe_cache_name(
        selection_sha256,
        provenance.fingerprint,
    )
    if lexical_raw_root.is_symlink():
        raise ValueError(f"Raw-probe cache root cannot be a symlink: {lexical_raw_root}")
    raw_root = lexical_raw_root.resolve(strict=False)
    if audit_root not in raw_root.parents:
        raise ValueError("Raw-probe cache root escapes the quality audit root")
    if provenance.fingerprint == inventory.provenance_fingerprint:
        provenance_compatibility: dict[str, object] = {
            "passes": True,
            "mode": "exact",
            "releasedProvenanceFingerprint": inventory.provenance_fingerprint,
            "candidateProvenanceFingerprint": provenance.fingerprint,
            "releasedImageId": inventory.provenance["image"]["id"],
            "candidateImageId": provenance.payload["image"]["id"],
            "candidatePayloadSha256": _sha256_bytes(
                _canonical_json_bytes(provenance.payload)
            ),
            "rendererContractEqual": True,
            "nonImageProvenanceEqual": True,
        }
    else:
        provenance_compatibility = _raw_probe_provenance_compatibility(
            inventory.provenance,
            provenance.payload,
        )
        if provenance_compatibility["passes"] is not True:
            raise ValueError(
                "Current raw-probe provenance is not output-compatible with released tiles"
            )
    publish_provenance_receipt(raw_root, provenance)

    def render_progress(done: int, total: int) -> None:
        if progress is not None:
            progress(f"[audit:raw-render {done}/{total}]")

    render = run_openmw_production(
        source_root=game_source_root,
        output_root=raw_root,
        cells=cells,
        provenance_fingerprint=provenance.fingerprint,
        image=image,
        magick=magick,
        timeout_seconds=timeout_seconds,
        retain_raw=True,
        workers=render_workers,
        progress=render_progress,
    )
    results: list[dict[str, object]] = []
    for index, (selected_record, adjacency) in enumerate(
        zip(selected, adjacencies, strict=True), start=1
    ):
        first_raw_path = raw_root / "raw" / adjacency.first.relative_path.with_suffix(".png")
        second_raw_path = raw_root / "raw" / adjacency.second.relative_path.with_suffix(".png")
        if not first_raw_path.is_file() or not second_raw_path.is_file():
            raise FileNotFoundError(f"Raw probe output is missing for {adjacency.identifier}")
        first_raw = _decode_rgba(first_raw_path, pixels=RAW_PIXELS, magick=magick)
        second_raw = _decode_rgba(second_raw_path, pixels=RAW_PIXELS, magick=magick)
        overlap_pixels = GUTTER_PIXELS * 2
        native_pixels = first_raw.width - overlap_pixels
        if adjacency.direction == "east":
            first_overlap = first_raw.crop(
                native_pixels, 0, overlap_pixels, first_raw.height
            )
            second_overlap = second_raw.crop(0, 0, overlap_pixels, second_raw.height)
        else:
            first_overlap = first_raw.crop(0, 0, first_raw.width, overlap_pixels)
            second_overlap = second_raw.crop(
                0, native_pixels, second_raw.width, overlap_pixels
            )
        overlap = _visual_difference(
            first_overlap,
            second_overlap,
            hard_pixel_delta=RAW_HARD_PIXEL_DELTA,
        )
        overlap_passes = (
            float(overlap["meanAbsoluteChannelDelta"]) <= RAW_MEAN_DELTA_MAX
            and float(overlap["p99PixelDelta"]) <= RAW_P99_DELTA_MAX
            and float(overlap["hardPixelFraction"]) <= RAW_HARD_FRACTION_MAX
            and float(overlap["alphaDifferingFraction"])
            <= RAW_ALPHA_DIFFERING_FRACTION_MAX
            and int(overlap["maximumOpaqueChannelDelta"])
            <= RAW_MAX_OPAQUE_DELTA_MAX
            and int(overlap["largestHardComponentPixels"])
            <= RAW_LARGEST_HARD_COMPONENT_MAX
        )
        release_seam_passes = (
            float(selected_record["meanExcessChannelDelta"])
            <= PAIR_MEAN_EXCESS_MAX
            and float(selected_record["p99PixelExcess"])
            <= CROSS_SHARD_P99_EXCESS_MAX
            and int(selected_record["maximumPixelExcess"])
            <= CROSS_SHARD_MAX_EXCESS_MAX
            and float(selected_record["hardPixelFraction"])
            <= CROSS_SHARD_HARD_FRACTION_MAX
        )
        first_repeat = _repeat_result(
            process_raw_master(first_raw_path, magick=magick),
            _decode_rgba(
                production_root / "tiles" / adjacency.first.relative_path,
                pixels=TILE_PIXELS,
                magick=magick,
            ),
            ignored_border_sides=stabilized_sides[adjacency.first],
        )
        second_repeat = _repeat_result(
            process_raw_master(second_raw_path, magick=magick),
            _decode_rgba(
                production_root / "tiles" / adjacency.second.relative_path,
                pixels=TILE_PIXELS,
                magick=magick,
            ),
            ignored_border_sides=stabilized_sides[adjacency.second],
        )
        repair_required = not overlap_passes
        repair_covered = repair_required and stabilization_verified
        pair_passes = (
            bool(first_repeat["passes"])
            and bool(second_repeat["passes"])
            and (
                overlap_passes
                or (repair_covered and release_seam_passes)
            )
        )
        results.append(
            {
                "id": adjacency.identifier,
                "cells": [
                    list(cell_for_native_tile(adjacency.first)),
                    list(cell_for_native_tile(adjacency.second)),
                ],
                "overlap": {
                    "passes": overlap_passes,
                    **overlap,
                },
                "sourceOverlapPasses": overlap_passes,
                "releaseSeamPasses": release_seam_passes,
                "repairRequired": repair_required,
                "repairCoveredByReceipt": repair_covered,
                "releasedRepeat": [first_repeat, second_repeat],
                "passes": pair_passes,
            }
        )
        if progress is not None:
            progress(f"[audit:raw-compare {index}/{probe_count}]")
    return {
        "passes": all(bool(result["passes"]) for result in results),
        "status": "passed"
        if all(bool(result["passes"]) for result in results)
        else "failed",
        "selectedCrossShardSeams": probe_count,
        "selectionSha256": selection_sha256,
        "uniqueCells": len(cells),
        **_canonical_raw_completion(
            target_cells=len(cells),
            rendered=render.rendered,
            skipped=render.skipped,
        ),
        "rendererProvenance": provenance_compatibility,
        "thresholds": {
            "overlapMeanDeltaMax": RAW_MEAN_DELTA_MAX,
            "overlapP99DeltaMax": RAW_P99_DELTA_MAX,
            "overlapHardPixelDelta": RAW_HARD_PIXEL_DELTA,
            "overlapHardFractionMax": RAW_HARD_FRACTION_MAX,
            "overlapAlphaDifferingFractionMax": RAW_ALPHA_DIFFERING_FRACTION_MAX,
            "overlapMaximumOpaqueDeltaMax": RAW_MAX_OPAQUE_DELTA_MAX,
            "overlapLargestHardComponentPixelsMax": RAW_LARGEST_HARD_COMPONENT_MAX,
            "repeatDifferingFractionMax": REPEAT_DIFFERING_FRACTION_MAX,
            "repeatMeanDeltaMax": REPEAT_MEAN_DELTA_MAX,
            "repeatP99DeltaMax": REPEAT_P99_DELTA_MAX,
            "repeatHardPixelDelta": REPEAT_HARD_PIXEL_DELTA,
            "repeatHardFractionMax": REPEAT_HARD_FRACTION_MAX,
            "repeatAlphaDifferingFractionMax": REPEAT_ALPHA_DIFFERING_FRACTION_MAX,
            "repeatMaximumOpaqueDeltaMax": REPEAT_MAX_OPAQUE_DELTA_MAX,
            "repeatLargestHardComponentPixelsMax": (
                REPEAT_LARGEST_HARD_COMPONENT_MAX
            ),
            "releaseMeanExcessMax": PAIR_MEAN_EXCESS_MAX,
            "releaseP99PixelExcessMax": CROSS_SHARD_P99_EXCESS_MAX,
            "releaseMaximumPixelExcessMax": CROSS_SHARD_MAX_EXCESS_MAX,
            "releaseHardPixelFractionMax": CROSS_SHARD_HARD_FRACTION_MAX,
        },
        "selectionStrategy": "pinned-plus-directional-risk-strata-v2",
        "pinnedProbeIds": list(PINNED_RAW_PROBE_IDS),
        "probes": results,
    }


def _copy_sample_pixel(
    destination: bytearray,
    destination_width: int,
    dx: int,
    dy: int,
    source: RgbaImage,
    sx: int,
    sy: int,
) -> None:
    source_offset = (sy * source.width + sx) * 4
    target_offset = (dy * destination_width + dx) * 4
    destination[target_offset : target_offset + 4] = source.pixels[
        source_offset : source_offset + 4
    ]


def build_contact_sheet(
    source_root: Path,
    seam_records: Sequence[Mapping[str, object]],
    output_path: Path,
    *,
    magick: str,
) -> dict[str, object]:
    cross = sorted(
        (record for record in seam_records if record.get("crossShard") is True),
        key=lambda value: (-float(value["meanExcessChannelDelta"]), str(value["id"])),
    )[:64]
    overall = sorted(
        seam_records,
        key=lambda value: (-float(value["meanExcessChannelDelta"]), str(value["id"])),
    )[:32]
    selected: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for record in [*cross, *overall]:
        identifier = str(record["id"])
        if identifier not in seen:
            selected.append(record)
            seen.add(identifier)
    columns = 8
    sample_size = 128
    rows = max(1, math.ceil(len(selected) / columns))
    width = columns * sample_size
    height = rows * sample_size
    canvas = bytearray(bytes((20, 18, 16, 255)) * (width * height))
    cache: dict[TileKey, RgbaImage] = {}

    def image_for(tile: TileKey) -> RgbaImage:
        if tile not in cache:
            cache[tile] = _decode_rgba(
                source_root / "tiles" / tile.relative_path,
                pixels=TILE_PIXELS,
                magick=magick,
            )
        return cache[tile]

    for ordinal, record in enumerate(selected):
        adjacency = _adjacency_from_record(record)
        first = image_for(adjacency.first)
        second = image_for(adjacency.second)
        origin_x = (ordinal % columns) * sample_size
        origin_y = (ordinal // columns) * sample_size
        for y in range(sample_size):
            for x in range(sample_size):
                if adjacency.direction == "east":
                    sy = min(TILE_PIXELS - 1, y * 4 + 2)
                    if x < 64:
                        source, sx = first, TILE_PIXELS - 64 + x
                    else:
                        source, sx = second, x - 64
                else:
                    sx = min(TILE_PIXELS - 1, x * 4 + 2)
                    if y < 64:
                        source, sy = second, TILE_PIXELS - 64 + y
                    else:
                        source, sy = first, y - 64
                _copy_sample_pixel(
                    canvas,
                    width,
                    origin_x + x,
                    origin_y + y,
                    source,
                    sx,
                    sy,
                )
        border = (220, 60, 50, 255) if record["flagged"] else (190, 150, 70, 255)
        for edge in range(sample_size):
            for bx, by in (
                (origin_x + edge, origin_y),
                (origin_x + edge, origin_y + sample_size - 1),
                (origin_x, origin_y + edge),
                (origin_x + sample_size - 1, origin_y + edge),
            ):
                offset = (by * width + bx) * 4
                canvas[offset : offset + 4] = bytes(border)
    encoded = encode_webp(
        RgbaImage(width, height, bytes(canvas)),
        executable=magick,
        lossless=True,
        quality=100,
        method=4,
    )
    _atomic_write(output_path, encoded)
    return {
        "samples": len(selected),
        "crossShardSamples": sum(record.get("crossShard") is True for record in selected),
        "width": width,
        "height": height,
        "sha256": _sha256_bytes(encoded),
        "bytes": len(encoded),
    }


def _artifact(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def report_with_hash(core: Mapping[str, object]) -> dict[str, object]:
    report = dict(core)
    report["auditSha256"] = _sha256_bytes(_canonical_json_bytes(core))
    return report


def _audit_implementation_sha256() -> str:
    return _sha256_file(Path(__file__).resolve())


def _load_reusable_report(
    path: Path,
    *,
    expected_identity: Mapping[str, str],
    expected_scope: Mapping[str, int],
) -> dict[str, Any]:
    report, _ = _read_json(path, "Previous quality audit report")
    if set(report) != EXPECTED_REPORT_KEYS:
        raise ValueError("Previous quality audit fields do not match the exact contract")
    audit_sha256 = report.get("auditSha256")
    core = {key: value for key, value in report.items() if key != "auditSha256"}
    if audit_sha256 != _sha256_bytes(_canonical_json_bytes(core)):
        raise ValueError("Previous quality audit logical hash does not recompute")
    if (
        report.get("schemaVersion") != AUDIT_SCHEMA_VERSION
        or report.get("datasetId") != DATASET_ID
        or report.get("snapshotId") != SNAPSHOT_ID
        or report.get("auditVersion") != AUDIT_VERSION
        or report.get("identity") != expected_identity
        or report.get("scope") != expected_scope
        or not isinstance(report.get("passes"), bool)
    ):
        raise ValueError("Previous quality audit identity cannot be reused")
    gates = report.get("gates")
    if not isinstance(gates, dict) or set(gates) != EXPECTED_GATES:
        raise ValueError("Previous quality audit gates are malformed")
    pyramid = gates.get("pyramidDerivation")
    if (
        not isinstance(pyramid, dict)
        or pyramid.get("passes") is not True
        or pyramid.get("parentsChecked") != EXPECTED_TOTAL_TILES - EXPECTED_NATIVE_TILES
        or pyramid.get("expectedParents") != EXPECTED_TOTAL_TILES - EXPECTED_NATIVE_TILES
        or pyramid.get("mismatches") != []
        or pyramid.get("tileCountsByZoom")
        != {str(key): value for key, value in EXPECTED_TILE_COUNTS.items()}
    ):
        raise ValueError("Previous quality audit pyramid gate cannot be reused")
    runtime = gates.get("runtimeResourcesCoordinates")
    if (
        not isinstance(runtime, dict)
        or runtime.get("passes") is not True
        or runtime.get("shards") != EXPECTED_SHARDS
        or runtime.get("resourceReports") != EXPECTED_SHARDS
        or runtime.get("targetMarkers") != EXPECTED_NATIVE_TILES
        or runtime.get("actionableMissingResources") != 0
        or runtime.get("maximumCoordinateErrorPixels") != 0.0
        or runtime.get("openmwCommit") != OPENMW_COMMIT
    ):
        raise ValueError("Previous quality audit runtime gate cannot be reused")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "tiles",
        "seams",
        "resourceRuntime",
        "worstSeams",
        "seamStabilization",
        "rawRendererProvenance",
    }:
        raise ValueError("Previous quality audit artifacts are malformed")
    runtime_artifact = artifacts.get("resourceRuntime")
    if not isinstance(runtime_artifact, dict) or set(runtime_artifact) != {
        "path",
        "sha256",
        "bytes",
    }:
        raise ValueError("Previous runtime artifact cannot be reused")
    relative = Path(str(runtime_artifact.get("path")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Previous runtime artifact path is unsafe")
    runtime_path = (path.parent / relative).resolve()
    if (
        path.parent.resolve() not in runtime_path.parents
        or not runtime_path.is_file()
        or runtime_path.is_symlink()
        or runtime_path.stat().st_size != runtime_artifact.get("bytes")
        or _sha256_file(runtime_path) != runtime_artifact.get("sha256")
    ):
        raise ValueError("Previous runtime artifact changed")
    runtime_value, _ = _read_json(runtime_path, "Previous runtime artifact")
    if runtime_value != runtime:
        raise ValueError("Previous runtime artifact does not equal its gate")
    return report


def _validated_audit_root(
    source_root: Path,
    game_source_root: Path,
    audit_root: Path,
) -> Path:
    lexical_audit_root = Path(os.path.abspath(audit_root))
    if lexical_audit_root.is_symlink():
        raise ValueError(f"Quality audit root cannot be a symlink: {lexical_audit_root}")
    resolved_audit_root = lexical_audit_root.resolve(strict=False)
    allowed_release_root = source_root / "quality-audit"
    overlaps_release = (
        resolved_audit_root == source_root
        or resolved_audit_root in source_root.parents
        or source_root in resolved_audit_root.parents
    )
    if overlaps_release and resolved_audit_root != allowed_release_root:
        raise ValueError(
            "Quality audit root may overlap the release only at its quality-audit directory"
        )
    if (
        resolved_audit_root == game_source_root
        or resolved_audit_root in game_source_root.parents
        or game_source_root in resolved_audit_root.parents
    ):
        raise ValueError("Quality audit root cannot overlap game source assets")
    return resolved_audit_root


def _create_audit_snapshot(source_root: Path, snapshot_root: Path) -> None:
    _copy_render_evidence(source_root, snapshot_root)
    shutil.copy2(
        source_root / STABILIZATION_RECEIPT,
        snapshot_root / STABILIZATION_RECEIPT,
    )
    _clone_tree(
        source_root / STABILIZATION_ROOT,
        snapshot_root / STABILIZATION_ROOT,
    )


def _run_full_audit_from_snapshot(
    *,
    repo_root: Path,
    source_root: Path,
    game_source_root: Path,
    audit_root: Path,
    workers: int,
    render_workers: int,
    probe_count: int,
    skip_raw_probes: bool,
    image: str,
    magick: str,
    timeout_seconds: int,
    reuse_evidence: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    if workers <= 0 or render_workers <= 0 or probe_count <= 0:
        raise ValueError("Worker and probe counts must be positive")
    source_root = source_root.resolve()
    game_source_root = game_source_root.resolve()
    audit_root = _validated_audit_root(source_root, game_source_root, audit_root)
    audit_root.mkdir(parents=True, exist_ok=True)

    if progress is not None:
        progress("[audit:inventory] validating hashes, provenance and exact tile tree")
    inventory = validate_source(source_root, progress=progress)
    recorded_magick = inventory.provenance.get("magickVersion")
    if not isinstance(recorded_magick, str) or not recorded_magick:
        raise ValueError("Render provenance ImageMagick identity is invalid")
    magick, current_toolchain = _resolve_stabilization_toolchain(
        repo_root=repo_root,
        magick=magick,
        expected_production_source_fingerprint=inventory.production_source_fingerprint,
        expected_magick_version=recorded_magick,
    )
    receipt = validate_stabilization_receipt(
        source_root,
        inventory,
        expected_toolchain=current_toolchain,
    )
    receipt_identity = receipt["identity"]
    assert isinstance(receipt_identity, dict)
    source_inventory_value, _ = _read_json(
        source_root / SOURCE_INVENTORY_PATH,
        "Archived render inventory",
    )
    render_inventory_entries = source_inventory_value.get("tiles")
    if not isinstance(render_inventory_entries, list):
        raise ValueError("Archived render inventory tiles are malformed")
    state_gate, _cells, shard_keys = audit_state_and_migrations(
        source_root,
        inventory,
        render_inventory_entries=render_inventory_entries,
    )
    stabilization_receipt_path = source_root / STABILIZATION_RECEIPT
    stabilization_gate = {
        "passes": True,
        "stabilizerVersion": receipt["stabilizerVersion"],
        "stabilizationFingerprint": receipt["stabilizationFingerprint"],
        "receiptSha256": receipt["receiptSha256"],
        "receiptFileSha256": _sha256_file(stabilization_receipt_path),
        "implementationSha256": receipt_identity["implementationSha256"],
        "postprocessToolchain": receipt_identity["postprocessToolchain"],
        "sourceInventorySha256": receipt_identity["sourceInventory"][
            "logicalSha256"
        ],
        "tileTransformsSha256": receipt_identity["tileTransforms"]["sha256"],
        "scope": receipt_identity["scope"],
    }
    identity = {
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
        "stabilizationFingerprint": receipt["stabilizationFingerprint"],
        "stabilizationReceiptSha256": receipt["receiptSha256"],
        "stabilizationReceiptFileSha256": _sha256_file(stabilization_receipt_path),
        "stabilizerImplementationSha256": stabilizer_implementation_sha256(),
        "sourceInventorySha256": receipt_identity["sourceInventory"][
            "logicalSha256"
        ],
        "auditImplementationSha256": _audit_implementation_sha256(),
    }
    expected_scope = {
        **EXPECTED_SCOPE,
        "rawCrossShardProbes": probe_count if not skip_raw_probes else 0,
    }
    previous = (
        _load_reusable_report(
            audit_root / "report.json",
            expected_identity=identity,
            expected_scope=expected_scope,
        )
        if reuse_evidence
        else None
    )

    tile_records, edges = audit_tiles(
        source_root,
        inventory,
        workers=workers,
        magick=magick,
        progress=progress,
    )
    tiles_path = audit_root / "tiles.ndjson"
    _write_ndjson(tiles_path, tile_records)
    nonempty = sum(int(record["alphaNonzeroPixels"]) > 0 for record in tile_records)
    alpha_gate = _binary_alpha_gate(tile_records)
    transparent_pixels = int(alpha_gate["alphaTransparentPixels"])
    opaque_pixels = int(alpha_gate["alphaOpaquePixels"])
    intermediate_pixels = int(alpha_gate["alphaIntermediatePixels"])
    inventory_gate = {
        "passes": (
            len(tile_records) == EXPECTED_TOTAL_TILES
            and nonempty == len(tile_records)
            and alpha_gate["passes"] is True
        ),
        "tileCount": len(tile_records),
        "totalBytes": inventory.total_bytes,
        "decoded512Rgba": len(tile_records),
        "nonemptyTiles": nonempty,
        **{key: value for key, value in alpha_gate.items() if key != "passes"},
        "inventorySha256": inventory.inventory_sha256,
        "inventoryFileSha256": inventory.inventory_file_sha256,
    }
    transform_records = _read_ndjson(source_root / TILE_TRANSFORMS_PATH)
    stabilization_rgba = _stabilization_rgba_gate(
        transform_records,
        tile_records,
        expected_touched_tiles=int(receipt_identity["scope"]["touchedTiles"]),
    )
    stabilization_gate.update(stabilization_rgba)
    receipt_output = receipt.get("output")
    receipt_alpha = (
        receipt_output.get("alphaEvidence")
        if isinstance(receipt_output, dict)
        else None
    )
    audited_alpha = {
        "mode": "binary-nonzero",
        "tilesChecked": len(tile_records),
        "transparentPixels": transparent_pixels,
        "opaquePixels": opaque_pixels,
        "intermediatePixels": intermediate_pixels,
    }
    stabilization_gate["alphaEvidence"] = receipt_alpha
    stabilization_gate["alphaEvidenceMatchesTiles"] = receipt_alpha == audited_alpha
    stabilization_gate["passes"] = bool(stabilization_gate["passes"]) and (
        receipt_alpha == audited_alpha
    )

    if previous is None:
        pyramid_gate = audit_pyramid(
            source_root,
            edges,
            workers=workers,
            magick=magick,
            progress=progress,
        )
    else:
        pyramid_gate = dict(previous["gates"]["pyramidDerivation"])
        if progress is not None:
            progress("[audit:pyramid reused 1480/1480]")
    seam_records, seam_gate = audit_seams(edges, progress=progress)
    seams_path = audit_root / "seams.ndjson"
    _write_ndjson(seams_path, seam_records)
    contact_path = audit_root / "worst-seams.webp"
    contact = build_contact_sheet(source_root, seam_records, contact_path, magick=magick)

    runtime_path = audit_root / "resource-runtime.json"
    if previous is None:
        runtime_gate = audit_runtime(source_root, shard_keys=shard_keys, progress=progress)
        _write_json(runtime_path, runtime_gate)
    else:
        runtime_gate = dict(previous["gates"]["runtimeResourcesCoordinates"])
        if progress is not None:
            progress("[audit:runtime reused 492/492]")

    if skip_raw_probes:
        raw_gate: dict[str, object] = {
            "passes": False,
            "status": "skipped",
            "reason": "Current-profile cross-shard raw probes were explicitly skipped",
            "selectedCrossShardSeams": 0,
        }
    else:
        raw_gate = audit_raw_probes(
            repo_root=repo_root,
            production_root=source_root,
            game_source_root=game_source_root,
            audit_root=audit_root,
            inventory=inventory,
            seam_records=seam_records,
            probe_count=probe_count,
            render_workers=render_workers,
            image=image,
            magick=magick,
            timeout_seconds=timeout_seconds,
            stabilization_verified=True,
            progress=progress,
        )

    gates: dict[str, object] = {
        "inventory": inventory_gate,
        "seamStabilization": stabilization_gate,
        "stateAndMigrations": state_gate,
        "pyramidDerivation": pyramid_gate,
        "finalSeams": seam_gate,
        "runtimeResourcesCoordinates": runtime_gate,
        "rawProbes": raw_gate,
    }
    passes = all(
        isinstance(value, dict) and value.get("passes") is True for value in gates.values()
    )
    artifacts = {
        "tiles": _artifact(tiles_path, audit_root),
        "seams": _artifact(seams_path, audit_root),
        "resourceRuntime": _artifact(runtime_path, audit_root),
        "worstSeams": _artifact(contact_path, audit_root),
    }
    stabilization_copy = audit_root / STABILIZATION_RECEIPT
    _atomic_write(stabilization_copy, stabilization_receipt_path.read_bytes())
    artifacts["seamStabilization"] = _artifact(stabilization_copy, audit_root)
    if not skip_raw_probes:
        renderer = raw_gate.get("rendererProvenance")
        if not isinstance(renderer, dict):
            raise RuntimeError("Raw renderer provenance evidence is malformed")
        selection_sha256 = raw_gate.get("selectionSha256")
        candidate_fingerprint = renderer.get("candidateProvenanceFingerprint")
        if not isinstance(selection_sha256, str) or not isinstance(
            candidate_fingerprint, str
        ):
            raise RuntimeError("Raw renderer provenance identity is malformed")
        raw_provenance_path = (
            audit_root
            / _raw_probe_cache_name(selection_sha256, candidate_fingerprint)
            / "provenance.json"
        )
        artifacts["rawRendererProvenance"] = _artifact(
            raw_provenance_path,
            audit_root,
        )
    core: dict[str, object] = {
        "schemaVersion": AUDIT_SCHEMA_VERSION,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "auditVersion": AUDIT_VERSION,
        "identity": identity,
        "scope": expected_scope,
        "gates": gates,
        "artifacts": artifacts,
        "contactSheet": contact,
        "limitations": [
            "The 32px raw gutters are retained only for the deterministic raw-probe sample, not all 492 production shards.",
            "Every final adjacency is audited; raw duplicate-gutter equality is re-rendered for 16 deterministic cross-shard controls, with receipt-bound one-pixel release repair required for any source mismatch.",
        ],
        "passes": passes,
    }
    report = report_with_hash(core)
    return report


def run_full_audit(
    *,
    repo_root: Path,
    source_root: Path,
    game_source_root: Path,
    audit_root: Path,
    workers: int,
    render_workers: int,
    probe_count: int,
    skip_raw_probes: bool,
    image: str,
    magick: str,
    timeout_seconds: int,
    reuse_evidence: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    if workers <= 0 or render_workers <= 0 or probe_count <= 0:
        raise ValueError("Worker and probe counts must be positive")
    repo_root = repo_root.resolve()
    source_root = source_root.resolve()
    game_source_root = game_source_root.resolve()
    audit_root = _validated_audit_root(source_root, game_source_root, audit_root)

    implementation_sha256 = _audit_implementation_sha256()
    source_inventory = validate_source(source_root, progress=progress)
    recorded_magick = source_inventory.provenance.get("magickVersion")
    if not isinstance(recorded_magick, str) or not recorded_magick:
        raise ValueError("Render provenance ImageMagick identity is invalid")
    resolved_magick, toolchain = _resolve_stabilization_toolchain(
        repo_root=repo_root,
        magick=magick,
        expected_production_source_fingerprint=(
            source_inventory.production_source_fingerprint
        ),
        expected_magick_version=recorded_magick,
    )
    source_receipt = validate_stabilization_receipt(
        source_root,
        source_inventory,
        expected_toolchain=toolchain,
    )
    source_receipt_bytes = (source_root / STABILIZATION_RECEIPT).read_bytes()

    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{source_root.name}.audit.",
            suffix=".tmp",
            dir=source_root.parent,
        )
    )
    temporary.rmdir()
    try:
        if progress is not None:
            progress("[audit:snapshot] cloning immutable release evidence")
        _create_audit_snapshot(source_root, temporary)
        snapshot_inventory = validate_source(temporary, progress=progress)
        _require_matching_source_snapshot(source_inventory, snapshot_inventory)
        snapshot_receipt = validate_stabilization_receipt(
            temporary,
            snapshot_inventory,
            expected_toolchain=toolchain,
        )
        if (
            snapshot_receipt != source_receipt
            or (temporary / STABILIZATION_RECEIPT).read_bytes()
            != source_receipt_bytes
        ):
            raise RuntimeError("Seam stabilization receipt changed while cloning audit snapshot")

        report = _run_full_audit_from_snapshot(
            repo_root=repo_root,
            source_root=temporary,
            game_source_root=game_source_root,
            audit_root=audit_root,
            workers=workers,
            render_workers=render_workers,
            probe_count=probe_count,
            skip_raw_probes=skip_raw_probes,
            image=image,
            magick=resolved_magick,
            timeout_seconds=timeout_seconds,
            reuse_evidence=reuse_evidence,
            progress=progress,
        )

        final_snapshot_inventory = validate_source(temporary, progress=progress)
        _require_matching_source_snapshot(snapshot_inventory, final_snapshot_inventory)
        final_snapshot_receipt = validate_stabilization_receipt(
            temporary,
            final_snapshot_inventory,
            expected_toolchain=toolchain,
        )
        if final_snapshot_receipt != snapshot_receipt:
            raise RuntimeError("Immutable audit snapshot changed during execution")

        final_source_inventory = validate_source(source_root, progress=progress)
        if _source_snapshot_identity(final_source_inventory) != _source_snapshot_identity(
            source_inventory
        ):
            raise RuntimeError("Release dataset changed during quality audit")
        final_source_receipt = validate_stabilization_receipt(
            source_root,
            final_source_inventory,
            expected_toolchain=toolchain,
        )
        if (
            final_source_receipt != source_receipt
            or (source_root / STABILIZATION_RECEIPT).read_bytes()
            != source_receipt_bytes
        ):
            raise RuntimeError("Seam stabilization receipt changed during quality audit")

        final_magick, final_toolchain = _resolve_stabilization_toolchain(
            repo_root=repo_root,
            magick=resolved_magick,
            expected_production_source_fingerprint=(
                source_inventory.production_source_fingerprint
            ),
            expected_magick_version=recorded_magick,
        )
        if final_magick != resolved_magick or final_toolchain != toolchain:
            raise RuntimeError("Quality audit toolchain changed during execution")
        if not skip_raw_probes:
            final_candidate = resolve_production_provenance(
                repo_root=repo_root,
                source_root=game_source_root,
                image=image,
                magick=resolved_magick,
            )
            _require_final_raw_probe_provenance(report, final_candidate)
        if _audit_implementation_sha256() != implementation_sha256:
            raise RuntimeError("Quality audit implementation changed during execution")
        identity = report.get("identity")
        if (
            not isinstance(identity, dict)
            or identity.get("auditImplementationSha256") != implementation_sha256
        ):
            raise RuntimeError("Quality audit report implementation identity is inconsistent")

        _write_json(audit_root / "report.json", report)
        return report
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Audit the finalized Poison Song basemap")
    subparsers = parser.add_subparsers(dest="command", required=True)
    full = subparsers.add_parser("full", help="Run every release quality gate")
    full.add_argument("--output", type=Path, default=repo_root / DEFAULT_STABILIZED_OUTPUT)
    full.add_argument("--source-root", type=Path, default=repo_root.parent / "morr-dev")
    full.add_argument("--audit-root", type=Path)
    full.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    full.add_argument("--render-workers", type=int, default=2)
    full.add_argument("--probe-count", type=int, default=16)
    full.add_argument("--skip-raw-probes", action="store_true")
    full.add_argument(
        "--reuse-evidence",
        action="store_true",
        help="Reuse a hash-bound passing pyramid/runtime gate from the previous report.",
    )
    full.add_argument("--image", default=DEFAULT_PRODUCTION_IMAGE)
    full.add_argument("--magick", default="magick")
    full.add_argument("--timeout-seconds", type=int, default=15 * 60)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    audit_root = (
        args.audit_root
        if args.audit_root is not None
        else output / "quality-audit"
    )
    report = run_full_audit(
        repo_root=repo_root,
        source_root=output,
        game_source_root=args.source_root,
        audit_root=audit_root,
        workers=args.workers,
        render_workers=args.render_workers,
        probe_count=args.probe_count,
        skip_raw_probes=args.skip_raw_probes,
        image=args.image,
        magick=args.magick,
        timeout_seconds=args.timeout_seconds,
        reuse_evidence=args.reuse_evidence,
        progress=_print_progress,
    )
    print(
        json.dumps(
            {
                "auditRoot": str(Path(os.path.abspath(audit_root)).resolve(strict=False)),
                "auditSha256": report["auditSha256"],
                "passes": report["passes"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["passes"] is True else 1


if __name__ == "__main__":
    sys.exit(main())
