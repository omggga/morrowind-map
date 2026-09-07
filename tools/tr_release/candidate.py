"""Fail-closed Tamriel Rebuilt candidate assembly and activation.

The functions in this module deliberately accept plain mappings.  Release-profile
and lock-file model classes may evolve without making activation depend on their
implementation APIs.  Candidate assembly is inactive; only ``activate_candidate``
touches the active dataset tree, and the index replacement is its final write.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any


_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_PUBLIC_PREFIXES = {
    "generated": "/datasets/generated/",
    "metadata": "/datasets/metadata/",
    "manifests": "/datasets/manifests/",
}


@dataclass(frozen=True)
class CandidateBundle:
    dataset_id: str
    snapshot_id: str
    manifest_path: Path
    index_path: Path
    _verified_manifest_bytes: bytes = field(default=b"", repr=False, compare=False)
    _verified_index_bytes: bytes = field(default=b"", repr=False, compare=False)

    def to_dict(self) -> dict[str, str]:
        return {
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "manifest": str(self.manifest_path),
            "index": str(self.index_path),
        }


@dataclass(frozen=True)
class _ActiveState:
    original_id: str
    current_tr_id: str
    original_entry: dict[str, Any]
    entries_by_map: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _BasemapEvidence:
    path: Path
    sha256: str
    value: dict[str, Any]


@dataclass(frozen=True)
class _CatalogEvidence:
    audit_path: Path
    audit_sha256: str
    audit_bytes: int
    locations_path: Path
    locations_sha256: str
    locations_bytes: int
    english_path: Path
    english_sha256: str
    english_bytes: int


def canonical_json_bytes(value: object) -> bytes:
    """Return the repository's canonical JSON representation with one trailing LF."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _logical_sha256(value: Mapping[str, Any], *, omit: str) -> str:
    core = {key: item for key, item in value.items() if key != omit}
    return _sha256_bytes(canonical_json_bytes(core)[:-1])


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _require_root(path: Path, label: str, *, create: bool = False) -> Path:
    root = _absolute(path)
    if root.is_symlink():
        raise ValueError(f"{label} cannot be a symlink: {root}")
    if create:
        parent = root.parent
        if parent.is_symlink():
            raise ValueError(f"{label} parent cannot be a symlink: {parent}")
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError(f"{label} is not a directory: {root}")
    return root


def _safe_relative(value: str, label: str) -> Path:
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or any(character in value for character in "%?#")
    ):
        raise ValueError(f"{label} is unsafe: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{label} is unsafe: {value!r}")
    if pure.as_posix() != value:
        raise ValueError(f"{label} is not canonical: {value!r}")
    return Path(*pure.parts)


def _ensure_no_symlink(path: Path, boundary: Path, label: str) -> None:
    path = _absolute(path)
    boundary = _absolute(boundary)
    try:
        relative = path.relative_to(boundary)
    except ValueError as error:
        raise ValueError(f"{label} escapes its root: {path}") from error
    current = boundary
    if current.is_symlink():
        raise ValueError(f"{label} root cannot be a symlink: {current}")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink: {current}")


def _safe_child(root: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"{label} path is unsafe: {relative}")
    path = root / relative
    _ensure_no_symlink(path, root, label)
    return path


def _path_from_url(url: object, *, kind: str, root: Path, label: str) -> Path:
    if not isinstance(url, str):
        raise ValueError(f"{label} URL must be a string")
    prefix = _PUBLIC_PREFIXES[kind]
    if not url.startswith(prefix) or any(character.isspace() for character in url):
        raise ValueError(f"{label} URL is outside {prefix}: {url!r}")
    relative = _safe_relative(url[len(prefix) :], f"{label} URL")
    return _safe_child(root, relative, label)


def _url_for(path: Path, *, kind: str, root: Path) -> str:
    relative = _absolute(path).relative_to(root)
    return _PUBLIC_PREFIXES[kind] + PurePosixPath(*relative.parts).as_posix()


def _read_object(
    path: Path,
    label: str,
    *,
    boundary: Path,
    canonical: bool,
) -> tuple[dict[str, Any], bytes]:
    _ensure_no_symlink(path, boundary, label)
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    payload = path.read_bytes()
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{label} is not strict UTF-8 JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    if canonical and payload != canonical_json_bytes(value):
        raise ValueError(f"{label} is not canonical UTF-8 JSON with one trailing LF: {path}")
    return value, payload


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be an array")
    return value


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _identifier(value: object, label: str) -> str:
    result = _required_string(value, label)
    if _IDENTIFIER.fullmatch(result) is None:
        raise ValueError(f"{label} is not a safe dataset identifier: {result!r}")
    return result


def _sha256(value: object, label: str) -> str:
    result = _required_string(value, label)
    if _SHA256.fullmatch(result) is None:
        raise ValueError(f"{label} is not a lowercase SHA-256")
    return result


def _byte_count(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _number_list(value: object, length: int | None, label: str) -> list[int | float]:
    values = _sequence(value, label)
    if length is not None and len(values) != length:
        raise ValueError(f"{label} must have exactly {length} values")
    result: list[int | float] = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{label} contains a non-number")
        if not math.isfinite(item):
            raise ValueError(f"{label} contains a non-finite number")
        result.append(item)
    return result


def _identity(profile: Mapping[str, object], lock: Mapping[str, object]) -> tuple[str, str]:
    dataset_id = _identifier(lock.get("datasetId"), "Release lock datasetId")
    profile_id = _identifier(profile.get("datasetId"), "Release profile datasetId")
    if profile_id != dataset_id:
        raise ValueError("Release profile and lock datasetId differ")
    if profile.get("mapKey") not in ("tamriel-rebuilt", "project-cyrodiil", "home-of-nords", "azurian-isles"):
        raise ValueError("Unsupported release mapKey")
    snapshot_id = _required_string(lock.get("snapshotId"), "Release lock snapshotId")
    profile_snapshot = profile.get("snapshotId")
    if profile_snapshot is not None and profile_snapshot != snapshot_id:
        raise ValueError("Release profile and lock snapshotId differ")
    return dataset_id, snapshot_id


def _lock_map(lock: Mapping[str, object]) -> dict[str, list[int | float]]:
    raw_value = lock.get("map")
    if raw_value is None:
        raw_value = lock.get("topology")
    if raw_value is None:
        raw_value = lock.get("renderer")
    raw = _mapping(raw_value, "Release lock map")
    if "projection" in raw or "tileGrid" in raw:
        projection = _mapping(raw.get("projection"), "Release lock map projection")
        tile_grid = _mapping(raw.get("tileGrid"), "Release lock map tileGrid")
        extent_value = projection.get("extent")
        center_value = projection.get("center")
        origin_value = tile_grid.get("origin")
        resolutions_value = tile_grid.get("resolutions")
        tile_size = tile_grid.get("tileSize", 512)
    else:
        extent_value = raw.get("extent")
        center_value = raw.get("center")
        origin_value = raw.get("origin")
        resolutions_value = raw.get("resolutions")
        tile_size = raw.get("tileSize", 512)
    extent = _number_list(extent_value, 4, "Release lock extent")
    origin = _number_list(origin_value, 2, "Release lock origin")
    resolutions = _number_list(resolutions_value, None, "Release lock resolutions")
    if not resolutions or any(value <= 0 for value in resolutions):
        raise ValueError("Release lock resolutions must be positive and non-empty")
    if tile_size != 512:
        raise ValueError("Release lock tileSize must be 512")
    if center_value is None:
        center = [(extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2]
        center = [int(value) if value.is_integer() else value for value in center]
    else:
        center = _number_list(center_value, 2, "Release lock center")
    return {
        "extent": extent,
        "center": center,
        "origin": origin,
        "resolutions": resolutions,
    }


def _descriptor_list(
    value: object,
    fields: tuple[str, ...],
    label: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_sequence(value, label)):
        item = _mapping(raw, f"{label}[{index}]")
        missing = [field for field in fields if field not in item]
        if missing:
            raise ValueError(f"{label}[{index}] misses fields: {', '.join(missing)}")
        result.append({field: copy.deepcopy(item[field]) for field in fields})
    return result


def _input_name(item: Mapping[str, Any], label: str) -> str:
    name = item.get("name", item.get("filename"))
    if isinstance(name, str) and name:
        return name
    path = item.get("relativePath", item.get("path"))
    relative = _safe_relative(_required_string(path, f"{label} path"), f"{label} path")
    return relative.name


def _lock_inputs(lock: Mapping[str, object]) -> list[Mapping[str, Any]]:
    raw: object = lock.get("inputs")
    if raw is None:
        raw = lock.get("sourceInputs")
    if raw is None and isinstance(lock.get("inputAudit"), Mapping):
        raw = lock["inputAudit"].get("inputs")  # type: ignore[index]
    if raw is None and isinstance(lock.get("source"), Mapping):
        raw = lock["source"].get("inputs")  # type: ignore[index]
    if raw is None:
        return []
    return [
        _mapping(item, f"Release lock inputs[{index}]")
        for index, item in enumerate(_sequence(raw, "Release lock inputs"))
    ]


def _profile_required_inputs(profile: Mapping[str, object]) -> list[Mapping[str, Any]]:
    raw = profile.get("requiredInputs")
    if raw is None:
        return []
    return [
        _mapping(item, f"Release profile requiredInputs[{index}]")
        for index, item in enumerate(_sequence(raw, "Release profile requiredInputs"))
    ]


def _matching_input(
    name: str,
    *,
    required_inputs: Sequence[Mapping[str, Any]],
    lock_inputs: Sequence[Mapping[str, Any]],
    label: str,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any]]:
    required_matches = [
        item
        for item in required_inputs
        if _input_name(item, label).casefold() == name.casefold()
    ]
    if len(required_matches) > 1:
        raise ValueError(f"{label} matches more than one required input: {name}")
    required = required_matches[0] if required_matches else None
    required_id = required.get("id") if required is not None else None
    audit_matches = [
        item
        for item in lock_inputs
        if (required_id is not None and item.get("id") == required_id)
        or (
            isinstance(item.get("relativePath"), str)
            and Path(str(item["relativePath"])).name.casefold() == name.casefold()
        )
        or (
            isinstance(item.get("path"), str)
            and Path(str(item["path"])).name.casefold() == name.casefold()
        )
        or (isinstance(item.get("name"), str) and str(item["name"]).casefold() == name.casefold())
    ]
    unique_matches = list({id(item): item for item in audit_matches}.values())
    if len(unique_matches) != 1:
        raise ValueError(
            f"{label} must match exactly one release-lock input by id or basename: {name}"
        )
    return required, unique_matches[0]


def _module_id(value: str) -> str:
    stem = Path(value).stem.casefold()
    result = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return _identifier(result, "Excluded module id")


def _profile_descriptors(
    profile: Mapping[str, object], lock: Mapping[str, object]
) -> dict[str, Any]:
    required_inputs = profile.get("requiredInputs")
    raw_content = profile.get("contentFiles")
    required_input_items = _profile_required_inputs(profile)
    lock_input_items = _lock_inputs(lock)
    release = _mapping(profile.get("release"), "Release profile release")
    release_version = _required_string(release.get("version"), "Release version")
    if raw_content is not None and all(
        isinstance(item, Mapping)
        for item in _sequence(raw_content, "Release profile contentFiles")
    ):
        content_files = _descriptor_list(
            raw_content,
            ("name", "kind", "version", "sha256", "loadOrder", "inclusion", "enabled"),
            "Release profile contentFiles",
        )
    elif raw_content is not None:
        content_files = []
        for load_order, raw_name in enumerate(
            _sequence(raw_content, "Release profile contentFiles")
        ):
            name = _required_string(raw_name, f"Release profile contentFiles[{load_order}]")
            suffix = Path(name).suffix.lower()
            if suffix not in {".esm", ".esp"}:
                raise ValueError(f"Content file is not ESM/ESP: {name}")
            required, audited = _matching_input(
                name,
                required_inputs=required_input_items,
                lock_inputs=lock_input_items,
                label="Release profile content file",
            )
            directory_id = None
            if required is not None:
                directory_id = required.get("dataDirectoryId", required.get("directoryId"))
            content_files.append(
                {
                    "name": name,
                    "kind": suffix[1:],
                    "version": (
                        release_version
                        if directory_id not in {None, "base-game"}
                        else None
                    ),
                    "sha256": _sha256(
                        audited.get("sha256"), f"Release lock input {name} SHA-256"
                    ),
                    "loadOrder": load_order,
                    "inclusion": "required",
                    "enabled": True,
                }
            )
    elif required_inputs is not None:
        content_files = []
        for index, raw in enumerate(_sequence(required_inputs, "Release profile requiredInputs")):
            item = _mapping(raw, f"Release profile requiredInputs[{index}]")
            name = _input_name(item, f"Release profile requiredInputs[{index}]")
            suffix = Path(name).suffix.lower()
            if suffix not in {".esm", ".esp"}:
                continue
            load_order = item.get("loadOrder")
            content_files.append(
                {
                    "name": name,
                    "kind": suffix[1:],
                    "version": copy.deepcopy(item.get("version")),
                    "sha256": copy.deepcopy(item.get("sha256")),
                    "loadOrder": copy.deepcopy(load_order),
                    "inclusion": copy.deepcopy(item.get("inclusion", "required")),
                    "enabled": copy.deepcopy(item.get("enabled", True)),
                }
            )
    else:
        raise ValueError("Release profile must define contentFiles or requiredInputs")

    raw_archives = profile.get("fallbackArchives")
    if raw_archives is not None and all(
        isinstance(item, Mapping)
        for item in _sequence(raw_archives, "Release profile fallbackArchives")
    ):
        archives = _descriptor_list(
            raw_archives,
            ("name", "sha256", "order", "required", "registered"),
            "Release profile fallbackArchives",
        )
    elif raw_archives is not None:
        archives = []
        for order, raw_name in enumerate(
            _sequence(raw_archives, "Release profile fallbackArchives")
        ):
            name = _required_string(raw_name, f"Release profile fallbackArchives[{order}]")
            if Path(name).suffix.lower() != ".bsa":
                raise ValueError(f"Fallback archive is not BSA: {name}")
            _, audited = _matching_input(
                name,
                required_inputs=required_input_items,
                lock_inputs=lock_input_items,
                label="Release profile fallback archive",
            )
            archives.append(
                {
                    "name": name,
                    "sha256": _sha256(
                        audited.get("sha256"), f"Release lock input {name} SHA-256"
                    ),
                    "order": order,
                    "required": True,
                    "registered": True,
                }
            )
    elif required_inputs is not None:
        archives = []
        archive_order = 0
        for index, raw in enumerate(_sequence(required_inputs, "Release profile requiredInputs")):
            item = _mapping(raw, f"Release profile requiredInputs[{index}]")
            name = _input_name(item, f"Release profile requiredInputs[{index}]")
            if Path(name).suffix.lower() != ".bsa":
                continue
            archives.append(
                {
                    "name": name,
                    "sha256": copy.deepcopy(item.get("sha256")),
                    "order": copy.deepcopy(item.get("archiveOrder", archive_order)),
                    "required": True,
                    "registered": True,
                }
            )
            archive_order += 1
    else:
        archives = []

    directories_value = profile.get("dataDirectories", profile.get("directories"))
    raw_directories = _sequence(directories_value, "Release profile dataDirectories")
    if all(
        isinstance(item, Mapping) and {"id", "order", "status"}.issubset(item)
        for item in raw_directories
    ):
        directories = _descriptor_list(
            raw_directories,
            ("id", "order", "status"),
            "Release profile dataDirectories",
        )
    else:
        directories = []
        for order, raw in enumerate(raw_directories):
            item = _mapping(raw, f"Release profile dataDirectories[{order}]")
            directories.append(
                {
                    "id": _identifier(
                        item.get("id"), f"Release profile dataDirectories[{order}] id"
                    ),
                    "order": order,
                    "status": "confirmed",
                }
            )
    excluded_value = profile.get(
        "excludedOptionalModules", profile.get("excludedModules", [])
    )
    modules: list[dict[str, Any]] = []
    for index, raw in enumerate(_sequence(excluded_value, "Release profile excludedModules")):
        if isinstance(raw, str):
            modules.append(
                {
                    "id": _module_id(raw),
                    "status": "disabled",
                    "notes": ["Excluded from the canonical Tamriel Rebuilt profile."],
                }
            )
            continue
        item = _mapping(raw, f"Release profile excludedModules[{index}]")
        source_id = item.get("id", item.get("name", item.get("relativePath")))
        module_id = _module_id(_required_string(source_id, "Excluded module id"))
        modules.append(
            {
                "id": module_id,
                "status": copy.deepcopy(item.get("status", "disabled")),
                "notes": copy.deepcopy(
                    item.get(
                        "notes",
                        ["Excluded from the canonical Tamriel Rebuilt profile."],
                    )
                ),
            }
        )
        module_name = item.get("name")
        if module_name is None and isinstance(item.get("relativePath"), str):
            module_name = PurePosixPath(str(item["relativePath"])).name
        if isinstance(module_name, str) and Path(module_name).suffix.lower() in {".esm", ".esp"}:
            suffix = Path(module_name).suffix.lower()
            if not any(
                entry["name"].casefold() == module_name.casefold()
                for entry in content_files
            ):
                audited_matches = [
                    audit
                    for audit in lock_input_items
                    if (
                        isinstance(audit.get("relativePath"), str)
                        and Path(str(audit["relativePath"])).name.casefold()
                        == module_name.casefold()
                    )
                    or (
                        isinstance(audit.get("name"), str)
                        and str(audit["name"]).casefold() == module_name.casefold()
                    )
                ]
                content_files.append(
                    {
                        "name": module_name,
                        "kind": suffix[1:],
                        "version": release_version,
                        "sha256": (
                            copy.deepcopy(audited_matches[0].get("sha256"))
                            if len(audited_matches) == 1
                            else None
                        ),
                        "loadOrder": None,
                        "inclusion": "excluded",
                        "enabled": False,
                    }
                )
    if not content_files:
        raise ValueError("Release profile has no ESM/ESP content descriptors")
    return {
        "status": "confirmed",
        "contentFiles": content_files,
        "registeredArchives": archives,
        "dataDirectories": directories,
        "modules": modules,
    }


def _active_state(active_root: Path) -> _ActiveState:
    index, _ = _read_object(
        active_root / "index.json",
        "Active dataset index",
        boundary=active_root,
        canonical=False,
    )
    entries = _sequence(index.get("datasets"), "Active dataset index entries")
    if len(entries) not in (2, 3, 4, 5):
        raise ValueError("Active dataset index must contain Original, TR and optional province maps")
    originals: list[tuple[str, dict[str, Any]]] = []
    rebuilt: list[str] = []
    entries_by_map: dict[str, dict[str, Any]] = {}
    for position, raw_entry in enumerate(entries):
        entry = dict(_mapping(raw_entry, f"Active dataset index entry {position}"))
        dataset_id = _identifier(entry.get("datasetId"), "Active dataset entry datasetId")
        manifest_path = _path_from_url(
            entry.get("manifestUrl"),
            kind="manifests",
            root=active_root / "manifests",
            label=f"Active {dataset_id} manifest",
        )
        expected_path = active_root / "manifests" / f"{dataset_id}.json"
        if manifest_path != expected_path:
            raise ValueError(f"Active manifest URL is not canonical for {dataset_id}")
        manifest, _ = _read_object(
            manifest_path,
            f"Active {dataset_id} manifest",
            boundary=active_root,
            canonical=False,
        )
        if manifest.get("datasetId") != dataset_id:
            raise ValueError(f"Active manifest identity differs for {dataset_id}")
        map_key = manifest.get("mapKey")
        if map_key not in {"original", "tamriel-rebuilt", "project-cyrodiil", "home-of-nords", "azurian-isles"} or map_key in entries_by_map:
            raise ValueError("Active map keys must be supported and unique")
        entries_by_map[map_key] = copy.deepcopy(entry)
        if map_key == "original":
            originals.append((dataset_id, copy.deepcopy(entry)))
        elif map_key == "tamriel-rebuilt":
            rebuilt.append(dataset_id)
        elif map_key not in {"project-cyrodiil", "home-of-nords", "azurian-isles"}:
            raise ValueError(f"Active manifest has unsupported mapKey: {dataset_id}")
    if len(originals) != 1 or len(rebuilt) != 1:
        raise ValueError("Active index must contain exactly one Original and one TR manifest")
    original_id, original_entry = originals[0]
    if index.get("defaultDatasetId") != original_id:
        raise ValueError("Original must remain the default active dataset")
    if original_entry.get("order") != 0:
        raise ValueError("Original dataset entry must remain first with order 0")
    tr_entry = next(
        dict(_mapping(item, "Active TR entry"))
        for item in entries
        if isinstance(item, Mapping) and item.get("datasetId") == rebuilt[0]
    )
    if tr_entry.get("order") != 1:
        raise ValueError("Active TR dataset entry must have order 1")
    if "project-cyrodiil" in entries_by_map and entries_by_map["project-cyrodiil"].get("order") != 2:
        raise ValueError("Project Cyrodiil dataset entry must have order 2")
    if "home-of-nords" in entries_by_map and entries_by_map["home-of-nords"].get("order") != 3:
        raise ValueError("Home of the Nords dataset entry must have order 3")
    if "azurian-isles" in entries_by_map and entries_by_map["azurian-isles"].get("order") != 4:
        raise ValueError("Azurian Isles dataset entry must have order 4")
    return _ActiveState(original_id, rebuilt[0], original_entry, entries_by_map)


def _assert_future_identity(dataset_id: str, state: _ActiveState) -> None:
    if dataset_id in {entry["datasetId"] for entry in state.entries_by_map.values()}:
        raise ValueError(
            "A future map release requires a new datasetId; "
            "it cannot reuse an active datasetId"
        )


def _verify_artifact_record(
    record_value: object,
    *,
    root: Path,
    kind: str,
    label: str,
    canonical_json: bool,
) -> tuple[Path, bytes, dict[str, Any] | None]:
    record = _mapping(record_value, f"{label} binding")
    expected_sha = _sha256(record.get("sha256"), f"{label} SHA-256")
    expected_bytes = _byte_count(record.get("bytes"), f"{label} byte count")
    if record.get("mediaType") != "application/json":
        raise ValueError(f"{label} mediaType must be application/json")
    path = _path_from_url(record.get("url"), kind=kind, root=root, label=label)
    _ensure_no_symlink(path, root, label)
    if not path.is_file():
        raise ValueError(f"{label} file is missing: {path}")
    payload = path.read_bytes()
    if len(payload) != expected_bytes or _sha256_bytes(payload) != expected_sha:
        raise ValueError(f"{label} file changed after evidence was produced: {path}")
    value: dict[str, Any] | None = None
    if canonical_json:
        value, parsed_payload = _read_object(
            path,
            label,
            boundary=root,
            canonical=True,
        )
        if parsed_payload != payload:
            raise AssertionError("Artifact changed during a single verification read")
    return path, payload, value


def _verify_relative_artifact(
    record_value: object,
    *,
    base: Path,
    boundary: Path,
    label: str,
    canonical_json: bool,
) -> tuple[Path, bytes, dict[str, Any] | None]:
    record = _mapping(record_value, f"{label} binding")
    relative = _safe_relative(
        _required_string(record.get("path"), f"{label} path"),
        f"{label} path",
    )
    path = _safe_child(base, relative, label)
    expected_sha = _sha256(record.get("sha256"), f"{label} SHA-256")
    expected_bytes = _byte_count(record.get("bytes"), f"{label} byte count")
    if not path.is_file():
        raise ValueError(f"{label} file is missing: {path}")
    payload = path.read_bytes()
    if len(payload) != expected_bytes or _sha256_bytes(payload) != expected_sha:
        raise ValueError(f"{label} file changed after evidence was produced: {path}")
    value: dict[str, Any] | None = None
    if canonical_json:
        value, parsed_payload = _read_object(
            path,
            label,
            boundary=boundary,
            canonical=True,
        )
        if parsed_payload != payload:
            raise AssertionError("Artifact changed during a single verification read")
    return path, payload, value


def _require_artifact_identity(
    value: Mapping[str, Any], dataset_id: str, snapshot_id: str, label: str
) -> None:
    if value.get("datasetId") != dataset_id or value.get("snapshotId") != snapshot_id:
        raise ValueError(f"{label} identity does not match the release lock")


def _verify_audit_hash(value: Mapping[str, Any], label: str) -> None:
    audit_sha = _sha256(value.get("auditSha256"), f"{label} logical SHA-256")
    if audit_sha != _logical_sha256(value, omit="auditSha256"):
        raise ValueError(f"{label} logical SHA-256 does not match its payload")


def _tiles_ndjson(payload: bytes) -> list[Mapping[str, Any]]:
    if not payload or not payload.endswith(b"\n"):
        raise ValueError("Basemap tiles.ndjson must be non-empty and end with one LF")
    records: list[Mapping[str, Any]] = []
    for index, line in enumerate(payload[:-1].split(b"\n")):
        if not line:
            raise ValueError(f"Basemap tiles.ndjson line {index + 1} is empty")
        try:
            value = json.loads(
                line,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(
                f"Basemap tiles.ndjson line {index + 1} is not strict UTF-8 JSON"
            ) from error
        if not isinstance(value, dict):
            raise ValueError(f"Basemap tiles.ndjson line {index + 1} must be an object")
        if line != canonical_json_bytes(value)[:-1]:
            raise ValueError(f"Basemap tiles.ndjson line {index + 1} is not canonical JSON")
        records.append(value)
    return records


def _verify_published_tiles(
    inventory_payload: bytes,
    *,
    version_path: Path,
    tile_root: Path,
    expected_count: int,
    expected_total_bytes: int,
) -> None:
    expected: dict[str, tuple[int, str]] = {}
    folded_paths: dict[str, str] = {}
    inventory_total = 0
    for index, record in enumerate(_tiles_ndjson(inventory_payload)):
        label = f"Basemap tiles.ndjson record {index + 1}"
        relative = _safe_relative(
            _required_string(record.get("path"), f"{label} path"),
            f"{label} path",
        )
        z = _byte_count(record.get("z"), f"{label} z")
        x = _byte_count(record.get("x"), f"{label} x")
        y = _byte_count(record.get("y"), f"{label} y")
        canonical_path = Path("tiles", str(z), str(x), f"{y}.webp")
        if relative != canonical_path:
            raise ValueError(f"{label} path does not match its XYZ coordinates")
        relative_text = PurePosixPath(*relative.parts).as_posix()
        folded = relative_text.casefold()
        if relative_text in expected or folded in folded_paths:
            raise ValueError(f"Basemap tiles.ndjson has a duplicate tile path: {relative_text}")
        byte_count = _byte_count(record.get("bytes"), f"{label} byte count")
        digest = _sha256(record.get("sha256"), f"{label} SHA-256")
        expected[relative_text] = (byte_count, digest)
        folded_paths[folded] = relative_text
        inventory_total += byte_count

    if len(expected) != expected_count:
        raise ValueError(
            "Basemap tiles.ndjson count differs from prepared tile integrity: "
            f"expected {expected_count}, got {len(expected)}"
        )
    if inventory_total != expected_total_bytes:
        raise ValueError(
            "Basemap tiles.ndjson total bytes differ from prepared tile integrity: "
            f"expected {expected_total_bytes}, got {inventory_total}"
        )

    seen: set[str] = set()
    actual_total = 0
    pending = [tile_root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as stream:
            entries = sorted(stream, key=lambda item: item.name)
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                raise ValueError(f"Published tile tree contains a symlink: {path}")
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ValueError(f"Published tile tree contains a non-regular file: {path}")
            relative_text = path.relative_to(version_path).as_posix()
            binding = expected.get(relative_text)
            if binding is None:
                raise ValueError(f"Found unexpected published tile: {relative_text}")
            payload = path.read_bytes()
            byte_count, digest = binding
            if len(payload) != byte_count or _sha256_bytes(payload) != digest:
                raise ValueError(
                    f"Published tile {relative_text} changed after tiles.ndjson was produced"
                )
            seen.add(relative_text)
            actual_total += len(payload)

    missing = sorted(set(expected) - seen)
    if missing:
        raise ValueError("Found missing published tiles: " + ", ".join(missing[:10]))
    if len(seen) != expected_count or actual_total != expected_total_bytes:
        raise ValueError(
            "Published tile tree count/total differs from tiles.ndjson: "
            f"count={len(seen)}, bytes={actual_total}"
        )


def _validate_basemap(
    path: Path,
    *,
    dataset_id: str,
    snapshot_id: str,
    lock_map: Mapping[str, list[int | float]],
    renderer_contract: Mapping[str, Any],
    profile_fingerprint: object,
    generated_root: Path,
    metadata_root: Path,
) -> _BasemapEvidence:
    map_assets, map_bytes = _read_object(
        path, "Prepared map-assets", boundary=metadata_root, canonical=True
    )
    _require_artifact_identity(map_assets, dataset_id, snapshot_id, "Prepared map-assets")
    relative = path.relative_to(metadata_root)
    if len(relative.parts) != 3 or relative.parts[0] != dataset_id:
        raise ValueError("Prepared map-assets path must be <datasetId>/<inventory>/map-assets.json")
    inventory_id = _sha256(relative.parts[1], "Prepared basemap inventory directory")
    if relative.parts[2] != "map-assets.json" or map_assets.get("projection") != "TES3:WORLD":
        raise ValueError("Prepared map-assets path or projection is invalid")
    pyramids = _sequence(map_assets.get("tilePyramids"), "Prepared tile pyramids")
    if len(pyramids) != 1:
        raise ValueError("Prepared map-assets must contain exactly one tile pyramid")
    pyramid = _mapping(pyramids[0], "Prepared tile pyramid")
    if (
        pyramid.get("extent") != lock_map["extent"]
        or pyramid.get("origin") != lock_map["origin"]
        or pyramid.get("resolutions") != lock_map["resolutions"]
        or pyramid.get("tileSize") != 512
    ):
        raise ValueError("Prepared tile pyramid does not match the release lock map")
    integrity = _mapping(pyramid.get("integrity"), "Prepared tile pyramid integrity")
    if integrity.get("inventorySha256") != inventory_id:
        raise ValueError("Prepared tile pyramid inventory does not match its immutable path")
    integrity_tile_count = _byte_count(
        integrity.get("tileCount"), "Prepared tile pyramid tile count"
    )
    integrity_total_bytes = _byte_count(
        integrity.get("totalBytes"), "Prepared tile pyramid total bytes"
    )
    expected_plan = renderer_contract.get("planFingerprint")
    if expected_plan is not None and integrity.get("planFingerprint") != expected_plan:
        raise ValueError("Prepared tile pyramid plan fingerprint differs from the release lock")
    if profile_fingerprint is not None and integrity.get("profileFingerprint") != profile_fingerprint:
        raise ValueError("Prepared tile pyramid profile fingerprint differs from the release lock")
    producer_value = renderer_contract.get("producer")
    if producer_value is not None:
        producer = _mapping(producer_value, "Release lock renderer producer")
        for key, label in (
            ("rendererFingerprint", "Renderer fingerprint"),
            ("productionSourceFingerprint", "Production source fingerprint"),
        ):
            expected_fingerprint = _sha256(
                producer.get(key), f"Release lock {label}"
            )
            if integrity.get(key) != expected_fingerprint:
                raise ValueError(f"{label} differs from the release lock")
    scope_value = renderer_contract.get("scope")
    renderer_scope = (
        _mapping(scope_value, "Release lock renderer scope")
        if scope_value is not None
        else None
    )
    if renderer_scope is not None and integrity_tile_count != renderer_scope.get("tiles"):
        raise ValueError("Prepared tile count differs from the release lock renderer scope")
    tile_counts_value = renderer_contract.get("tileCounts")
    if tile_counts_value is not None:
        tile_counts = _mapping(tile_counts_value, "Release lock renderer tile counts")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in tile_counts.values()
        ):
            raise ValueError("Release lock renderer tile counts are malformed")
        if sum(tile_counts.values()) != integrity_tile_count:
            raise ValueError("Prepared tile count differs from release lock zoom counts")

    template = _required_string(pyramid.get("urlTemplate"), "Prepared tile URL template")
    suffix = "/tiles/{z}/{x}/{y}.webp"
    if not template.endswith(suffix):
        raise ValueError("Prepared tile URL template is not an XYZ WebP template")
    version_path = _path_from_url(
        template[: -len(suffix)],
        kind="generated",
        root=generated_root,
        label="Prepared basemap version",
    )
    expected_version = generated_root / dataset_id / inventory_id
    if version_path != expected_version:
        raise ValueError("Prepared tile URL does not match dataset and inventory identity")
    tile_root = version_path / "tiles"
    _ensure_no_symlink(tile_root, generated_root, "Prepared tile tree")
    if not tile_root.is_dir():
        raise ValueError("Prepared tile tree is missing")

    _, _, coverage = _verify_artifact_record(
        pyramid.get("coverage"),
        root=metadata_root,
        kind="metadata",
        label="Basemap coverage",
        canonical_json=True,
    )
    assert coverage is not None
    _require_artifact_identity(coverage, dataset_id, snapshot_id, "Basemap coverage")
    _, _, quality = _verify_artifact_record(
        pyramid.get("qualityReport"),
        root=metadata_root,
        kind="metadata",
        label="Basemap quality audit",
        canonical_json=True,
    )
    assert quality is not None
    _require_artifact_identity(quality, dataset_id, snapshot_id, "Basemap quality audit")
    if quality.get("passes") is not True:
        raise ValueError("Basemap quality audit did not pass")
    _verify_audit_hash(quality, "Basemap quality audit")
    if renderer_scope is not None and quality.get("scope") != dict(renderer_scope):
        raise ValueError("Basemap quality scope differs from the release lock")
    supporting = _mapping(quality.get("artifacts"), "Basemap quality audit artifacts")
    quality_path = _path_from_url(
        _mapping(pyramid.get("qualityReport"), "Basemap quality binding").get("url"),
        kind="metadata",
        root=metadata_root,
        label="Basemap quality audit",
    )
    tiles_inventory_payload: bytes | None = None
    for name, record in supporting.items():
        artifact_path, artifact_payload, _ = _verify_relative_artifact(
            record,
            base=quality_path.parent,
            boundary=metadata_root,
            label=f"Basemap quality artifact {name}",
            canonical_json=False,
        )
        if name == "tiles":
            if artifact_path != quality_path.parent / "tiles.ndjson":
                raise ValueError("Basemap tiles artifact must use the canonical tiles.ndjson path")
            tiles_inventory_payload = artifact_payload
    if tiles_inventory_payload is None:
        raise ValueError("Basemap quality audit must bind tiles.ndjson")
    gates = _mapping(quality.get("gates"), "Basemap quality audit gates")
    inventory_gate = _mapping(gates.get("inventory"), "Basemap inventory gate")
    if inventory_gate.get("passes") is not True:
        raise ValueError("Basemap inventory gate did not pass")
    if inventory_gate.get("inventorySha256") != inventory_id:
        raise ValueError("Basemap inventory gate differs from the immutable inventory path")
    if inventory_gate.get("tileCount") != integrity_tile_count:
        raise ValueError("Basemap inventory gate tile count differs from map-assets")
    if inventory_gate.get("totalBytes") != integrity_total_bytes:
        raise ValueError("Basemap inventory gate total bytes differs from map-assets")
    _verify_published_tiles(
        tiles_inventory_payload,
        version_path=version_path,
        tile_root=tile_root,
        expected_count=integrity_tile_count,
        expected_total_bytes=integrity_total_bytes,
    )
    derivation = _mapping(pyramid.get("derivation"), "Basemap derivation")
    _verify_artifact_record(
        derivation.get("receipt"),
        root=metadata_root,
        kind="metadata",
        label="Basemap derivation receipt",
        canonical_json=True,
    )
    return _BasemapEvidence(path, _sha256_bytes(map_bytes), map_assets)


def _discover_basemap(
    *,
    dataset_id: str,
    snapshot_id: str,
    lock_map: Mapping[str, list[int | float]],
    renderer_contract: Mapping[str, Any],
    profile_fingerprint: object,
    generated_root: Path,
    metadata_root: Path,
) -> _BasemapEvidence:
    eligible: list[_BasemapEvidence] = []
    errors: list[str] = []
    dataset_root = metadata_root / dataset_id
    _ensure_no_symlink(dataset_root, metadata_root, "Prepared basemap dataset root")
    if dataset_root.is_dir():
        for path in sorted(dataset_root.rglob("map-assets.json")):
            try:
                value, _ = _read_object(
                    path, "Prepared map-assets candidate", boundary=metadata_root, canonical=True
                )
                if value.get("datasetId") != dataset_id or value.get("snapshotId") != snapshot_id:
                    continue
                eligible.append(
                    _validate_basemap(
                        path,
                        dataset_id=dataset_id,
                        snapshot_id=snapshot_id,
                        lock_map=lock_map,
                        renderer_contract=renderer_contract,
                        profile_fingerprint=profile_fingerprint,
                        generated_root=generated_root,
                        metadata_root=metadata_root,
                    )
                )
            except ValueError as error:
                errors.append(f"{path}: {error}")
    if errors:
        raise ValueError("Invalid prepared basemap evidence: " + "; ".join(errors))
    if len(eligible) != 1:
        raise ValueError(
            f"Expected exactly one eligible prepared basemap for {dataset_id}/{snapshot_id}; "
            f"found {len(eligible)}"
        )
    return eligible[0]


def _validate_catalog(
    path: Path,
    *,
    dataset_id: str,
    snapshot_id: str,
    catalog_contract: Mapping[str, Any] | None,
    generated_root: Path,
    metadata_root: Path,
) -> _CatalogEvidence:
    audit, audit_bytes = _read_object(
        path, "Prepared catalog audit", boundary=metadata_root, canonical=True
    )
    _require_artifact_identity(audit, dataset_id, snapshot_id, "Prepared catalog audit")
    if audit.get("passes") is not True:
        raise ValueError("Prepared catalog audit did not pass")
    _verify_audit_hash(audit, "Prepared catalog audit")
    if catalog_contract is not None:
        exact_bindings = {
            "worldCounts": "records",
            "resolutionCounts": "resolution",
            "exclusions": "exclusions",
        }
        for contract_key, audit_key in exact_bindings.items():
            expected = catalog_contract.get(contract_key)
            if expected is not None and audit.get(audit_key) != expected:
                raise ValueError(
                    f"Prepared catalog {audit_key} differs from release lock {contract_key}"
                )
        expected_policy = catalog_contract.get("policyFingerprint")
        if expected_policy is not None and audit.get("policyFingerprint") != expected_policy:
            raise ValueError("Prepared catalog policy fingerprint differs from the release lock")
        grouping = _mapping(audit.get("grouping"), "Prepared catalog grouping")
        exclusions = _mapping(audit.get("exclusions"), "Prepared catalog exclusions")
        for contract_key, actual in (
            ("catalogCounts", grouping),
            ("regionCounts", grouping),
            ("dropped", exclusions),
        ):
            expected_subset = catalog_contract.get(contract_key)
            if expected_subset is None:
                continue
            expected_mapping = _mapping(
                expected_subset, f"Release lock catalog {contract_key}"
            )
            if any(actual.get(key) != value for key, value in expected_mapping.items()):
                raise ValueError(
                    f"Prepared catalog evidence differs from release lock {contract_key}"
                )
    inventory = _mapping(audit.get("inventory"), "Prepared catalog inventory")
    _require_artifact_identity(inventory, dataset_id, snapshot_id, "Prepared catalog inventory")
    if catalog_contract is not None and catalog_contract.get("implementationSha256") is not None:
        expected_implementation = _sha256(
            catalog_contract.get("implementationSha256"),
            "Release lock catalog implementation SHA-256",
        )
        if inventory.get("implementationSha256") != expected_implementation:
            raise ValueError("Prepared catalog implementation differs from the release lock")
        extractor = _mapping(audit.get("extractor"), "Prepared catalog extractor")
        if extractor.get("sha256") != expected_implementation:
            raise ValueError("Prepared catalog extractor differs from the release lock")
    inventory_sha = _sha256_bytes(canonical_json_bytes(dict(inventory))[:-1])
    if audit.get("catalogInventorySha256") != inventory_sha:
        raise ValueError("Prepared catalog inventory SHA-256 does not match its payload")
    relative = path.relative_to(metadata_root)
    expected_relative = Path(dataset_id) / "catalogs" / inventory_sha / "catalog-audit.json"
    if relative != expected_relative:
        raise ValueError("Prepared catalog audit is outside its immutable inventory path")
    artifacts = _mapping(inventory.get("artifacts"), "Prepared catalog artifacts")
    if set(artifacts) != {"locations", "english"}:
        raise ValueError("Prepared catalog inventory must bind locations and English artifacts")
    generated_version = generated_root / dataset_id / "catalogs" / inventory_sha
    locations_path, locations_bytes, locations = _verify_relative_artifact(
        artifacts["locations"],
        base=generated_version,
        boundary=generated_root,
        label="Locations artifact",
        canonical_json=True,
    )
    english_path, english_bytes, english = _verify_relative_artifact(
        artifacts["english"],
        base=generated_version,
        boundary=generated_root,
        label="English catalog artifact",
        canonical_json=True,
    )
    if locations_path != generated_version / "locations.json":
        raise ValueError("Locations artifact must use the canonical locations.json path")
    if english_path != generated_version / "locales/en.json":
        raise ValueError("English artifact must use the canonical locales/en.json path")
    assert locations is not None and english is not None
    _require_artifact_identity(locations, dataset_id, snapshot_id, "Locations artifact")
    _require_artifact_identity(english, dataset_id, snapshot_id, "English catalog artifact")
    if english.get("locale") != "en":
        raise ValueError("English catalog artifact has the wrong locale")
    return _CatalogEvidence(
        audit_path=path,
        audit_sha256=_sha256_bytes(audit_bytes),
        audit_bytes=len(audit_bytes),
        locations_path=locations_path,
        locations_sha256=_sha256_bytes(locations_bytes),
        locations_bytes=len(locations_bytes),
        english_path=english_path,
        english_sha256=_sha256_bytes(english_bytes),
        english_bytes=len(english_bytes),
    )


def _discover_catalog(
    *,
    dataset_id: str,
    snapshot_id: str,
    catalog_contract: Mapping[str, Any] | None,
    generated_root: Path,
    metadata_root: Path,
) -> _CatalogEvidence:
    eligible: list[_CatalogEvidence] = []
    errors: list[str] = []
    dataset_root = metadata_root / dataset_id
    _ensure_no_symlink(dataset_root, metadata_root, "Prepared catalog dataset root")
    if dataset_root.is_dir():
        for path in sorted(dataset_root.rglob("catalog-audit.json")):
            try:
                value, _ = _read_object(
                    path, "Prepared catalog candidate", boundary=metadata_root, canonical=True
                )
                if value.get("datasetId") != dataset_id or value.get("snapshotId") != snapshot_id:
                    continue
                eligible.append(
                    _validate_catalog(
                        path,
                        dataset_id=dataset_id,
                        snapshot_id=snapshot_id,
                        catalog_contract=catalog_contract,
                        generated_root=generated_root,
                        metadata_root=metadata_root,
                    )
                )
            except ValueError as error:
                errors.append(f"{path}: {error}")
    if errors:
        raise ValueError("Invalid prepared catalog evidence: " + "; ".join(errors))
    if len(eligible) != 1:
        raise ValueError(
            f"Expected exactly one eligible prepared catalog for {dataset_id}/{snapshot_id}; "
            f"found {len(eligible)}"
        )
    return eligible[0]


def _localized(value: object, label: str) -> dict[str, str]:
    if isinstance(value, str):
        if not value:
            raise ValueError(f"{label} cannot be empty")
        return {"en": value}
    mapping = _mapping(value, label)
    english = _required_string(mapping.get("en"), f"{label}.en")
    return {"en": english}


def _regions(value: object) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_sequence(value, "Release profile regions")):
        item = _mapping(raw, f"Release profile regions[{index}]")
        result.append(
            {
                "id": _identifier(item.get("id"), f"Release profile regions[{index}] id"),
                "title": _localized(
                    item.get("title"), f"Release profile regions[{index}] title"
                ),
                "kind": copy.deepcopy(item.get("kind")),
                "status": copy.deepcopy(item.get("status")),
            }
        )
    if not result:
        raise ValueError("Release profile must define at least one region")
    return result


def _manifest(
    profile: Mapping[str, object],
    lock: Mapping[str, object],
    *,
    dataset_id: str,
    snapshot_id: str,
    lock_map: Mapping[str, list[int | float]],
    basemap: _BasemapEvidence,
    catalog: _CatalogEvidence,
    generated_root: Path,
    metadata_root: Path,
) -> dict[str, Any]:
    release = _mapping(profile.get("release"), "Release profile release")
    release_descriptor = {
        "name": _required_string(release.get("name"), "Release name"),
        "version": _required_string(release.get("version"), "Release version"),
        "build": copy.deepcopy(release.get("build")),
    }
    regions = _regions(profile.get("regions"))
    return {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "mapKey": profile["mapKey"],
        "snapshotId": snapshot_id,
        "title": _localized(profile.get("title"), "Release title"),
        "summary": _localized(profile.get("summary"), "Release summary"),
        "release": release_descriptor,
        "readiness": {
            "status": "ready",
            "exactProfile": True,
            "blockers": [],
            "warnings": [],
        },
        "localization": {
            "defaultLocale": "en",
            "locales": [
                {
                    "locale": "en",
                    "status": "available",
                    "coverage": 1,
                    "fallbackLocale": None,
                }
            ],
        },
        "regions": regions,
        "profile": _profile_descriptors(profile, lock),
        "map": {
            "projection": {
                "code": "TES3:WORLD",
                "units": "world-units",
                "cellSize": 8192,
                "extent": copy.deepcopy(lock_map["extent"]),
                "center": copy.deepcopy(lock_map["center"]),
            },
            "tileGrid": {
                "tileSize": 512,
                "origin": copy.deepcopy(lock_map["origin"]),
                "resolutions": copy.deepcopy(lock_map["resolutions"]),
            },
        },
        "artifacts": {
            "locations": {
                "url": _url_for(catalog.locations_path, kind="generated", root=generated_root),
                "mediaType": "application/json",
                "sha256": catalog.locations_sha256,
                "bytes": catalog.locations_bytes,
            },
            "locales": [
                {
                    "locale": "en",
                    "artifact": {
                        "url": _url_for(
                            catalog.english_path,
                            kind="generated",
                            root=generated_root,
                        ),
                        "mediaType": "application/json",
                        "sha256": catalog.english_sha256,
                        "bytes": catalog.english_bytes,
                    },
                }
            ],
            "tiles": {
                "manifestUrl": _url_for(basemap.path, kind="metadata", root=metadata_root),
                "sha256": basemap.sha256,
            },
            "catalogAudit": {
                "url": _url_for(catalog.audit_path, kind="metadata", root=metadata_root),
                "mediaType": "application/json",
                "sha256": catalog.audit_sha256,
                "bytes": catalog.audit_bytes,
            },
        },
        "provenance": {
            "kind": "generated",
            "notes": [
                "This manifest was assembled from the pinned Tamriel Rebuilt release lock.",
                "Its basemap and catalog passed immutable evidence verification before activation.",
            ],
            "knownIssues": [],
        },
    }


def _candidate_index(
    *, dataset_id: str, state: _ActiveState, map_key: str = "tamriel-rebuilt"
) -> dict[str, Any]:
    entries = copy.deepcopy(state.entries_by_map)
    order = {"original": 0, "tamriel-rebuilt": 1, "project-cyrodiil": 2, "home-of-nords": 3, "azurian-isles": 4}
    entries[map_key] = {
        "datasetId": dataset_id,
        "manifestUrl": f"/datasets/manifests/{dataset_id}.json",
        "order": order[map_key],
    }
    return {
        "schemaVersion": 1,
        "defaultDatasetId": state.original_id,
        "datasets": sorted(entries.values(), key=lambda entry: entry["order"]),
    }


def _atomic_write(path: Path, payload: bytes, *, boundary: Path) -> None:
    _ensure_no_symlink(path, boundary, "Atomic write target")
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_no_symlink(path.parent, boundary, "Atomic write directory")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(path.parent)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _roots(
    *,
    generated_root: Path,
    metadata_root: Path,
    candidate_root: Path,
    active_datasets_root: Path | None,
    active_index_path: Path | None,
    active_manifests_root: Path | None,
    public_root: Path | None,
    create_candidate: bool,
) -> tuple[Path, Path, Path, Path]:
    generated = _require_root(generated_root, "Generated artifact root")
    metadata = _require_root(metadata_root, "Metadata artifact root")
    if active_datasets_root is not None:
        active = _require_root(active_datasets_root, "Active datasets root")
    else:
        if active_index_path is None or active_manifests_root is None:
            raise ValueError(
                "Provide active_datasets_root or both active_index_path and "
                "active_manifests_root"
            )
        index_path = _absolute(active_index_path)
        manifests = _require_root(active_manifests_root, "Active manifests root")
        active = _require_root(index_path.parent, "Active datasets root")
        if index_path != active / "index.json" or manifests != active / "manifests":
            raise ValueError("Active index/manifests must use the canonical datasets layout")
    if active_index_path is not None and _absolute(active_index_path) != active / "index.json":
        raise ValueError("active_index_path differs from active_datasets_root/index.json")
    if (
        active_manifests_root is not None
        and _absolute(active_manifests_root) != active / "manifests"
    ):
        raise ValueError("active_manifests_root differs from active datasets layout")
    if public_root is not None:
        public = _require_root(public_root, "Web public root")
        datasets = public / "datasets"
        if (
            generated != datasets / "generated"
            or metadata != datasets / "metadata"
            or active != datasets
        ):
            raise ValueError("Artifact and active roots differ from the web public layout")
    return (
        generated,
        metadata,
        active,
        _require_root(candidate_root, "Candidate root", create=create_candidate),
    )


def _expected(
    profile: Mapping[str, object],
    lock: Mapping[str, object],
    *,
    generated_root: Path,
    metadata_root: Path,
    active_root: Path,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    dataset_id, snapshot_id = _identity(profile, lock)
    state = _active_state(active_root)
    _assert_future_identity(dataset_id, state)
    lock_map = _lock_map(lock)
    renderer_value = lock.get("renderer", lock.get("map", lock.get("topology")))
    renderer_contract = _mapping(renderer_value, "Release lock renderer")
    catalog_value = lock.get("catalog")
    catalog_contract = (
        _mapping(catalog_value, "Release lock catalog")
        if catalog_value is not None
        else None
    )
    basemap = _discover_basemap(
        dataset_id=dataset_id,
        snapshot_id=snapshot_id,
        lock_map=lock_map,
        renderer_contract=renderer_contract,
        profile_fingerprint=lock.get("profileFingerprint"),
        generated_root=generated_root,
        metadata_root=metadata_root,
    )
    catalog = _discover_catalog(
        dataset_id=dataset_id,
        snapshot_id=snapshot_id,
        catalog_contract=catalog_contract,
        generated_root=generated_root,
        metadata_root=metadata_root,
    )
    manifest = _manifest(
        profile,
        lock,
        dataset_id=dataset_id,
        snapshot_id=snapshot_id,
        lock_map=lock_map,
        basemap=basemap,
        catalog=catalog,
        generated_root=generated_root,
        metadata_root=metadata_root,
    )
    index = _candidate_index(dataset_id=dataset_id, state=state, map_key=str(profile["mapKey"]))
    return dataset_id, snapshot_id, manifest, index


def build_candidate(
    profile: Mapping[str, object],
    lock: Mapping[str, object],
    *,
    generated_root: Path,
    metadata_root: Path,
    candidate_root: Path,
    active_datasets_root: Path | None = None,
    active_index_path: Path | None = None,
    active_manifests_root: Path | None = None,
    public_root: Path | None = None,
) -> CandidateBundle:
    """Build a verified candidate without changing any active dataset file."""

    generated, metadata, active, candidate = _roots(
        generated_root=generated_root,
        metadata_root=metadata_root,
        candidate_root=candidate_root,
        active_datasets_root=active_datasets_root,
        active_index_path=active_index_path,
        active_manifests_root=active_manifests_root,
        public_root=public_root,
        create_candidate=True,
    )
    dataset_id, snapshot_id, manifest, index = _expected(
        profile,
        lock,
        generated_root=generated,
        metadata_root=metadata,
        active_root=active,
    )
    manifest_path = candidate / "manifests" / f"{dataset_id}.json"
    index_path = candidate / "index.json"
    _atomic_write(manifest_path, canonical_json_bytes(manifest), boundary=candidate)
    _atomic_write(index_path, canonical_json_bytes(index), boundary=candidate)
    return verify_candidate(
        profile,
        lock,
        generated_root=generated,
        metadata_root=metadata,
        active_datasets_root=active,
        candidate_root=candidate,
    )


def verify_candidate(
    profile: Mapping[str, object],
    lock: Mapping[str, object],
    *,
    generated_root: Path,
    metadata_root: Path,
    candidate_root: Path,
    active_datasets_root: Path | None = None,
    active_index_path: Path | None = None,
    active_manifests_root: Path | None = None,
    public_root: Path | None = None,
) -> CandidateBundle:
    """Re-read every candidate/evidence binding and fail on any drift or tampering."""

    generated, metadata, active, candidate = _roots(
        generated_root=generated_root,
        metadata_root=metadata_root,
        candidate_root=candidate_root,
        active_datasets_root=active_datasets_root,
        active_index_path=active_index_path,
        active_manifests_root=active_manifests_root,
        public_root=public_root,
        create_candidate=False,
    )
    dataset_id, snapshot_id, expected_manifest, expected_index = _expected(
        profile,
        lock,
        generated_root=generated,
        metadata_root=metadata,
        active_root=active,
    )
    manifest_path = candidate / "manifests" / f"{dataset_id}.json"
    index_path = candidate / "index.json"
    manifest, manifest_payload = _read_object(
        manifest_path, "Candidate manifest", boundary=candidate, canonical=True
    )
    index, index_payload = _read_object(
        index_path, "Candidate index", boundary=candidate, canonical=True
    )
    if manifest != expected_manifest:
        raise ValueError("Candidate manifest differs from the release lock or prepared artifacts")
    if index != expected_index:
        raise ValueError("Candidate index differs from the preserved maps plus the new release")
    return CandidateBundle(
        dataset_id,
        snapshot_id,
        manifest_path,
        index_path,
        manifest_payload,
        index_payload,
    )


def _stage_replace(path: Path, payload: bytes, *, boundary: Path) -> Path:
    _ensure_no_symlink(path, boundary, "Activation target")
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_no_symlink(path.parent, boundary, "Activation directory")
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{path.name}.",
        suffix=".activate",
        dir=path.parent,
        delete=False,
    ) as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        return Path(stream.name)


def activate_candidate(
    profile: Mapping[str, object],
    lock: Mapping[str, object],
    *,
    generated_root: Path,
    metadata_root: Path,
    candidate_root: Path,
    active_datasets_root: Path | None = None,
    active_index_path: Path | None = None,
    active_manifests_root: Path | None = None,
    public_root: Path | None = None,
) -> CandidateBundle:
    """Verify and atomically activate a new TR dataset; the index switches last."""

    _, _, active, _ = _roots(
        generated_root=generated_root,
        metadata_root=metadata_root,
        candidate_root=candidate_root,
        active_datasets_root=active_datasets_root,
        active_index_path=active_index_path,
        active_manifests_root=active_manifests_root,
        public_root=public_root,
        create_candidate=False,
    )
    baseline_index = (active / "index.json").read_bytes()
    bundle = verify_candidate(
        profile,
        lock,
        generated_root=generated_root,
        metadata_root=metadata_root,
        active_datasets_root=active_datasets_root,
        candidate_root=candidate_root,
        active_index_path=active_index_path,
        active_manifests_root=active_manifests_root,
        public_root=public_root,
    )
    if (active / "index.json").read_bytes() != baseline_index:
        raise ValueError("Active datasets changed after candidate verification")
    state = _active_state(active)
    _assert_future_identity(bundle.dataset_id, state)
    manifest_payload = bundle._verified_manifest_bytes
    index_payload = bundle._verified_index_bytes
    if not manifest_payload or not index_payload:
        raise RuntimeError("Candidate verification did not retain exact activation bytes")
    if index_payload != canonical_json_bytes(
        _candidate_index(dataset_id=bundle.dataset_id, state=state, map_key=str(profile["mapKey"]))
    ):
        raise ValueError("Active datasets changed after candidate verification")

    manifest_target = active / "manifests" / f"{bundle.dataset_id}.json"
    index_target = active / "index.json"
    staged_manifest: Path | None = None
    staged_index: Path | None = None
    try:
        staged_manifest = _stage_replace(manifest_target, manifest_payload, boundary=active)
        staged_index = _stage_replace(index_target, index_payload, boundary=active)
        if index_target.read_bytes() != baseline_index:
            raise ValueError("Active dataset index changed during activation")
        current = _active_state(active)
        if current != state:
            raise ValueError("Active datasets changed during activation")
        os.replace(staged_manifest, manifest_target)
        staged_manifest = None
        _fsync_directory(manifest_target.parent)
        os.replace(staged_index, index_target)
        staged_index = None
        _fsync_directory(active)
    finally:
        for temporary in (staged_manifest, staged_index):
            if temporary is not None and temporary.exists():
                temporary.unlink()
    if (
        manifest_target.read_bytes() != manifest_payload
        or index_target.read_bytes() != index_payload
    ):
        raise RuntimeError("Activated manifest or index failed read-back verification")
    return bundle


__all__ = [
    "CandidateBundle",
    "activate_candidate",
    "build_candidate",
    "canonical_json_bytes",
    "verify_candidate",
]
