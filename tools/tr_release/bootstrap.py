from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Mapping, Sequence

from tools.land_renderer.tiles import TileGrid
from tools.tr_release.model import RELEASE_PRODUCTION_SOURCE_PATHS


_SHA256 = re.compile(r"[0-9a-f]{64}")
_PACKAGING_NOISE = {".ds_store", "thumbs.db", "desktop.ini", "__macosx"}
_FROZEN_MODULES = (
    "tools.openmw_renderer.production",
    "tools.openmw_renderer.publish",
    "tools.openmw_renderer.stabilize",
    "tools.openmw_renderer.audit",
    "tools.catalog_pipeline.poison",
)


@dataclass(frozen=True, slots=True)
class RuntimeSourceInput:
    logical_id: str
    relative_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ActivatedRelease:
    production: ModuleType
    publish: ModuleType
    stabilize: ModuleType
    audit: ModuleType
    catalog: ModuleType


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _lock_section(lock: Mapping[str, Any], *names: str) -> Mapping[str, Any]:
    for name in names:
        value = lock.get(name)
        if isinstance(value, Mapping):
            return value
    return {}


def _source_inputs(lock: Mapping[str, Any]) -> tuple[RuntimeSourceInput, ...]:
    source = _lock_section(lock, "source")
    raw = source.get("inputs", lock.get("inputs"))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("Release lock inputs must be an array")
    result: list[RuntimeSourceInput] = []
    for index, item in enumerate(raw):
        entry = _require_mapping(item, f"release lock input {index}")
        logical_id = str(entry.get("id", entry.get("logicalId", "")))
        relative_path = str(entry.get("relativePath", entry.get("path", "")))
        sha256 = str(entry.get("sha256", ""))
        if not logical_id or not relative_path or _SHA256.fullmatch(sha256) is None:
            raise ValueError(f"Release lock input {index} is incomplete")
        result.append(RuntimeSourceInput(logical_id, relative_path, sha256))
    return tuple(result)


def _data_directories(profile: Mapping[str, Any]) -> tuple[str, ...]:
    raw = profile.get("dataDirectories")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("Release profile dataDirectories must be an array")
    result: list[str] = []
    for index, item in enumerate(raw):
        entry = _require_mapping(item, f"data directory {index}")
        value = str(entry.get("path", ""))
        if not value:
            raise ValueError(f"data directory {index} has no path")
        result.append(value)
    return tuple(result)


def _ordered_strings(profile: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = profile.get(key)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError(f"Release profile {key} must be an array")
    values = tuple(str(value) for value in raw)
    if not values or any(not value for value in values):
        raise ValueError(f"Release profile {key} cannot contain empty values")
    return values


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _input_audit(source_root: Path, inputs: Sequence[RuntimeSourceInput]) -> dict[str, dict[str, object]]:
    audit: dict[str, dict[str, object]] = {}
    for item in inputs:
        path = source_root / item.relative_path
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"Required TR release input is missing or unsafe: {path}")
        actual = _sha256_file(path)
        if actual != item.sha256:
            raise ValueError(
                f"TR release input hash mismatch for {item.relative_path}: "
                f"expected {item.sha256}, got {actual}"
            )
        audit[item.logical_id] = {
            "relativePath": item.relative_path,
            "bytes": path.stat().st_size,
            "sha256": actual,
        }
    return audit


def _tree_audit(source_root: Path, directories: Sequence[str]) -> dict[str, dict[str, object]]:
    audit: dict[str, dict[str, object]] = {}
    for relative_root in directories:
        root = source_root / relative_root
        if root.is_symlink() or not root.is_dir():
            raise FileNotFoundError(f"Required TR data directory is missing or unsafe: {root}")
        entries: list[tuple[str, int, str]] = []
        normalized: set[str] = set()
        for path in sorted(root.rglob("*"), key=lambda value: value.as_posix().casefold()):
            relative = path.relative_to(root)
            if any(part.casefold() in _PACKAGING_NOISE for part in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError(f"TR data directories cannot contain symlinks: {path}")
            if not path.is_file():
                continue
            relative_text = relative.as_posix()
            collision_key = relative_text.casefold()
            if collision_key in normalized:
                raise ValueError(
                    f"Case-insensitive TR resource collision in {relative_root}: {relative_text}"
                )
            normalized.add(collision_key)
            entries.append((relative_text, path.stat().st_size, _sha256_file(path)))
        digest = hashlib.sha256()
        for relative_text, byte_length, file_hash in entries:
            digest.update(relative_text.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(byte_length).encode("ascii"))
            digest.update(b"\0")
            digest.update(file_hash.encode("ascii"))
            digest.update(b"\n")
        audit[relative_root] = {
            "files": len(entries),
            "bytes": sum(item[1] for item in entries),
            "sha256": digest.hexdigest(),
        }
    return audit


def _expected_tree_audit(lock: Mapping[str, Any]) -> Mapping[str, Any]:
    source = _lock_section(lock, "source")
    value = source.get("dataTrees", source.get("assetTrees", lock.get("dataTrees", {})))
    if isinstance(value, Mapping):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: dict[str, Any] = {}
        for item in value:
            entry = _require_mapping(item, "release lock data tree")
            key = str(entry.get("path", entry.get("id", "")))
            if key:
                result[key] = {
                    name: entry[name]
                    for name in ("files", "bytes", "sha256")
                    if name in entry
                }
        return result
    return {}


def _normalize_tree_expectation(
    expected: Mapping[str, Any], directories: Sequence[str]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for directory in directories:
        direct = expected.get(directory)
        if direct is not None:
            result[directory] = direct
            continue
        matches = [
            value
            for value in expected.values()
            if isinstance(value, Mapping) and value.get("path") == directory
        ]
        if len(matches) != 1:
            raise ValueError(f"Release lock has no unique data-tree audit for {directory}")
        result[directory] = {
            name: matches[0][name]
            for name in ("files", "bytes", "sha256")
            if name in matches[0]
        }
    return result


def _quoted_path(root: PurePosixPath, relative: str) -> str:
    value = str(root / PurePosixPath(relative))
    if '"' in value or "\n" in value or "\r" in value:
        raise ValueError("OpenMW data paths cannot contain quotes or newlines")
    return f'"{value}"'


def _runtime_profile(profile: Mapping[str, Any], lock: Mapping[str, Any]) -> ModuleType:
    contract = importlib.import_module("tools.openmw_renderer.profile")
    model = importlib.import_module("tools.tr_release.model")
    parsed_profile = model.parse_profile(dict(profile))
    inputs = _source_inputs(lock)
    directories = _data_directories(profile)
    archives = _ordered_strings(profile, "fallbackArchives")
    content = _ordered_strings(profile, "contentFiles")
    inventory_only = _ordered_strings(profile, "inventoryOnlyFiles")
    expected_source = _require_mapping(lock.get("source"), "release lock source")
    expected_trees = {
        str(_require_mapping(item, "release lock data tree")["relativePath"]): {
            key: _require_mapping(item, "release lock data tree")[key]
            for key in ("files", "bytes", "sha256")
        }
        for item in expected_source.get("dataTrees", ())
    }
    profile_fingerprint = str(lock.get("profileFingerprint", ""))
    if _SHA256.fullmatch(profile_fingerprint) is None:
        raise ValueError("Release lock profileFingerprint is missing or invalid")

    module = ModuleType("tools.openmw_renderer.profile")
    module.__file__ = str(Path(__file__).resolve())
    module.SourceInput = RuntimeSourceInput
    module.PROFILE_ID = str(lock.get("datasetId", profile.get("datasetId", "")))
    module.OPENMW_RELEASE = contract.OPENMW_RELEASE
    module.OPENMW_COMMIT = contract.OPENMW_COMMIT
    module.OPENMW_SOURCE_URL = contract.OPENMW_SOURCE_URL
    module.DOCKER_PLATFORM = contract.DOCKER_PLATFORM
    module.UBUNTU_SNAPSHOT = contract.UBUNTU_SNAPSHOT
    module.DOCKER_BASE_IMAGE = contract.DOCKER_BASE_IMAGE
    module.DEFAULT_DOCKER_IMAGE = contract.DEFAULT_DOCKER_IMAGE
    module.SOURCE_INPUTS = inputs
    module.DATA_DIRECTORIES = directories
    module.FALLBACK_ARCHIVES = archives
    module.CONTENT_FILES = content
    module.EXCLUDED_DYNAMIC_CONTENT_FILES = inventory_only
    module.sha256_file = _sha256_file
    source_cache: dict[Path, Any] = {}

    def checked_source(source_root: Path) -> Any:
        resolved = Path(source_root).resolve()
        audit = source_cache.get(resolved)
        if audit is None:
            audit = model.check_source(parsed_profile, resolved)
            if audit.to_dict() != dict(expected_source):
                raise ValueError("TR source audit does not match release.lock.json")
            source_cache[resolved] = audit
        return audit

    def validate_source_inputs(
        source_root: Path, selected: Sequence[RuntimeSourceInput] = inputs
    ) -> dict[str, dict[str, object]]:
        if tuple(selected) != inputs:
            return _input_audit(Path(source_root), tuple(selected))
        audit = checked_source(Path(source_root))
        return {
            item.id: {
                "relativePath": item.relative_path,
                "bytes": item.bytes,
                "sha256": item.sha256,
            }
            for item in audit.inputs
        }

    def fingerprint_data_directories(source_root: Path) -> dict[str, dict[str, object]]:
        audit = checked_source(Path(source_root))
        return {
            item.relative_path: {
                "files": item.files,
                "bytes": item.bytes,
                "sha256": item.sha256,
            }
            for item in audit.data_trees
        }

    def render_openmw_cfg(*, game_root: PurePosixPath = PurePosixPath("/game")) -> str:
        lines = ["# Generated from config/tr-release.json. Do not edit.", "replace=config", "encoding=win1252"]
        lines.extend(f"fallback-archive={archive}" for archive in archives)
        lines.extend(f"data={_quoted_path(game_root, relative)}" for relative in directories)
        lines.extend(f"content={name}" for name in content)
        return "\n".join(lines) + "\n"

    def profile_fingerprint_fn(
        input_audit: Mapping[str, Any],
        *,
        asset_audit: Mapping[str, Any] | None = None,
        openmw_cfg: str | None = None,
        settings_cfg: str | None = None,
    ) -> str:
        del openmw_cfg, settings_cfg
        expected_inputs = {
            str(item["id"]): {
                "relativePath": item["relativePath"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in expected_source["inputs"]
        }
        if dict(input_audit) != expected_inputs:
            raise ValueError("TR release input audit differs from release.lock.json")
        if asset_audit is not None and dict(asset_audit) != expected_trees:
            raise ValueError("TR release asset audit differs from release.lock.json")
        return profile_fingerprint

    module.validate_source_inputs = validate_source_inputs
    module.fingerprint_data_directories = fingerprint_data_directories
    module.render_openmw_cfg = render_openmw_cfg
    module.render_settings_cfg = contract.render_settings_cfg
    module.render_console_script = contract.render_console_script
    module.profile_fingerprint = profile_fingerprint_fn
    return module


def _renderer_contract(lock: Mapping[str, Any]) -> Mapping[str, Any]:
    contract = _lock_section(lock, "renderer", "topology")
    if not contract:
        raise ValueError("Release lock renderer/topology contract is missing")
    return contract


def _integer_map(value: object, label: str) -> dict[int, int]:
    mapping = _require_mapping(value, label)
    result = {int(key): int(item) for key, item in mapping.items()}
    if not result or min(result.values()) < 0:
        raise ValueError(f"{label} is empty or invalid")
    return result


def _adjacency_map(value: object) -> dict[tuple[int, str], int]:
    mapping = _require_mapping(value, "renderer adjacencies")
    result: dict[tuple[int, str], int] = {}
    for key, item in mapping.items():
        if isinstance(item, Mapping):
            for direction, count in item.items():
                result[(int(key), str(direction))] = int(count)
            continue
        zoom, direction = str(key).split(":", 1)
        result[(int(zoom), direction)] = int(item)
    return result


def _scope(contract: Mapping[str, Any]) -> dict[str, int]:
    direct = contract.get("scope")
    if isinstance(direct, Mapping):
        return {str(key): int(value) for key, value in direct.items()}
    tile_counts = _integer_map(contract.get("tileCounts"), "renderer tileCounts")
    native_zoom = max(tile_counts)
    total = sum(tile_counts.values())
    adjacency = _adjacency_map(contract.get("adjacencies"))
    return {
        "tiles": total,
        "nativeTiles": tile_counts[native_zoom],
        "lowerZoomTiles": total - tile_counts[native_zoom],
        "shards": int(contract["shards"]),
        "allFinalAdjacencies": sum(adjacency.values()),
        "nativeAdjacencies": sum(
            count for (zoom, _), count in adjacency.items() if zoom == native_zoom
        ),
        "nativeCrossShardAdjacencies": int(contract["nativeCrossShardAdjacencies"]),
        "rawCrossShardProbes": int(contract.get("rawCrossShardProbes", 16)),
    }


def _profile_regions(profile: Mapping[str, Any]) -> tuple[str, ...]:
    raw = profile.get("regions")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("Release profile regions must be an array")
    result = tuple(
        str(_require_mapping(item, "release region").get("id", "")) for item in raw
    )
    if not result or any(not item for item in result):
        raise ValueError("Release profile regions are invalid")
    return result


def activate(profile: Mapping[str, Any], lock: Mapping[str, Any]) -> ActivatedRelease:
    already_loaded = [name for name in _FROZEN_MODULES if name in sys.modules]
    if already_loaded:
        raise RuntimeError(
            "TR release bootstrap requires a fresh subprocess before pipeline modules "
            f"are imported: {already_loaded}"
        )
    dataset_id = str(lock.get("datasetId", ""))
    snapshot_id = str(lock.get("snapshotId", ""))
    if not dataset_id or not snapshot_id or profile.get("datasetId") != dataset_id:
        raise ValueError("Release profile/lock dataset identity mismatch")
    contract = _renderer_contract(lock)
    extent = tuple(int(value) for value in contract.get("extent", ()))
    origin = tuple(int(value) for value in contract.get("origin", ()))
    if len(extent) != 4 or len(origin) != 2:
        raise ValueError("Release renderer extent/origin are invalid")
    tile_counts = _integer_map(contract.get("tileCounts"), "renderer tileCounts")
    adjacencies = _adjacency_map(contract.get("adjacencies"))
    scope = _scope(contract)
    probe_ids = tuple(str(value) for value in contract.get("pinnedRawProbeIds", ()))
    if len(probe_ids) < 2:
        raise ValueError("Release renderer must pin at least two raw probe IDs")

    sys.modules["tools.openmw_renderer.profile"] = _runtime_profile(profile, lock)
    production = importlib.import_module("tools.openmw_renderer.production")
    production.DATASET_ID = dataset_id
    production.SNAPSHOT_ID = snapshot_id
    production.PINNED_PROFILE_FINGERPRINT = str(lock["profileFingerprint"])
    production.DEFAULT_OUTPUT = Path("local-data/tr-release/production") / dataset_id
    production.DEFAULT_PRODUCTION_IMAGE = "morrowind-map-openmw:0.51.0-tr"
    production.POISON_WORLD_EXTENT = extent
    production.POISON_SONG_TILE_GRID = TileGrid(float(origin[0]), float(origin[1]))
    production.PRODUCTION_SOURCE_PATHS = tuple(
        dict.fromkeys(
            (*production.PRODUCTION_SOURCE_PATHS, *RELEASE_PRODUCTION_SOURCE_PATHS)
        )
    )

    publish = importlib.import_module("tools.openmw_renderer.publish")
    publish.TILE_PYRAMID_ID = f"{dataset_id}.basemap"
    publish.TILE_REGIONS = _profile_regions(profile)
    publish.EXPECTED_TILE_COUNTS = tile_counts
    publish.PINNED_RAW_PROBE_IDS = probe_ids
    publish.EXPECTED_PLAN_FINGERPRINT = str(contract["planFingerprint"])
    publish.DEFAULT_RELEASE_OUTPUT = Path("local-data/tr-release/release") / dataset_id
    publish.DEFAULT_METADATA_ROOT = Path("apps/web/public/datasets/metadata") / dataset_id
    publish.POISON_WORLD_EXTENT = extent
    publish.EXPECTED_QUALITY_SCOPE = scope

    stabilize = importlib.import_module("tools.openmw_renderer.stabilize")
    stabilize.DEFAULT_STABILIZED_OUTPUT = Path("local-data/tr-release/release") / dataset_id
    stabilize.EXPECTED_CROSS_SHARD_EDGES = scope["nativeCrossShardAdjacencies"]

    audit = importlib.import_module("tools.openmw_renderer.audit")
    audit.EXPECTED_TILE_COUNTS = tile_counts
    audit.EXPECTED_ADJACENCIES = {key: value for key, value in adjacencies.items() if value}
    audit.EXPECTED_TOTAL_TILES = scope["tiles"]
    audit.EXPECTED_NATIVE_TILES = scope["nativeTiles"]
    audit.EXPECTED_SHARDS = scope["shards"]
    audit.EXPECTED_TOTAL_ADJACENCIES = scope["allFinalAdjacencies"]
    audit.EXPECTED_NATIVE_ADJACENCIES = scope["nativeAdjacencies"]
    audit.EXPECTED_NATIVE_CROSS_SHARD = scope["nativeCrossShardAdjacencies"]
    audit.PINNED_RAW_PROBE_IDS = probe_ids
    audit.EXPECTED_SCOPE = scope

    catalog = importlib.import_module("tools.catalog_pipeline.poison")
    catalog.DATASET_ID = dataset_id
    catalog.SNAPSHOT_ID = snapshot_id
    input_by_name = {
        Path(item.relative_path).name.casefold(): item.logical_id for item in _source_inputs(lock)
    }
    catalog.CATALOG_SOURCE_IDS = tuple(input_by_name[name.casefold()] for name in _ordered_strings(profile, "contentFiles"))
    catalog.PLUGIN_REGIONS = {
        str(key): str(value)
        for key, value in _require_mapping(profile.get("pluginRegions"), "pluginRegions").items()
    }
    catalog.MAP_EXTENT = extent
    locked_inputs = {item.logical_id: item for item in _source_inputs(lock)}
    catalog.MASTER_SIZE_EXCEPTIONS = tuple(
        {
            "dependentSha256": locked_inputs[str(item["dependentInputId"])].sha256,
            "masterSha256": locked_inputs[str(item["masterInputId"])].sha256,
            "advertisedBytes": int(item["advertisedBytes"]),
            "actualBytes": int(item["actualBytes"]),
            "reason": str(item["reason"]),
        }
        for item in profile.get("masterSizeExceptions", ())
    )
    catalog_contract = _lock_section(lock, "catalog")
    catalog.EXPECTED_WORLD_COUNTS = dict(catalog_contract.get("worldCounts", {}))
    catalog.EXPECTED_CATALOG_COUNTS = dict(catalog_contract.get("catalogCounts", {}))
    catalog.EXPECTED_RESOLUTION_COUNTS = dict(catalog_contract.get("resolutionCounts", {}))
    catalog.EXPECTED_REGION_COUNTS = dict(catalog_contract.get("regionCounts", {}))
    catalog.EXPECTED_EXCLUSIONS = dict(catalog_contract.get("exclusions", {}))
    catalog.EXPECTED_DROPPED = dict(catalog_contract.get("dropped", {}))

    return ActivatedRelease(production, publish, stabilize, audit, catalog)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
