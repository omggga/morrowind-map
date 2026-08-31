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

from tools.catalog_pipeline.catalog import build_catalog, validate_catalog_bundle
from tools.catalog_pipeline.tes3 import PluginInput, canonical_ref_id, merge_plugins


DATASET_ID = "original-goty-hd"
AUDIT_VERSION = "generic-tes3-catalog-v1"
CATALOG_DIRECTORY = "catalogs"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_ROOT = (REPO_ROOT.parent / "morr-dev").resolve()
MAP_EXTENT = (-229376, -155648, 196608, 237568)
PLUGIN_REGIONS = {
    "Morrowind.esm": "vvardenfell",
    "Tribunal.esm": "vvardenfell",
    "Bloodmoon.esm": "solstheim",
}


@dataclass(frozen=True, slots=True)
class PinnedInput:
    name: str
    relative_path: str
    bytes: int
    sha256: str


PINNED_INPUTS = (
    PinnedInput(
        "Morrowind.esm",
        "bsa/Morrowind.esm",
        79_837_557,
        "5c3c8c2cbd20e25901b59b3ece33d36b7ef0e3d60ad8d11828bcc61a5ead1647",
    ),
    PinnedInput(
        "Tribunal.esm",
        "bsa/Tribunal.esm",
        4_565_686,
        "2ace511f23cc2a9ddd5f3aa59c7919789b9378cf4b17c8ae3375dd6b782f3f2b",
    ),
    PinnedInput(
        "Bloodmoon.esm",
        "bsa/Bloodmoon.esm",
        9_631_798,
        "bd27090d0e6ad4c1bf1abc83f1a2dac56fcc82cae7bfe8263c413fb301801357",
    ),
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _input_identity() -> list[dict[str, object]]:
    return [
        {
            "name": source.name,
            "relativePath": source.relative_path,
            "bytes": source.bytes,
            "sha256": source.sha256,
        }
        for source in PINNED_INPUTS
    ]


INPUT_FINGERPRINT = hashlib.sha256(
    _canonical_json_bytes(_input_identity())
).hexdigest()
# Shared with the isolated Original renderer profile. Its fingerprint is derived
# from the complete pinned base-game input set (the three ESMs and three BSAs),
# while this catalog loader deliberately opens only the ESM subset.
SNAPSHOT_ID = "original:goty:8b2690c0ce1c954e"

IMPLEMENTATION_FILES = (
    Path("tools/tes3/records.py"),
    Path("tools/catalog_pipeline/tes3.py"),
    Path("tools/catalog_pipeline/catalog.py"),
    Path("tools/catalog_pipeline/original.py"),
)
EXPECTED_WORLD_COUNTS = {
    "rawCellRecords": 2935,
    "effectiveCells": 2887,
    "effectiveInteriorCells": 1328,
    "effectiveExteriorCells": 1559,
    "rawDoorRecords": 322,
    "effectiveDoors": 267,
    "doorOverrides": 55,
    "rawReferenceVersions": 357692,
    "effectiveReferences": 357692,
    "rawTeleportReferenceVersions": 3619,
    "effectiveTeleportReferences": 3619,
    "effectiveExteriorTeleportReferences": 1205,
    "rawLandRecords": 1540,
    "effectiveLand": 1540,
    "cellDeletions": 0,
    "doorDeletions": 0,
    "referenceDeletions": 0,
    "landDeletions": 0,
    "ignoredRecords": 0,
}
EXPECTED_CATALOG_COUNTS = {
    "places": 1036,
    "interiorPlaces": 940,
    "namedExteriorCells": 126,
    "namedExteriorPlaces": 96,
    "entrances": 1205,
    "multiEntrancePlaces": 141,
    "entrancesInMultiEntrancePlaces": 406,
    "maximumEntrancesPerPlace": 14,
    "aliases": 0,
    "byRegion": {"solstheim": 92, "vvardenfell": 944},
    "byType": {
        "ancestral-tomb": 88,
        "cave": 118,
        "dwemer-ruin": 28,
        "guild": 8,
        "house": 256,
        "landmark": 36,
        "mine": 40,
        "other": 261,
        "settlement": 31,
        "ship": 50,
        "shop": 43,
        "shrine": 43,
        "stronghold": 24,
        "temple": 10,
    },
}
EXPECTED_RESOLUTION_COUNTS = {
    "effectiveReferencesScanned": 357692,
    "exteriorReferences": 156778,
    "exteriorTeleports": 1205,
    "namedTeleportCandidates": 1205,
    "resolvedDoorBases": 1205,
    "resolvedDestinationCells": 1205,
    "catalogEntrances": 1205,
}
EXPECTED_REGION_COUNTS = {
    "entrancesByRegion": {"solstheim": 97, "vvardenfell": 1108},
    "interiorPlacesByRegion": {"solstheim": 79, "vvardenfell": 861},
    "namedExteriorPlacesByRegion": {"solstheim": 13, "vvardenfell": 83},
}
EXPECTED_EXCLUSIONS = {
    "automaticTestNameFiltering": False,
    "explicitDenylistEntries": 0,
    "unreachableInteriorCells": 388,
}


@dataclass(frozen=True, slots=True)
class ValidatedCatalog:
    root: Path
    audit: dict[str, Any]
    inventory_sha256: str
    locations_bytes: bytes
    english_bytes: bytes
    audit_bytes: bytes


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
    source_root = source_root.resolve()
    if source_root != DEFAULT_SOURCE_ROOT:
        raise ValueError(
            "Original GOTY source root is pinned to "
            f"{DEFAULT_SOURCE_ROOT}; refusing alternate content path {source_root}"
        )
    expected_data_root = (source_root / "bsa").resolve()
    plugins: list[PluginInput] = []
    for source in PINNED_INPUTS:
        path = source_root / source.relative_path
        if path.is_symlink() or path.parent.resolve() != expected_data_root:
            raise ValueError(f"Pinned Original input path is not a regular bsa file: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"Required Original catalog input is missing: {path}")
        actual_bytes = path.stat().st_size
        if actual_bytes != source.bytes:
            raise ValueError(
                f"Original input size mismatch for {source.relative_path}: "
                f"expected {source.bytes}, got {actual_bytes}"
            )
        actual_sha256 = _sha256_file(path)
        if actual_sha256 != source.sha256:
            raise ValueError(
                f"Original input hash mismatch for {source.relative_path}: "
                f"expected {source.sha256}, got {actual_sha256}"
            )
        plugins.append(PluginInput(source.name, path, actual_sha256))
    return tuple(plugins)


def _input_audit(
    plugins: tuple[PluginInput, ...], source_root: Path
) -> list[dict[str, object]]:
    return [
        {
            "loadOrder": load_order,
            "name": plugin.name,
            "relativePath": plugin.path.relative_to(source_root).as_posix(),
            "bytes": plugin.path.stat().st_size,
            "sha256": plugin.sha256,
        }
        for load_order, plugin in enumerate(plugins)
    ]


def _implementation_audit(repo_root: Path) -> dict[str, object]:
    files = []
    for relative in IMPLEMENTATION_FILES:
        payload = (repo_root / relative).read_bytes()
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
    for place in locations["places"]:  # type: ignore[index]
        count = len(place["entrances"])
        if count:
            histogram[count] += 1
    return {str(key): histogram[key] for key in sorted(histogram)}


def _catalog_artifact_metrics(
    locations: Mapping[str, object], english: Mapping[str, object]
) -> dict[str, object]:
    entrance_regions: Counter[str] = Counter()
    interior_regions: Counter[str] = Counter()
    exterior_regions: Counter[str] = Counter()
    place_regions: Counter[str] = Counter()
    place_types: Counter[str] = Counter()
    exterior_names: defaultdict[str, list[str]] = defaultdict(list)
    entrances_total = 0
    multi_entrance_places = 0
    entrances_in_multi = 0
    maximum_entrances = 0
    named_exterior_cells = 0
    aliases = 0
    inside_extent = True
    min_x, min_y, max_x, max_y = MAP_EXTENT
    places = locations["places"]  # type: ignore[index]
    localized = english["places"]  # type: ignore[index]
    for place, locale in zip(places, localized, strict=True):
        positions = [place["mapPosition"]]
        positions.extend(entrance["coordinate"] for entrance in place["entrances"])
        if any(
            not (
                min_x <= float(position[0]) <= max_x
                and min_y <= float(position[1]) <= max_y
            )
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
        entrance_regions[place["regionId"]] += entrance_count
        if not entrances:
            exterior_regions[place["regionId"]] += 1
            named_exterior_cells += len(place["sources"])
            exterior_names[str(locale["name"])].append(str(place["id"]))
        elif entrance_count > 1:
            interior_regions[place["regionId"]] += 1
            multi_entrance_places += 1
            entrances_in_multi += entrance_count
        else:
            interior_regions[place["regionId"]] += 1
    split_names = [
        {"name": name, "placeIds": sorted(place_ids)}
        for name, place_ids in sorted(exterior_names.items())
        if len(place_ids) > 1
    ]
    return {
        "places": len(places),
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
        "splitExteriorNames": split_names,
        "allCoordinatesWithinManifestExtent": inside_extent,
    }


def _require_expected_counts(
    actual: Mapping[str, object], expected: Mapping[str, object], label: str
) -> None:
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Pinned Original {label} counts changed: {mismatches}")


def build_original_catalog(
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
    if build.dropped:
        raise ValueError(f"Original catalog has unresolved/dropped destinations: {build.dropped}")
    if not (
        build.resolution.get("namedTeleportCandidates")
        == build.resolution.get("resolvedDoorBases")
        == build.resolution.get("resolvedDestinationCells")
        == build.resolution.get("catalogEntrances")
        == 1205
    ):
        raise ValueError("Original catalog does not resolve every candidate destination")

    diagnostics = _catalog_artifact_metrics(build.locations, build.english)
    if not diagnostics["allCoordinatesWithinManifestExtent"]:
        raise ValueError("Catalog coordinate falls outside the Original manifest extent")
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
    inputs = _input_audit(plugins, source_root)
    implementation = _implementation_audit(repo_root)
    inventory = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "inputFingerprint": INPUT_FINGERPRINT,
        "inputs": inputs,
        "implementationSha256": implementation["sha256"],
        "policyFingerprint": build.policy_fingerprint,
        "artifacts": artifacts,
    }
    inventory_sha256 = _sha256_bytes(_canonical_json_bytes(inventory))
    exclusions = {
        "unreachableInteriorCells": world.counts["effectiveInteriorCells"]
        - build.counts["interiorPlaces"],
        "explicitDenylistEntries": 0,
        "automaticTestNameFiltering": False,
    }
    if exclusions != EXPECTED_EXCLUSIONS:
        raise ValueError(f"Original catalog exclusions changed: {exclusions}")
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
        "exclusions": exclusions,
        "integrity": {
            **build.gates,
            "exactPinnedInputSet": True,
            "zeroUnresolvedDestinations": True,
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
    _atomic_write(output_root / "locations.json", locations_bytes)
    _atomic_write(output_root / "locales/en.json", english_bytes)
    _atomic_write(output_root / "catalog-audit.json", _json_file_bytes(audit))
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
            raise ValueError(f"{label} dataset identity does not match Original GOTY HD")
    if english.get("locale") != "en":
        raise ValueError("Original locale artifact must be English")
    if audit.get("auditVersion") != AUDIT_VERSION or audit.get("passes") is not True:
        raise ValueError("Original catalog audit is not a passing supported audit")
    if audit.get("policyFingerprint") != _sha256_bytes(
        _canonical_json_bytes(audit.get("policy"))
    ):
        raise ValueError("Catalog policy fingerprint does not match its payload")
    audit_core = {key: value for key, value in audit.items() if key != "auditSha256"}
    if audit.get("auditSha256") != _sha256_bytes(_canonical_json_bytes(audit_core)):
        raise ValueError("Catalog audit logical SHA-256 does not match its payload")
    inventory = audit.get("inventory")
    extractor = audit.get("extractor")
    if not isinstance(inventory, dict) or not isinstance(extractor, dict):
        raise ValueError("Catalog inventory/extractor identity is missing")
    current_extractor = _implementation_audit(REPO_ROOT)
    if extractor != current_extractor:
        raise ValueError("Original catalog extractor identity is stale")
    if (
        inventory.get("datasetId") != DATASET_ID
        or inventory.get("snapshotId") != SNAPSHOT_ID
        or inventory.get("inputFingerprint") != INPUT_FINGERPRINT
        or inventory.get("inputs") != audit.get("inputs")
        or inventory.get("implementationSha256") != extractor.get("sha256")
        or inventory.get("policyFingerprint") != audit.get("policyFingerprint")
    ):
        raise ValueError("Original catalog inventory bindings are inconsistent")
    inventory_sha256 = _sha256_bytes(_canonical_json_bytes(inventory))
    if audit.get("catalogInventorySha256") != inventory_sha256:
        raise ValueError("Catalog inventory SHA-256 does not match its payload")
    actual_artifacts = {
        "locations": _artifact(locations_bytes, "locations.json"),
        "english": _artifact(english_bytes, "locales/en.json"),
    }
    if inventory.get("artifacts") != actual_artifacts:
        raise ValueError("Catalog artifacts do not match the inventory")
    location_ids = [place["id"] for place in locations.get("places", [])]
    locale_ids = [place["placeId"] for place in english.get("places", [])]
    if location_ids != locale_ids:
        raise ValueError("Locations and English locale IDs/order differ")
    inputs = audit.get("inputs")
    expected_inputs = [
        {"loadOrder": index, **descriptor}
        for index, descriptor in enumerate(_input_identity())
    ]
    if inputs != expected_inputs:
        raise ValueError("Original catalog input set/load order is not exactly pinned")
    semantic_gates = validate_catalog_bundle(
        locations,
        english,
        known_plugins={canonical_ref_id(source.name) for source in PINNED_INPUTS},
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
    if not isinstance(records, dict) or not isinstance(resolution, dict):
        raise ValueError("Catalog record/resolution audit is malformed")
    _require_expected_counts(records, EXPECTED_WORLD_COUNTS, "published world")
    _require_expected_counts(resolution, EXPECTED_RESOLUTION_COUNTS, "published resolution")
    if audit.get("exclusions") != EXPECTED_EXCLUSIONS:
        raise ValueError("Catalog exclusion audit does not match the pinned policy")
    integrity = audit.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("artifacts") != actual_artifacts:
        raise ValueError("Catalog integrity audit is malformed")
    required_integrity_gates = {
        *semantic_gates,
        "exactPinnedInputSet",
        "zeroUnresolvedDestinations",
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
        root,
        audit,
        inventory_sha256,
        locations_bytes,
        english_bytes,
        audit_bytes,
    )


def _publish_tree(
    target: Path, artifacts: Mapping[Path, bytes], *, boundary: Path
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
    parser = argparse.ArgumentParser(description="Build and publish the isolated Original GOTY EN catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_build = repo_root / "local-data/catalog-production" / DATASET_ID
    build = subparsers.add_parser("build")
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
    args = _parser(REPO_ROOT).parse_args(argv)
    if args.command == "build":
        result = build_original_catalog(
            source_root=DEFAULT_SOURCE_ROOT,
            output_root=args.output,
            repo_root=REPO_ROOT,
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
