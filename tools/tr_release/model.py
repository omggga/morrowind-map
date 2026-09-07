from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
MAP_KEY = "tamriel-rebuilt"
PROVINCE_RELEASES = {
    "project-cyrodiil": ("pc", "project-cyrodiil-core", "Cyr_Main.esm", "cyr-main-esm", "cyrodiil"),
    "home-of-nords": ("shotn", "home-of-nords-core", "Sky_Main.esm", "sky-main-esm", "skyrim"),
}
DATA_DIRECTORY_IDS = ("base-game", "tamriel-data", "tamriel-rebuilt-core")
FALLBACK_ARCHIVES = ("Morrowind.bsa", "Tribunal.bsa", "Bloodmoon.bsa")
CONTENT_FILES = (
    "Morrowind.esm",
    "Tribunal.esm",
    "Bloodmoon.esm",
    "Tamriel_Data.esm",
    "TR_Mainland.esm",
)
INVENTORY_ONLY_FILES = ("Tamriel_Data.omwscripts", "tamrielrebuilt.omwscripts")
CELL_SIZE = 8_192
NATIVE_ZOOM = 7
SNAPSHOT_FINGERPRINT_LENGTH = 16
ADOPTED_SNAPSHOT_ID = "tr:poison-song-26.08:6964517551e0fcb0"
ADOPTED_SNAPSHOT_DATASET_ID = "poison-song-26.08"
RELEASE_PRODUCTION_SOURCE_PATHS = (
    "tools/tr_release/model.py",
    "tools/tr_release/bootstrap.py",
    "tools/tr_release/cli.py",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SLUG = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_LOCALE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_NOISE_FILES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
_NOISE_DIRECTORIES = frozenset({"__macosx"})
_CONTROLLED_INPUT_SUFFIXES = frozenset(
    {".bsa", ".ba2", ".esm", ".esp", ".omwaddon", ".omwgame", ".omwscripts"}
)

BASE_INPUT_HASHES = {
    "morrowind-esm": "5c3c8c2cbd20e25901b59b3ece33d36b7ef0e3d60ad8d11828bcc61a5ead1647",
    "tribunal-esm": "2ace511f23cc2a9ddd5f3aa59c7919789b9378cf4b17c8ae3375dd6b782f3f2b",
    "bloodmoon-esm": "bd27090d0e6ad4c1bf1abc83f1a2dac56fcc82cae7bfe8263c413fb301801357",
    "morrowind-bsa": "3dcd5e6bfa08245521a53374bf733ee5c920df49103898a15aa31144ad64cf48",
    "tribunal-bsa": "3901e7a146f7a64a4ae9534c80d5974f7ab15adf5c48c4561d9313c0f7831d69",
    "bloodmoon-bsa": "7c20956791400d958cb407f0b7c1c19ceaf46719df7eb724d0b450299360bd7c",
}

INPUT_LAYOUT = (
    ("morrowind-esm", "base-game", "Morrowind.esm"),
    ("tribunal-esm", "base-game", "Tribunal.esm"),
    ("bloodmoon-esm", "base-game", "Bloodmoon.esm"),
    ("morrowind-bsa", "base-game", "Morrowind.bsa"),
    ("tribunal-bsa", "base-game", "Tribunal.bsa"),
    ("bloodmoon-bsa", "base-game", "Bloodmoon.bsa"),
    ("tamriel-data-esm", "tamriel-data", "Tamriel_Data.esm"),
    ("tamriel-data-scripts", "tamriel-data", "Tamriel_Data.omwscripts"),
    ("tr-mainland-esm", "tamriel-rebuilt-core", "TR_Mainland.esm"),
    ("tr-mainland-scripts", "tamriel-rebuilt-core", "tamrielrebuilt.omwscripts"),
)


class ProfileError(ValueError):
    """A human-authored TR release profile violates the strict contract."""


@dataclass(frozen=True, slots=True)
class ReleaseMetadata:
    name: str
    version: str
    build: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version, "build": self.build}


@dataclass(frozen=True, slots=True)
class DataDirectory:
    id: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "path": self.path}


@dataclass(frozen=True, slots=True)
class RequiredInput:
    id: str
    directory_id: str
    filename: str
    sha256: str | None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "directoryId": self.directory_id,
            "filename": self.filename,
        }
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        return result


@dataclass(frozen=True, slots=True)
class ExcludedOptionalModule:
    id: str
    relative_path: str

    @property
    def content_file(self) -> str:
        return PurePosixPath(self.relative_path).name

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "relativePath": self.relative_path}


@dataclass(frozen=True, slots=True)
class Region:
    id: str
    title: tuple[tuple[str, str], ...]
    kind: str
    status: str

    @property
    def localized_title(self) -> dict[str, str]:
        return dict(self.title)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": dict(self.title),
            "kind": self.kind,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class MasterSizeException:
    dependent_input_id: str
    master_input_id: str
    advertised_bytes: int
    actual_bytes: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "dependentInputId": self.dependent_input_id,
            "masterInputId": self.master_input_id,
            "advertisedBytes": self.advertised_bytes,
            "actualBytes": self.actual_bytes,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SmokeCenter:
    id: str
    cell: tuple[int, int]

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "cell": list(self.cell)}


@dataclass(frozen=True, slots=True)
class ReleaseProfile:
    schema_version: int
    dataset_id: str
    map_key: str
    title: tuple[tuple[str, str], ...]
    summary: tuple[tuple[str, str], ...]
    release: ReleaseMetadata
    data_directories: tuple[DataDirectory, ...]
    fallback_archives: tuple[str, ...]
    content_files: tuple[str, ...]
    inventory_only_files: tuple[str, ...]
    excluded_optional_modules: tuple[ExcludedOptionalModule, ...]
    regions: tuple[Region, ...]
    plugin_regions: tuple[tuple[str, str], ...]
    required_inputs: tuple[RequiredInput, ...]
    master_size_exceptions: tuple[MasterSizeException, ...]
    smoke_centers: tuple[SmokeCenter, ...]
    adopted_snapshot_id: str | None = None

    @property
    def snapshot_prefix(self) -> str:
        return PROVINCE_RELEASES[self.map_key][0] if self.map_key in PROVINCE_RELEASES else "tr"

    @property
    def land_content_files(self) -> tuple[str, ...]:
        return (PROVINCE_RELEASES[self.map_key][2],) if self.map_key in PROVINCE_RELEASES else self.content_files

    @property
    def catalog_regions(self) -> tuple[str, ...] | None:
        return (PROVINCE_RELEASES[self.map_key][4],) if self.map_key in PROVINCE_RELEASES else None

    @property
    def localized_title(self) -> dict[str, str]:
        return dict(self.title)

    @property
    def localized_summary(self) -> dict[str, str]:
        return dict(self.summary)

    @property
    def plugin_region_map(self) -> dict[str, str]:
        return dict(self.plugin_regions)

    @property
    def directory_by_id(self) -> dict[str, DataDirectory]:
        return {item.id: item for item in self.data_directories}

    @property
    def input_by_id(self) -> dict[str, RequiredInput]:
        return {item.id: item for item in self.required_inputs}

    def input_relative_path(self, item: RequiredInput) -> str:
        return str(PurePosixPath(self.directory_by_id[item.directory_id].path) / item.filename)

    def to_dict(self, *, include_adopted_snapshot: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "datasetId": self.dataset_id,
            "mapKey": self.map_key,
            "title": dict(self.title),
            "summary": dict(self.summary),
            "release": self.release.to_dict(),
            "dataDirectories": [item.to_dict() for item in self.data_directories],
            "fallbackArchives": list(self.fallback_archives),
            "contentFiles": list(self.content_files),
            "inventoryOnlyFiles": list(self.inventory_only_files),
            "excludedOptionalModules": [
                item.to_dict() for item in self.excluded_optional_modules
            ],
            "regions": [item.to_dict() for item in self.regions],
            "pluginRegions": dict(self.plugin_regions),
            "requiredInputs": [item.to_dict() for item in self.required_inputs],
            "masterSizeExceptions": [
                item.to_dict() for item in self.master_size_exceptions
            ],
            "smokeCenters": [item.to_dict() for item in self.smoke_centers],
        }
        if include_adopted_snapshot and self.adopted_snapshot_id is not None:
            result["adoptedSnapshotId"] = self.adopted_snapshot_id
        return result


@dataclass(frozen=True, slots=True)
class InputLock:
    id: str
    directory_id: str
    filename: str
    relative_path: str
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "directoryId": self.directory_id,
            "filename": self.filename,
            "relativePath": self.relative_path,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class DataTreeFingerprint:
    id: str
    relative_path: str
    files: int
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "relativePath": self.relative_path,
            "files": self.files,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class SourceAudit:
    inputs: tuple[InputLock, ...]
    data_trees: tuple[DataTreeFingerprint, ...]

    @property
    def input_by_id(self) -> dict[str, InputLock]:
        return {item.id: item for item in self.inputs}

    def to_dict(self) -> dict[str, object]:
        return {
            "inputs": [item.to_dict() for item in self.inputs],
            "dataTrees": [item.to_dict() for item in self.data_trees],
        }


@dataclass(frozen=True, slots=True)
class ReleaseLock:
    profile: ReleaseProfile
    source_audit: SourceAudit
    profile_fingerprint: str
    derived_snapshot_id: str
    snapshot_id: str

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schemaVersion": SCHEMA_VERSION,
            "datasetId": self.profile.dataset_id,
            "mapKey": self.profile.map_key,
            "profileFingerprint": self.profile_fingerprint,
            "derivedSnapshotId": self.derived_snapshot_id,
            "snapshotId": self.snapshot_id,
            "profile": self.profile.to_dict(),
            "source": self.source_audit.to_dict(),
        }
        if self.profile.adopted_snapshot_id is not None:
            result["adoptedSnapshotId"] = self.profile.adopted_snapshot_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class ZoomTopology:
    zoom: int
    tile_count: int
    east_adjacencies: int
    north_adjacencies: int

    @property
    def adjacencies(self) -> int:
        return self.east_adjacencies + self.north_adjacencies

    def to_dict(self) -> dict[str, int]:
        return {
            "zoom": self.zoom,
            "tiles": self.tile_count,
            "eastAdjacencies": self.east_adjacencies,
            "northAdjacencies": self.north_adjacencies,
            "adjacencies": self.adjacencies,
        }


@dataclass(frozen=True, slots=True)
class LandTopology:
    effective_cells: int
    extent: tuple[int, int, int, int]
    origin: tuple[int, int]
    min_zoom: int
    native_zoom: int
    zooms: tuple[ZoomTopology, ...]
    shard_centers: tuple[tuple[int, int], ...]
    native_cross_shard_adjacencies: int
    probes: tuple[str, ...]

    @property
    def total_tiles(self) -> int:
        return sum(item.tile_count for item in self.zooms)

    @property
    def total_adjacencies(self) -> int:
        return sum(item.adjacencies for item in self.zooms)

    def to_dict(self) -> dict[str, object]:
        return {
            "effectiveCells": self.effective_cells,
            "extent": list(self.extent),
            "origin": list(self.origin),
            "minZoom": self.min_zoom,
            "nativeZoom": self.native_zoom,
            "zooms": [item.to_dict() for item in self.zooms],
            "totalTiles": self.total_tiles,
            "totalAdjacencies": self.total_adjacencies,
            "shards": len(self.shard_centers),
            "shardCenters": [list(item) for item in self.shard_centers],
            "nativeCrossShardAdjacencies": self.native_cross_shard_adjacencies,
            "probes": list(self.probes),
        }


def canonical_json_bytes(value: object) -> bytes:
    """Encode JSON identically on every supported host and reject non-JSON floats."""

    def validate(item: object, location: str) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"Non-finite number at {location}")
            return
        if isinstance(item, dict):
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"Non-string object key at {location}")
                validate(nested, f"{location}.{key}")
            return
        if isinstance(item, (list, tuple)):
            for index, nested in enumerate(item):
                validate(nested, f"{location}[{index}]")
            return
        raise ValueError(f"Unsupported JSON value at {location}: {type(item).__name__}")

    try:
        validate(value, "$")
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"Value is not canonical JSON: {error}") from error


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise ProfileError(f"Invalid JSON numeric constant: {value}")


def load_profile(path: Path | str) -> ReleaseProfile:
    profile_path = Path(path)
    if profile_path.is_symlink():
        raise ProfileError(f"Release profile cannot be a symlink: {profile_path}")
    if not profile_path.is_file():
        raise FileNotFoundError(f"Release profile is missing: {profile_path}")
    try:
        raw = json.loads(
            profile_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_invalid_constant,
        )
    except UnicodeDecodeError as error:
        raise ProfileError(f"Release profile must be UTF-8: {profile_path}") from error
    except json.JSONDecodeError as error:
        raise ProfileError(f"Invalid release profile JSON: {error}") from error
    return parse_profile(raw)


def _object(
    value: object,
    label: str,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProfileError(f"{label} must be an object")
    keys = set(value)
    unknown = keys - required - optional
    missing = required - keys
    if unknown:
        raise ProfileError(f"{label} has unknown keys: {', '.join(sorted(unknown))}")
    if missing:
        raise ProfileError(f"{label} is missing keys: {', '.join(sorted(missing))}")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProfileError(f"{label} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ProfileError(f"{label} cannot contain control characters")
    return value


def _slug(value: object, label: str) -> str:
    result = _text(value, label)
    if not _SLUG.fullmatch(result):
        raise ProfileError(f"{label} must be a lowercase slug")
    return result


def _localized(value: object, label: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or not value:
        raise ProfileError(f"{label} must be a non-empty locale object")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for locale, text in value.items():
        if not isinstance(locale, str) or not _LOCALE.fullmatch(locale):
            raise ProfileError(f"{label} has an invalid locale: {locale!r}")
        folded = locale.casefold()
        if folded in seen:
            raise ProfileError(f"{label} has a case-insensitive locale collision: {locale}")
        seen.add(folded)
        result.append((locale, _text(text, f"{label}.{locale}")))
    if set(value) != {"en"}:
        raise ProfileError(f"{label} must define exactly the en locale")
    return tuple(sorted(result))


def _casefold_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _ensure_unique(values: Iterable[str], label: str) -> None:
    seen: dict[str, str] = {}
    for value in values:
        folded = _casefold_key(value)
        previous = seen.get(folded)
        if previous is not None:
            raise ProfileError(f"{label} has a case-insensitive collision: {previous!r}, {value!r}")
        seen[folded] = value


def _safe_relative_path(value: object, label: str) -> str:
    result = _text(value, label)
    if "\\" in result:
        raise ProfileError(f"{label} must use forward slashes")
    candidate = PurePosixPath(result)
    if candidate.is_absolute() or result != candidate.as_posix():
        raise ProfileError(f"{label} must be a canonical source-root-relative path")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ProfileError(f"{label} contains an unsafe path component")
    return result


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProfileError(f"{label} must be an array")
    result = tuple(_text(item, f"{label}[]") for item in value)
    _ensure_unique(result, label)
    return result


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProfileError(f"{label} must be a positive integer")
    return value


def parse_profile(value: object) -> ReleaseProfile:
    root = _object(
        value,
        "profile",
        required={
            "schemaVersion",
            "datasetId",
            "mapKey",
            "title",
            "summary",
            "release",
            "dataDirectories",
            "fallbackArchives",
            "contentFiles",
            "inventoryOnlyFiles",
            "excludedOptionalModules",
            "regions",
            "pluginRegions",
            "requiredInputs",
            "masterSizeExceptions",
            "smokeCenters",
        },
        optional={"adoptedSnapshotId"},
    )
    if isinstance(root["schemaVersion"], bool) or root["schemaVersion"] != SCHEMA_VERSION:
        raise ProfileError(f"schemaVersion must be {SCHEMA_VERSION}")
    dataset_id = _slug(root["datasetId"], "datasetId")
    map_key = root["mapKey"]
    if map_key not in (MAP_KEY, *PROVINCE_RELEASES):
        raise ProfileError("mapKey must identify a supported release")
    directory_ids = DATA_DIRECTORY_IDS
    content_order = CONTENT_FILES
    inventory_order = INVENTORY_ONLY_FILES
    input_layout = INPUT_LAYOUT
    if map_key in PROVINCE_RELEASES:
        _, directory_id, plugin_name, input_id, _ = PROVINCE_RELEASES[map_key]
        directory_ids = (*DATA_DIRECTORY_IDS[:2], directory_id)
        content_order = (*CONTENT_FILES[:4], plugin_name)
        inventory_order = INVENTORY_ONLY_FILES[:1]
        input_layout = (*INPUT_LAYOUT[:8], (input_id, directory_id, plugin_name))
    title = _localized(root["title"], "title")
    summary = _localized(root["summary"], "summary")
    if {item[0] for item in title} != {item[0] for item in summary}:
        raise ProfileError("title and summary must define the same locales")

    release_raw = _object(
        root["release"], "release", required={"name", "version", "build"}
    )
    release = ReleaseMetadata(
        _text(release_raw["name"], "release.name"),
        _text(release_raw["version"], "release.version"),
        _text(release_raw["build"], "release.build"),
    )

    directories_raw = root["dataDirectories"]
    if not isinstance(directories_raw, list):
        raise ProfileError("dataDirectories must be an array")
    directories: list[DataDirectory] = []
    for index, raw in enumerate(directories_raw):
        item = _object(raw, f"dataDirectories[{index}]", required={"id", "path"})
        directories.append(
            DataDirectory(
                _slug(item["id"], f"dataDirectories[{index}].id"),
                _safe_relative_path(item["path"], f"dataDirectories[{index}].path"),
            )
        )
    if tuple(item.id for item in directories) != directory_ids:
        raise ProfileError(f"dataDirectories ids/order must be {directory_ids!r}")
    _ensure_unique((item.path for item in directories), "dataDirectories paths")
    directory_parts = [PurePosixPath(item.path).parts for item in directories]
    for index, first in enumerate(directory_parts):
        for second in directory_parts[index + 1 :]:
            shorter = min(len(first), len(second))
            if tuple(part.casefold() for part in first[:shorter]) == tuple(
                part.casefold() for part in second[:shorter]
            ):
                raise ProfileError("dataDirectories paths cannot overlap")

    fallback_archives = _string_list(root["fallbackArchives"], "fallbackArchives")
    if fallback_archives != FALLBACK_ARCHIVES:
        raise ProfileError(f"fallbackArchives must exactly equal {FALLBACK_ARCHIVES!r}")
    content_files = _string_list(root["contentFiles"], "contentFiles")
    inventory_only = _string_list(root["inventoryOnlyFiles"], "inventoryOnlyFiles")
    if inventory_only != inventory_order:
        raise ProfileError(f"inventoryOnlyFiles must exactly equal {inventory_order!r}")

    excluded_raw = root["excludedOptionalModules"]
    if not isinstance(excluded_raw, list):
        raise ProfileError("excludedOptionalModules must be an array")
    excluded: list[ExcludedOptionalModule] = []
    for index, raw in enumerate(excluded_raw):
        item = _object(
            raw,
            f"excludedOptionalModules[{index}]",
            required={"id", "relativePath"},
        )
        module = ExcludedOptionalModule(
            _slug(item["id"], f"excludedOptionalModules[{index}].id"),
            _safe_relative_path(
                item["relativePath"], f"excludedOptionalModules[{index}].relativePath"
            ),
        )
        if PurePosixPath(module.relative_path).suffix.casefold() not in {
            ".esp",
            ".esm",
            ".omwaddon",
        }:
            raise ProfileError("excluded optional modules must be content plugins")
        excluded.append(module)
    _ensure_unique((item.id for item in excluded), "excludedOptionalModules ids")
    _ensure_unique((item.relative_path for item in excluded), "excludedOptionalModules paths")
    excluded_names = {_casefold_key(item.content_file) for item in excluded}
    included_optional = [item for item in content_files if _casefold_key(item) in excluded_names]
    if included_optional:
        raise ProfileError(f"Excluded optional modules cannot be in contentFiles: {included_optional}")
    if content_files != content_order:
        raise ProfileError(f"contentFiles must exactly equal {content_order!r}")
    if {_casefold_key(item) for item in content_files} & {
        _casefold_key(item) for item in inventory_only
    }:
        raise ProfileError("inventoryOnlyFiles cannot be in contentFiles")

    regions_raw = root["regions"]
    if not isinstance(regions_raw, list) or not regions_raw:
        raise ProfileError("regions must be a non-empty array")
    regions: list[Region] = []
    for index, raw in enumerate(regions_raw):
        item = _object(
            raw,
            f"regions[{index}]",
            required={"id", "title", "kind", "status"},
        )
        kind = _text(item["kind"], f"regions[{index}].kind")
        status = _text(item["status"], f"regions[{index}].status")
        if kind not in {"exterior", "interior-inset"}:
            raise ProfileError("region kind must be exterior or interior-inset")
        if status not in {"available", "planned"}:
            raise ProfileError("region status must be available or planned")
        regions.append(
            Region(
                _slug(item["id"], f"regions[{index}].id"),
                _localized(item["title"], f"regions[{index}].title"),
                kind,
                status,
            )
        )
    _ensure_unique((item.id for item in regions), "regions ids")
    profile_locales = {item[0] for item in title}
    for region in regions:
        if {item[0] for item in region.title} != profile_locales:
            raise ProfileError(f"region {region.id!r} must define the profile locales")

    plugin_regions_raw = root["pluginRegions"]
    if not isinstance(plugin_regions_raw, dict):
        raise ProfileError("pluginRegions must be an object")
    _ensure_unique(plugin_regions_raw.keys(), "pluginRegions keys")
    if set(plugin_regions_raw) != set(content_order):
        raise ProfileError("pluginRegions must map every content file exactly once")
    region_ids = {item.id for item in regions}
    # Dependency regions are resolved during merge, but need not be published.
    if map_key in PROVINCE_RELEASES:
        region_ids |= {"vvardenfell", "solstheim"}
    plugin_regions: list[tuple[str, str]] = []
    for plugin in content_order:
        region_id = _slug(plugin_regions_raw[plugin], f"pluginRegions.{plugin}")
        if region_id not in region_ids:
            raise ProfileError(f"pluginRegions.{plugin} references unknown region {region_id!r}")
        plugin_regions.append((plugin, region_id))

    inputs_raw = root["requiredInputs"]
    if not isinstance(inputs_raw, list):
        raise ProfileError("requiredInputs must be an array")
    inputs: list[RequiredInput] = []
    for index, raw in enumerate(inputs_raw):
        item = _object(
            raw,
            f"requiredInputs[{index}]",
            required={"id", "directoryId", "filename"},
            optional={"sha256"},
        )
        digest = item.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
            raise ProfileError(f"requiredInputs[{index}].sha256 must be lowercase SHA-256")
        inputs.append(
            RequiredInput(
                _slug(item["id"], f"requiredInputs[{index}].id"),
                _slug(item["directoryId"], f"requiredInputs[{index}].directoryId"),
                _safe_relative_path(item["filename"], f"requiredInputs[{index}].filename"),
                digest,
            )
        )
    actual_layout = tuple((item.id, item.directory_id, item.filename) for item in inputs)
    if actual_layout != input_layout:
        raise ProfileError("requiredInputs must follow the exact canonical id/directory/file layout")
    full_input_paths = [
        str(PurePosixPath(directories[directory_ids.index(item.directory_id)].path) / item.filename)
        for item in inputs
    ]
    _ensure_unique((item.id for item in inputs), "requiredInputs ids")
    _ensure_unique(full_input_paths, "requiredInputs paths")
    for item in inputs:
        immutable_hash = BASE_INPUT_HASHES.get(item.id)
        if immutable_hash is not None and item.sha256 != immutable_hash:
            raise ProfileError(f"{item.id} must use its immutable base-game SHA-256")

    exceptions_raw = root["masterSizeExceptions"]
    if not isinstance(exceptions_raw, list):
        raise ProfileError("masterSizeExceptions must be an array")
    exceptions: list[MasterSizeException] = []
    input_by_id = {item.id: item for item in inputs}
    for index, raw in enumerate(exceptions_raw):
        item = _object(
            raw,
            f"masterSizeExceptions[{index}]",
            required={
                "dependentInputId",
                "masterInputId",
                "advertisedBytes",
                "actualBytes",
                "reason",
            },
        )
        dependent = _slug(
            item["dependentInputId"], f"masterSizeExceptions[{index}].dependentInputId"
        )
        master = _slug(item["masterInputId"], f"masterSizeExceptions[{index}].masterInputId")
        if dependent == master or dependent not in input_by_id or master not in input_by_id:
            raise ProfileError("masterSizeExceptions must reference two distinct required inputs")
        exceptions.append(
            MasterSizeException(
                dependent,
                master,
                _positive_int(
                    item["advertisedBytes"],
                    f"masterSizeExceptions[{index}].advertisedBytes",
                ),
                _positive_int(item["actualBytes"], f"masterSizeExceptions[{index}].actualBytes"),
                _slug(item["reason"], f"masterSizeExceptions[{index}].reason"),
            )
        )
    _ensure_unique(
        (f"{item.dependent_input_id}\0{item.master_input_id}" for item in exceptions),
        "masterSizeExceptions pairs",
    )

    smoke_raw = root["smokeCenters"]
    if not isinstance(smoke_raw, list) or len(smoke_raw) < 3:
        raise ProfileError("smokeCenters must contain at least three controls")
    smoke_centers: list[SmokeCenter] = []
    for index, raw in enumerate(smoke_raw):
        item = _object(raw, f"smokeCenters[{index}]", required={"id", "cell"})
        cell = item["cell"]
        if (
            not isinstance(cell, list)
            or len(cell) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in cell)
        ):
            raise ProfileError(f"smokeCenters[{index}].cell must be an [int, int] pair")
        coordinates = (cell[0], cell[1])
        if any(value % 3 for value in coordinates):
            raise ProfileError("smokeCenters coordinates must both be divisible by three")
        smoke_centers.append(
            SmokeCenter(_slug(item["id"], f"smokeCenters[{index}].id"), coordinates)
        )
    _ensure_unique((item.id for item in smoke_centers), "smokeCenters ids")
    if len({item.cell for item in smoke_centers}) != len(smoke_centers):
        raise ProfileError("smokeCenters cells must be unique")

    adopted = root.get("adoptedSnapshotId")
    if adopted is not None and (
        dataset_id != ADOPTED_SNAPSHOT_DATASET_ID or adopted != ADOPTED_SNAPSHOT_ID
    ):
        raise ProfileError(
            "adoptedSnapshotId is reserved for the exact already-published 26.08 seed"
        )

    return ReleaseProfile(
        SCHEMA_VERSION,
        dataset_id,
        map_key,
        title,
        summary,
        release,
        tuple(directories),
        fallback_archives,
        content_files,
        inventory_only,
        tuple(excluded),
        tuple(regions),
        tuple(plugin_regions),
        tuple(inputs),
        tuple(exceptions),
        tuple(smoke_centers),
        adopted,
    )


def _is_noise(relative: PurePosixPath) -> bool:
    parts = tuple(part.casefold() for part in relative.parts)
    return any(part in _NOISE_DIRECTORIES for part in parts) or (
        bool(parts) and parts[-1] in _NOISE_FILES
    )


def _fingerprint_data_tree(
    directory: DataDirectory,
    root: Path,
    controlled_inputs: frozenset[str],
) -> DataTreeFingerprint:
    if root.is_symlink():
        raise ValueError(f"Data directory cannot be a symlink: {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"Required data directory is missing: {root}")
    pending: list[tuple[PurePosixPath, Path]] = [(PurePosixPath(), root)]
    seen: dict[str, str] = {}
    files: list[dict[str, object]] = []
    while pending:
        relative_root, actual_root = pending.pop()
        with os.scandir(actual_root) as stream:
            entries = sorted(stream, key=lambda item: (_casefold_key(item.name), item.name))
        for entry in entries:
            relative = relative_root / entry.name
            actual = Path(entry.path)
            if entry.is_symlink():
                raise ValueError(f"Data trees cannot contain symlinks: {actual}")
            if _is_noise(relative):
                continue
            normalized = _casefold_key(relative.as_posix())
            previous = seen.get(normalized)
            if previous is not None:
                raise ValueError(
                    f"Case-insensitive data-tree collision in {directory.id}: "
                    f"{previous!r}, {relative.as_posix()!r}"
                )
            seen[normalized] = relative.as_posix()
            if entry.is_dir(follow_symlinks=False):
                pending.append((relative, actual))
            elif entry.is_file(follow_symlinks=False):
                if (
                    PurePosixPath(entry.name).suffix.casefold() in _CONTROLLED_INPUT_SUFFIXES
                    and normalized not in controlled_inputs
                ):
                    raise ValueError(
                        f"Unexpected mounted release input in {directory.id}: "
                        f"{relative.as_posix()}"
                    )
                stat = entry.stat(follow_symlinks=False)
                files.append(
                    {
                        "path": relative.as_posix(),
                        "bytes": stat.st_size,
                        "sha256": sha256_file(actual),
                    }
                )
            else:
                raise ValueError(f"Data trees can contain only regular files/directories: {actual}")
    files.sort(key=lambda item: (_casefold_key(str(item["path"])), str(item["path"])))
    return DataTreeFingerprint(
        directory.id,
        directory.path,
        len(files),
        sum(int(item["bytes"]) for item in files),
        canonical_json_sha256(files),
    )


def _reject_symlink_components(root: Path, relative: str) -> None:
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Source paths cannot contain symlink components: {current}")


def check_source(profile: ReleaseProfile, source_root: Path | str) -> SourceAudit:
    """Hash every required input and complete mounted data tree without following links."""

    root = Path(source_root)
    if root.is_symlink():
        raise ValueError(f"Source root cannot be a symlink: {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"Source root is missing: {root}")
    for directory in profile.data_directories:
        _reject_symlink_components(root, directory.path)
    controlled_by_directory = {
        directory.id: frozenset(
            _casefold_key(item.filename)
            for item in profile.required_inputs
            if item.directory_id == directory.id
        )
        for directory in profile.data_directories
    }
    trees = tuple(
        _fingerprint_data_tree(
            directory,
            root / directory.path,
            controlled_by_directory[directory.id],
        )
        for directory in profile.data_directories
    )
    inputs: list[InputLock] = []
    for item in profile.required_inputs:
        relative_path = profile.input_relative_path(item)
        path = root / relative_path
        if path.is_symlink():
            raise ValueError(f"Required input cannot be a symlink: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"Required input is missing: {path}")
        actual = sha256_file(path)
        if item.sha256 is not None and actual != item.sha256:
            raise ValueError(
                f"Input hash mismatch for {item.id}: expected {item.sha256}, got {actual}"
            )
        inputs.append(
            InputLock(
                item.id,
                item.directory_id,
                item.filename,
                relative_path,
                path.stat().st_size,
                actual,
            )
        )
    audit = SourceAudit(tuple(inputs), trees)
    audited_inputs = audit.input_by_id
    for exception in profile.master_size_exceptions:
        master = audited_inputs[exception.master_input_id]
        if master.bytes != exception.actual_bytes:
            raise ValueError(
                f"Master-size exception {exception.reason!r} is stale: "
                f"expected {exception.actual_bytes} bytes, got {master.bytes}"
            )
    return audit


def generate_release_lock(
    profile: ReleaseProfile, source_root: Path | str
) -> ReleaseLock:
    source_audit = check_source(profile, source_root)
    fingerprint_payload = {
        "schemaVersion": SCHEMA_VERSION,
        "profile": profile.to_dict(include_adopted_snapshot=False),
        "source": source_audit.to_dict(),
    }
    profile_fingerprint = canonical_json_sha256(fingerprint_payload)
    derived_snapshot_id = (
        f"{profile.snapshot_prefix}:{profile.dataset_id}:{profile_fingerprint[:SNAPSHOT_FINGERPRINT_LENGTH]}"
    )
    return ReleaseLock(
        profile,
        source_audit,
        profile_fingerprint,
        derived_snapshot_id,
        profile.adopted_snapshot_id or derived_snapshot_id,
    )


def _shard_center(cell: tuple[int, int]) -> tuple[int, int]:
    return 3 * ((cell[0] + 1) // 3), 3 * ((cell[1] + 1) // 3)


def _adjacencies(
    zoom: int, tiles: set[tuple[int, int]]
) -> tuple[tuple[int, int, str, int, int], ...]:
    result: list[tuple[int, int, str, int, int]] = []
    for x, y in sorted(tiles, key=lambda item: (item[1], item[0])):
        if (x + 1, y) in tiles:
            result.append((x, y, "east", x + 1, y))
        if (x, y - 1) in tiles:
            result.append((x, y, "north", x, y - 1))
    return tuple(result)


def _adjacency_id(zoom: int, item: tuple[int, int, str, int, int]) -> str:
    x, y, direction, other_x, other_y = item
    return f"{zoom}/{x}/{y}:{direction}:{zoom}/{other_x}/{other_y}"


def _select_probes(values: Sequence[str], count: int) -> tuple[str, ...]:
    if count <= 0 or not values:
        return ()
    if len(values) <= count:
        return tuple(values)
    indices = tuple((index * len(values)) // count for index in range(count))
    return tuple(values[index] for index in indices)


def derive_land_topology(
    effective_cells: Iterable[tuple[int, int]],
    *,
    native_zoom: int = NATIVE_ZOOM,
    cell_size: int = CELL_SIZE,
    probe_count: int = 16,
) -> LandTopology:
    """Derive sparse XYZ topology from effective exterior LAND cell coordinates."""

    if isinstance(native_zoom, bool) or not isinstance(native_zoom, int) or native_zoom < 0:
        raise ValueError("native_zoom must be a non-negative integer")
    if isinstance(cell_size, bool) or not isinstance(cell_size, int) or cell_size <= 0:
        raise ValueError("cell_size must be a positive integer")
    if isinstance(probe_count, bool) or not isinstance(probe_count, int) or probe_count < 0:
        raise ValueError("probe_count must be a non-negative integer")
    cells: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for raw in effective_cells:
        if (
            not isinstance(raw, tuple)
            or len(raw) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in raw)
        ):
            raise ValueError("effective LAND cells must be (int, int) tuples")
        if raw in seen:
            raise ValueError(f"Duplicate effective LAND cell: {raw}")
        seen.add(raw)
        cells.append(raw)
    if not cells:
        raise ValueError("At least one effective LAND cell is required")
    cells.sort(key=lambda item: (item[1], item[0]))
    min_x = min(item[0] for item in cells)
    max_x = max(item[0] for item in cells)
    min_y = min(item[1] for item in cells)
    max_y = max(item[1] for item in cells)
    extent = (min_x * cell_size, min_y * cell_size, (max_x + 1) * cell_size, (max_y + 1) * cell_size)
    origin = (extent[0], extent[3])
    native_by_cell = {
        cell: (cell[0] - min_x, max_y - cell[1])
        for cell in cells
    }
    tiles_by_zoom: dict[int, set[tuple[int, int]]] = {native_zoom: set(native_by_cell.values())}
    for zoom in range(native_zoom - 1, -1, -1):
        divisor = 1 << (native_zoom - zoom)
        tiles_by_zoom[zoom] = {
            (tile[0] // divisor, tile[1] // divisor)
            for tile in tiles_by_zoom[native_zoom]
        }
    zooms: list[ZoomTopology] = []
    native_adjacencies: tuple[tuple[int, int, str, int, int], ...] = ()
    for zoom in range(native_zoom + 1):
        adjacency_records = _adjacencies(zoom, tiles_by_zoom[zoom])
        east = sum(item[2] == "east" for item in adjacency_records)
        north = len(adjacency_records) - east
        zooms.append(ZoomTopology(zoom, len(tiles_by_zoom[zoom]), east, north))
        if zoom == native_zoom:
            native_adjacencies = adjacency_records
    cell_by_native = {tile: cell for cell, tile in native_by_cell.items()}
    cross_shard = tuple(
        item
        for item in native_adjacencies
        if _shard_center(cell_by_native[(item[0], item[1])])
        != _shard_center(cell_by_native[(item[3], item[4])])
    )
    probe_ids = tuple(_adjacency_id(native_zoom, item) for item in cross_shard)
    shard_centers = tuple(sorted({_shard_center(cell) for cell in cells}, key=lambda item: (item[1], item[0])))
    return LandTopology(
        len(cells),
        extent,
        origin,
        0,
        native_zoom,
        tuple(zooms),
        shard_centers,
        len(cross_shard),
        _select_probes(probe_ids, probe_count),
    )
