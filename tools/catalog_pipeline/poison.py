from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tools.catalog_pipeline.catalog import CatalogBuild, build_catalog, validate_catalog_bundle
from tools.catalog_pipeline.tes3 import (
    EffectiveWorld,
    PluginInput,
    canonical_ref_id,
    merge_plugins,
)
from tools.openmw_renderer.profile import CONTENT_FILES, SOURCE_INPUTS, sha256_file


DATASET_ID = "poison-song-26.08"
SNAPSHOT_ID = "tr:poison-song-26.08:6964517551e0fcb0"
AUDIT_VERSION = "generic-tes3-catalog-v1"
CATALOG_DIRECTORY = "catalogs"
CATALOG_SOURCE_IDS = (
    "morrowind-esm",
    "tribunal-esm",
    "bloodmoon-esm",
    "tamriel-data-esm",
    "tr-mainland-esm",
)
PLUGIN_REGIONS = {
    "Morrowind.esm": "vvardenfell",
    "Tribunal.esm": "vvardenfell",
    "Bloodmoon.esm": "solstheim",
    "Tamriel_Data.esm": "tr-mainland",
    "TR_Mainland.esm": "tr-mainland",
}
MAP_EXTENT = (-229376, -475136, 409600, 278528)
IMPLEMENTATION_FILES = (
    Path("tools/tes3/records.py"),
    Path("tools/catalog_pipeline/tes3.py"),
    Path("tools/catalog_pipeline/catalog.py"),
    Path("tools/catalog_pipeline/poison.py"),
)
EXPECTED_WORLD_COUNTS = {
    "rawCellRecords": 9336,
    "effectiveCells": 9075,
    "effectiveInteriorCells": 5069,
    "effectiveExteriorCells": 4006,
    "rawDoorRecords": 1039,
    "effectiveDoors": 984,
    "doorOverrides": 55,
    "rawReferenceVersions": 1706102,
    "effectiveReferences": 1706101,
    "referenceOverrides": 1,
    "rawTeleportReferenceVersions": 14223,
    "effectiveTeleportReferences": 14223,
    "effectiveExteriorTeleportReferences": 4912,
    "movedReferenceVersions": 0,
    "cellDeletions": 0,
    "doorDeletions": 0,
    "referenceDeletions": 0,
    "ignoredRecords": 0,
}
EXPECTED_CATALOG_COUNTS = {
    "places": 4085,
    "interiorPlaces": 3755,
    "namedExteriorCells": 417,
    "namedExteriorPlaces": 330,
    "entrances": 4902,
    "multiEntrancePlaces": 697,
    "entrancesInMultiEntrancePlaces": 1844,
    "maximumEntrancesPerPlace": 14,
    "aliases": 0,
    "byRegion": {
        "solstheim": 92,
        "tr-mainland": 3052,
        "vvardenfell": 941,
    },
    "byType": {
        "ancestral-tomb": 240,
        "cave": 471,
        "dwemer-ruin": 81,
        "guild": 33,
        "house": 1116,
        "landmark": 100,
        "mine": 157,
        "other": 1192,
        "settlement": 131,
        "ship": 149,
        "shop": 158,
        "shrine": 112,
        "stronghold": 84,
        "temple": 61,
    },
}
EXPECTED_RESOLUTION_COUNTS = {
    "exteriorTeleports": 4912,
    "exteriorToExteriorTeleports": 10,
    "namedTeleportCandidates": 4902,
    "resolvedDoorBases": 4902,
    "resolvedDestinationCells": 4902,
    "catalogEntrances": 4902,
}
EXPECTED_REGION_COUNTS = {
    "entrancesByRegion": {
        "solstheim": 97,
        "tr-mainland": 3700,
        "vvardenfell": 1105,
    },
    "interiorPlacesByRegion": {
        "solstheim": 79,
        "tr-mainland": 2818,
        "vvardenfell": 858,
    },
    "namedExteriorPlacesByRegion": {
        "solstheim": 13,
        "tr-mainland": 234,
        "vvardenfell": 83,
    },
}
EXPECTED_EXCLUSIONS = {
    "automaticTestNameFiltering": False,
    "explicitDenylistEntries": 0,
    "exteriorDestinationPolicy": 10,
    "unreachableInteriorCells": 1314,
}
EXPECTED_DROPPED = {"exteriorDestinationPolicy": 10}
MASTER_SIZE_EXCEPTIONS = (
    {
        "dependentSha256": "661c96c6aa5e517d897f8b9de93c814d2aca16fd17b6e4ce7869486e3737064b",
        "masterSha256": "e94ca3a5c62e0228ac3782e813cae58c4e10da2e9e8b7611e0a8f5ff9a98d06f",
        "advertisedBytes": 17_200_101,
        "actualBytes": 17_199_325,
        "reason": "tr-mainland-tamriel-data-26.08-size-metadata",
    },
)


@dataclass(frozen=True, slots=True)
class ValidatedCatalog:
    root: Path
    audit: dict[str, Any]
    inventory_sha256: str
    locations_bytes: bytes
    english_bytes: bytes
    audit_bytes: bytes


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


def _artifact(payload: bytes, path: str) -> dict[str, object]:
    return {"path": path, "bytes": len(payload), "sha256": _sha256_bytes(payload)}


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
            temporary = Path(stream.name)
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _source_descriptors(source_root: Path) -> tuple[PluginInput, ...]:
    selected = {
        source.logical_id: source
        for source in SOURCE_INPUTS
        if source.logical_id in CATALOG_SOURCE_IDS
    }
    if len(selected) != len(CATALOG_SOURCE_IDS) or set(selected) != set(CATALOG_SOURCE_IDS):
        raise RuntimeError("Pinned catalog inputs do not match the OpenMW profile")
    plugins: list[PluginInput] = []
    for name, source_id in zip(CONTENT_FILES, CATALOG_SOURCE_IDS, strict=True):
        source = selected[source_id]
        path = source_root / source.relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Required catalog input is missing: {path}")
        actual = sha256_file(path)
        if actual != source.sha256:
            raise ValueError(
                f"Catalog input hash mismatch for {source.relative_path}: "
                f"expected {source.sha256}, got {actual}"
            )
        plugins.append(PluginInput(name=name, path=path, sha256=actual))
    return tuple(plugins)


def _known_master_size_exception(
    *,
    dependent: PluginInput,
    master: PluginInput,
    advertised_size: int | None,
    actual_size: int,
) -> str | None:
    for exception in MASTER_SIZE_EXCEPTIONS:
        if (
            exception["dependentSha256"] == dependent.sha256
            and exception["masterSha256"] == master.sha256
            and exception["advertisedBytes"] == advertised_size
            and exception["actualBytes"] == actual_size
        ):
            return str(exception["reason"])
    return None


def _input_audit(world: EffectiveWorld, source_root: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for load_order, (plugin, dependencies) in enumerate(
        zip(world.plugins, world.masters, strict=True)
    ):
        masters: list[dict[str, object]] = []
        for dependency in dependencies:
            master = world.plugins[dependency.resolved_plugin_index]
            actual_size = master.path.stat().st_size
            exception = None
            if dependency.advertised_size != actual_size:
                exception = _known_master_size_exception(
                    dependent=plugin,
                    master=master,
                    advertised_size=dependency.advertised_size,
                    actual_size=actual_size,
                )
                if exception is None:
                    raise ValueError(
                        f"Unexpected MAST size mismatch: {plugin.name} -> {master.name}, "
                        f"advertised={dependency.advertised_size}, actual={actual_size}"
                    )
            masters.append(
                {
                    "name": dependency.name,
                    "resolvedLoadOrder": dependency.resolved_plugin_index,
                    "advertisedBytes": dependency.advertised_size,
                    "actualBytes": actual_size,
                    "sizeMatches": dependency.advertised_size == actual_size,
                    "allowlistedException": exception,
                }
            )
        result.append(
            {
                "loadOrder": load_order,
                "name": plugin.name,
                "relativePath": plugin.path.relative_to(source_root).as_posix(),
                "bytes": plugin.path.stat().st_size,
                "sha256": plugin.sha256,
                "masters": masters,
            }
        )
    return result


def _implementation_audit(repo_root: Path) -> dict[str, object]:
    files = []
    for relative in IMPLEMENTATION_FILES:
        path = repo_root / relative
        payload = path.read_bytes()
        files.append(
            {
                "path": relative.as_posix(),
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
        )
    return {
        "files": files,
        "sha256": _sha256_bytes(_canonical_json_bytes(files)),
    }


def _entrance_histogram(locations: Mapping[str, object]) -> dict[str, int]:
    histogram: Counter[int] = Counter()
    for place in locations["places"]:
        count = len(place["entrances"])
        if count:
            histogram[count] += 1
    return {str(key): histogram[key] for key in sorted(histogram)}


def _catalog_artifact_metrics(
    locations: Mapping[str, object],
    english: Mapping[str, object],
) -> dict[str, object]:
    entrance_regions: Counter[str] = Counter()
    interior_regions: Counter[str] = Counter()
    exterior_regions: Counter[str] = Counter()
    place_regions: Counter[str] = Counter()
    place_types: Counter[str] = Counter()
    exterior_names: defaultdict[str, list[str]] = defaultdict(list)
    long_range: list[dict[str, object]] = []
    entrances_total = 0
    multi_entrance_places = 0
    entrances_in_multi = 0
    maximum_entrances = 0
    named_exterior_cells = 0
    aliases = 0
    inside_extent = True
    min_x, min_y, max_x, max_y = MAP_EXTENT
    for place, locale in zip(locations["places"], english["places"], strict=True):
        positions = [place["mapPosition"]]
        positions.extend(entrance["coordinate"] for entrance in place["entrances"])
        if any(
            not (min_x <= float(position[0]) <= max_x and min_y <= float(position[1]) <= max_y)
            for position in positions
        ):
            inside_extent = False
        entrances = place["entrances"]
        entrance_count = len(entrances)
        entrances_total += entrance_count
        maximum_entrances = max(maximum_entrances, entrance_count)
        aliases += len(locale["aliases"])
        place_regions[place["regionId"]] += 1
        place_types[place["type"]] += 1
        entrance_regions[place["regionId"]] += len(entrances)
        if not entrances:
            exterior_regions[place["regionId"]] += 1
            named_exterior_cells += len(place["sources"])
            exterior_names[str(locale["name"])].append(str(place["id"]))
        elif len(entrances) > 1:
            interior_regions[place["regionId"]] += 1
            multi_entrance_places += 1
            entrances_in_multi += entrance_count
            cells = [tuple(entrance["exteriorCell"]) for entrance in entrances]
            span = max(
                max(cell[0] for cell in cells) - min(cell[0] for cell in cells),
                max(cell[1] for cell in cells) - min(cell[1] for cell in cells),
            )
            if span > 1:
                long_range.append(
                    {
                        "placeId": place["id"],
                        "name": locale["name"],
                        "exteriorCells": [list(cell) for cell in sorted(set(cells))],
                        "chebyshevSpanCells": span,
                    }
                )
        else:
            interior_regions[place["regionId"]] += 1
    split_names = [
        {"name": name, "placeIds": sorted(place_ids)}
        for name, place_ids in sorted(exterior_names.items())
        if len(place_ids) > 1
    ]
    return {
        "places": len(locations["places"]),
        "interiorPlaces": sum(interior_regions.values()),
        "namedExteriorCells": named_exterior_cells,
        "namedExteriorPlaces": sum(exterior_regions.values()),
        "entrances": entrances_total,
        "multiEntrancePlaces": multi_entrance_places,
        "entrancesInMultiEntrancePlaces": entrances_in_multi,
        "maximumEntrancesPerPlace": maximum_entrances,
        "aliases": aliases,
        "byRegion": dict(sorted(place_regions.items())),
        "byType": dict(sorted(place_types.items())),
        "entranceHistogram": _entrance_histogram(locations),
        "entrancesByRegion": dict(sorted(entrance_regions.items())),
        "interiorPlacesByRegion": dict(sorted(interior_regions.items())),
        "namedExteriorPlacesByRegion": dict(sorted(exterior_regions.items())),
        "longRangeMultiEntrancePlaces": long_range,
        "splitExteriorNames": split_names,
        "allCoordinatesWithinManifestExtent": inside_extent,
    }


def _require_expected_counts(
    actual: Mapping[str, object], expected: Mapping[str, object], label: str
) -> None:
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key, 0) != value
    }
    if mismatches:
        raise ValueError(f"Pinned {label} counts changed: {mismatches}")


def build_poison_catalog(
    *, source_root: Path, output_root: Path, repo_root: Path
) -> ValidatedCatalog:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    plugins = _source_descriptors(source_root)
    world = merge_plugins(plugins)
    build = build_catalog(
        world,
        dataset_id=DATASET_ID,
        snapshot_id=SNAPSHOT_ID,
        plugin_regions=PLUGIN_REGIONS,
    )
    _require_expected_counts(world.counts, EXPECTED_WORLD_COUNTS, "world")
    _require_expected_counts(build.counts, EXPECTED_CATALOG_COUNTS, "catalog")
    _require_expected_counts(build.resolution, EXPECTED_RESOLUTION_COUNTS, "resolution")
    if build.dropped != EXPECTED_DROPPED:
        raise ValueError(f"Pinned catalog exclusions changed: {build.dropped}")

    diagnostics = _catalog_artifact_metrics(build.locations, build.english)
    if not diagnostics["allCoordinatesWithinManifestExtent"]:
        raise ValueError("Catalog coordinate falls outside the release manifest extent")
    _require_expected_counts(diagnostics, EXPECTED_CATALOG_COUNTS, "artifact catalog")
    _require_expected_counts(diagnostics, EXPECTED_REGION_COUNTS, "region")
    for key, value in build.counts.items():
        if key != "byTypeRule" and diagnostics.get(key) != value:
            raise ValueError(
                f"Catalog model/artifact metric mismatch for {key}: "
                f"{value!r} != {diagnostics.get(key)!r}"
            )
    locations_bytes = _json_file_bytes(build.locations)
    english_bytes = _json_file_bytes(build.english)
    artifacts = {
        "locations": _artifact(locations_bytes, "locations.json"),
        "english": _artifact(english_bytes, "locales/en.json"),
    }
    inputs = _input_audit(world, source_root)
    implementation = _implementation_audit(repo_root)
    inventory = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "inputs": inputs,
        "implementationSha256": implementation["sha256"],
        "policyFingerprint": build.policy_fingerprint,
        "artifacts": artifacts,
    }
    inventory_sha256 = _sha256_bytes(_canonical_json_bytes(inventory))
    audit_core = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "auditVersion": AUDIT_VERSION,
        "catalogInventorySha256": inventory_sha256,
        "inventory": inventory,
        "inputs": inputs,
        "extractor": implementation,
        "encoding": {
            "strings": "windows-1252-strict",
            "termination": "first-nul",
            "recordIdentity": "ascii-a-z-lowercase-only",
        },
        "policy": build.policy,
        "policyFingerprint": build.policy_fingerprint,
        "records": world.counts,
        "resolution": build.resolution,
        "grouping": {**diagnostics, "byTypeRule": build.counts["byTypeRule"]},
        "exclusions": {
            **build.dropped,
            "unreachableInteriorCells": world.counts["effectiveInteriorCells"]
            - build.counts["interiorPlaces"],
            "explicitDenylistEntries": 0,
            "automaticTestNameFiltering": False,
        },
        "integrity": {
            **build.gates,
            "expectedWorldCounts": True,
            "expectedCatalogCounts": True,
            "expectedResolutionCounts": True,
            "expectedRegionCounts": True,
            "expectedExclusions": True,
            "canonicalJsonWithLf": True,
            "allCoordinatesWithinManifestExtent": True,
            "artifacts": artifacts,
        },
        "passes": True,
    }
    audit = {
        **audit_core,
        "auditSha256": _sha256_bytes(_canonical_json_bytes(audit_core)),
    }
    audit_bytes = _json_file_bytes(audit)
    _atomic_write(output_root / "locations.json", locations_bytes)
    _atomic_write(output_root / "locales/en.json", english_bytes)
    _atomic_write(output_root / "catalog-audit.json", audit_bytes)
    return validate_catalog(output_root)


def _read_canonical_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    if payload != _json_file_bytes(value):
        raise ValueError(f"{label} is not canonical UTF-8 JSON with one trailing LF")
    return value, payload


def validate_catalog(root: Path) -> ValidatedCatalog:
    root = root.resolve()
    locations, locations_bytes = _read_canonical_json(root / "locations.json", "Locations")
    english, english_bytes = _read_canonical_json(root / "locales/en.json", "English locale")
    audit, audit_bytes = _read_canonical_json(root / "catalog-audit.json", "Catalog audit")
    for label, value in (("locations", locations), ("English locale", english), ("audit", audit)):
        if value.get("datasetId") != DATASET_ID or value.get("snapshotId") != SNAPSHOT_ID:
            raise ValueError(f"{label} dataset identity does not match the TR release")
    if english.get("locale") != "en":
        raise ValueError("English locale artifact has the wrong locale")
    if audit.get("auditVersion") != AUDIT_VERSION or audit.get("passes") is not True:
        raise ValueError("Catalog audit is not a passing supported audit")
    if audit.get("policyFingerprint") != _sha256_bytes(
        _canonical_json_bytes(audit.get("policy"))
    ):
        raise ValueError("Catalog policy fingerprint does not match its payload")
    audit_core = {key: value for key, value in audit.items() if key != "auditSha256"}
    if audit.get("auditSha256") != _sha256_bytes(_canonical_json_bytes(audit_core)):
        raise ValueError("Catalog audit logical SHA-256 does not match its payload")
    inventory = audit.get("inventory")
    if not isinstance(inventory, dict):
        raise ValueError("Catalog inventory is missing")
    extractor = audit.get("extractor")
    if not isinstance(extractor, dict):
        raise ValueError("Catalog extractor identity is missing")
    current_extractor = _implementation_audit(Path(__file__).resolve().parents[2])
    if extractor != current_extractor:
        raise ValueError("Catalog extractor identity is stale")
    if (
        inventory.get("datasetId") != DATASET_ID
        or inventory.get("snapshotId") != SNAPSHOT_ID
        or inventory.get("inputs") != audit.get("inputs")
        or inventory.get("implementationSha256") != extractor.get("sha256")
        or inventory.get("policyFingerprint") != audit.get("policyFingerprint")
    ):
        raise ValueError("Catalog inventory bindings are inconsistent")
    inventory_sha256 = _sha256_bytes(_canonical_json_bytes(inventory))
    if audit.get("catalogInventorySha256") != inventory_sha256:
        raise ValueError("Catalog inventory SHA-256 does not match its payload")
    artifacts = inventory.get("artifacts")
    actual_artifacts = {
        "locations": _artifact(locations_bytes, "locations.json"),
        "english": _artifact(english_bytes, "locales/en.json"),
    }
    if artifacts != actual_artifacts:
        raise ValueError("Catalog artifacts do not match the inventory")
    location_ids = [place["id"] for place in locations.get("places", [])]
    locale_ids = [place["placeId"] for place in english.get("places", [])]
    if location_ids != locale_ids:
        raise ValueError("Locations and English locale IDs/order differ")
    inputs = audit.get("inputs")
    if not isinstance(inputs, list):
        raise ValueError("Catalog input audit is malformed")
    known_plugins = {
        str(item["name"])
        for item in inputs
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if len(known_plugins) != len(inputs):
        raise ValueError("Catalog input plugin list is malformed or duplicated")
    semantic_gates = validate_catalog_bundle(
        locations,
        english,
        known_plugins={canonical_ref_id(plugin) for plugin in known_plugins},
    )
    metrics = _catalog_artifact_metrics(locations, english)
    _require_expected_counts(metrics, EXPECTED_CATALOG_COUNTS, "published catalog")
    _require_expected_counts(metrics, EXPECTED_REGION_COUNTS, "published region")
    grouping = audit.get("grouping")
    if not isinstance(grouping, dict):
        raise ValueError("Catalog grouping audit is malformed")
    for key, value in metrics.items():
        if grouping.get(key) != value:
            raise ValueError(f"Catalog grouping audit is stale for {key}")
    type_rules = grouping.get("byTypeRule")
    if (
        not isinstance(type_rules, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for key, value in type_rules.items()
        )
        or sum(type_rules.values()) != metrics["places"]
    ):
        raise ValueError("Catalog type-rule audit is malformed")
    records = audit.get("records")
    resolution = audit.get("resolution")
    exclusions = audit.get("exclusions")
    if not isinstance(records, dict) or not isinstance(resolution, dict):
        raise ValueError("Catalog record/resolution audit is malformed")
    _require_expected_counts(records, EXPECTED_WORLD_COUNTS, "published world")
    _require_expected_counts(resolution, EXPECTED_RESOLUTION_COUNTS, "published resolution")
    if exclusions != EXPECTED_EXCLUSIONS:
        raise ValueError("Catalog exclusion audit does not match the pinned policy")
    integrity = audit.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("artifacts") != actual_artifacts:
        raise ValueError("Catalog integrity audit is malformed")
    required_integrity_gates = {
        *semantic_gates,
        "expectedWorldCounts",
        "expectedCatalogCounts",
        "expectedResolutionCounts",
        "expectedRegionCounts",
        "expectedExclusions",
        "canonicalJsonWithLf",
        "allCoordinatesWithinManifestExtent",
    }
    if any(integrity.get(key) is not True for key in required_integrity_gates):
        raise ValueError("Catalog integrity audit contains a failing or missing gate")
    return ValidatedCatalog(
        root=root,
        audit=audit,
        inventory_sha256=inventory_sha256,
        locations_bytes=locations_bytes,
        english_bytes=english_bytes,
        audit_bytes=audit_bytes,
    )


def _publish_tree(
    target: Path,
    artifacts: Mapping[Path, bytes],
    *,
    boundary: Path,
) -> bool:
    boundary = Path(os.path.abspath(boundary))
    target = Path(os.path.abspath(target))
    if target == boundary or boundary not in target.parents:
        raise ValueError(f"Immutable catalog target escapes its publication root: {target}")
    current = boundary
    for part in target.relative_to(boundary).parts:
        if current.is_symlink():
            raise ValueError(f"Immutable catalog path contains a symlink: {current}")
        current /= part
    if target.is_symlink():
        raise ValueError(f"Immutable catalog target cannot be a symlink: {target}")
    for relative in artifacts:
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError(f"Immutable catalog artifact path is unsafe: {relative}")
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"Immutable catalog target is not a directory: {target}")
        actual: dict[Path, bytes] = {}
        for path in target.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"Immutable catalog tree contains a symlink: {path}")
            if path.is_file():
                actual[path.relative_to(target)] = path.read_bytes()
        if actual != dict(artifacts):
            raise ValueError(f"Immutable catalog target differs: {target}")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent))
    try:
        for relative, payload in sorted(artifacts.items(), key=lambda item: item[0].as_posix()):
            _atomic_write(staging / relative, payload)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return True


def prepare_catalog(
    *, source_root: Path, public_root: Path, metadata_root: Path
) -> dict[str, object]:
    validated = validate_catalog(source_root)
    version = validated.inventory_sha256
    public_root = Path(os.path.abspath(public_root))
    metadata_root = Path(os.path.abspath(metadata_root))
    generated_target = public_root / DATASET_ID / CATALOG_DIRECTORY / version
    metadata_target = metadata_root / DATASET_ID / CATALOG_DIRECTORY / version
    generated_created = _publish_tree(
        generated_target,
        {
            Path("locations.json"): validated.locations_bytes,
            Path("locales/en.json"): validated.english_bytes,
        },
        boundary=public_root,
    )
    metadata_created = _publish_tree(
        metadata_target,
        {Path("catalog-audit.json"): validated.audit_bytes},
        boundary=metadata_root,
    )
    return {
        "catalogInventorySha256": version,
        "generatedCreated": generated_created,
        "generatedRoot": str(generated_target),
        "metadataCreated": metadata_created,
        "metadataRoot": str(metadata_target),
    }


def _parser(repo_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and publish the Tamriel Rebuilt EN catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_build = repo_root / "local-data/catalog-production" / DATASET_ID
    build = subparsers.add_parser("build")
    build.add_argument("--source-root", type=Path, default=repo_root / "local-data/inputs")
    build.add_argument("--output", type=Path, default=default_build)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--source", type=Path, default=default_build)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--source", type=Path, default=default_build)
    prepare.add_argument(
        "--public-root", type=Path, default=repo_root / "apps/web/public/datasets/generated"
    )
    prepare.add_argument(
        "--metadata-root", type=Path, default=repo_root / "apps/web/public/datasets/metadata"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    args = _parser(repo_root).parse_args(argv)
    if args.command == "build":
        result = build_poison_catalog(
            source_root=args.source_root,
            output_root=args.output,
            repo_root=repo_root,
        )
        payload = {
            "catalogInventorySha256": result.inventory_sha256,
            "output": str(result.root),
            "places": result.audit["grouping"]["places"],
            "entrances": result.audit["grouping"]["entrances"],
        }
    elif args.command == "validate":
        result = validate_catalog(args.source)
        payload = {
            "catalogInventorySha256": result.inventory_sha256,
            "source": str(result.root),
            "valid": True,
        }
    else:
        payload = prepare_catalog(
            source_root=args.source,
            public_root=args.public_root,
            metadata_root=args.metadata_root,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
