from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Mapping

from tools.data_pipeline.esm import TeleportReference, extract_world_data
from tools.data_pipeline.mim import (
    MimLocation,
    MimMarker,
    classify_place,
    match_mim_progress,
    parse_mim_locations,
    parse_mim_markers,
    parse_mim_progress,
)


DATASET_ID = "original-goty"
SNAPSHOT_ID = "original:goty:332684d75ed7e331"
EXPECTED_ESM_HASHES = {
    "Morrowind.esm": "5c3c8c2cbd20e25901b59b3ece33d36b7ef0e3d60ad8d11828bcc61a5ead1647",
    "Tribunal.esm": "2ace511f23cc2a9ddd5f3aa59c7919789b9378cf4b17c8ae3375dd6b782f3f2b",
    "Bloodmoon.esm": "bd27090d0e6ad4c1bf1abc83f1a2dac56fcc82cae7bfe8263c413fb301801357",
}
EXPECTED_MIM_LAYOUT_HASHES = {
    "vvardenfell": "80fb8673ddf5866bb72ddf5d2f9097fbd2558f56a158b1d1624f32503c9c1758",
    "solstheim": "40a1df5a268821e6a4250017943ceee3fa95ccea632a15296789c1d90225d5ba",
}
MIM_EXTENT = (-125_000.0, -130_000.0, 175_000.0, 220_000.0)
SOLSTHEIM_MIM_AXIS_SCALE = (0.349764187732, 0.347160285692)
SOLSTHEIM_MIM_AXIS_OFFSET = (-185_826.803992, 161_123.190917)
SOLSTHEIM_RASTER_EXTENT = (-229_376.0, 114_688.0, -131_072.0, 237_568.0)
MIM_IMPORT_MAPPING_VERSION = "mim-progress-v2"
MANUAL_NAMES: dict[tuple[str, int], dict[str, str]] = {
    ("solstheim", 15): {"ru": "Логово Удирфрюкта"},
    ("solstheim", 19): {"en": "Beast Stone"},
    ("solstheim", 22): {"en": "Sun Stone"},
    ("solstheim", 31): {"en": "Tree Stone"},
    ("solstheim", 40): {"en": "Earth Stone"},
    ("solstheim", 44): {"ru": "Дозор Тормура"},
    ("solstheim", 45): {"en": "Water Stone"},
    ("solstheim", 49): {"en": "Altar of Thrond"},
    ("solstheim", 50): {"en": "Wind Stone"},
    ("solstheim", 62): {"en": "Airship Wreckage"},
}


@dataclass(frozen=True)
class Candidate:
    english: str
    russian: str
    refs: tuple[TeleportReference, ...]


@dataclass(frozen=True)
class ResolvedName:
    english: str
    source: str
    candidate: Candidate | None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_mim_layout(
    region_id: str,
    path: Path,
    expected_hashes: Mapping[str, str] = EXPECTED_MIM_LAYOUT_HASHES,
) -> None:
    expected_hash = expected_hashes.get(region_id)
    if expected_hash is None:
        raise ValueError(f"No pinned MIM layout SHA-256 for {region_id!r}")
    actual_hash = sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(
            f"Unexpected MIM {region_id} layout SHA-256: {actual_hash}; "
            f"expected {expected_hash}. Bump snapshot/mapping and provide a migration."
        )


def canonical_position(region_id: str, position: tuple[float, float]) -> tuple[float, float]:
    if region_id == "vvardenfell":
        return position
    if region_id != "solstheim":
        raise ValueError(f"Unknown Original region {region_id!r}")
    x, y = position
    return (
        x * SOLSTHEIM_MIM_AXIS_SCALE[0] + SOLSTHEIM_MIM_AXIS_OFFSET[0],
        y * SOLSTHEIM_MIM_AXIS_SCALE[1] + SOLSTHEIM_MIM_AXIS_OFFSET[1],
    )


def canonical_solstheim_extent() -> tuple[float, float, float, float]:
    return SOLSTHEIM_RASTER_EXTENT


def mim_marker_id(region_id: str, marker: MimMarker, identical_occurrence: int) -> str:
    identity = "\0".join(
        (
            MIM_IMPORT_MAPPING_VERSION,
            region_id,
            marker.text,
            f"{marker.position[0]},{marker.position[1]}",
            str(identical_occurrence),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{DATASET_ID}.custom.mim-{region_id}-{digest}"


def build_mim_import_region(
    region_id: str,
    locations: list[MimLocation],
    user_path: Path,
    markers_path: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    matches = match_mim_progress(
        region_id,
        locations,
        parse_mim_progress(user_path),
    )
    progress = [
        {
            "placeId": f"{DATASET_ID}.{region_id}.mim-{location.index:04d}",
            "status": record.status,
            "note": record.note,
        }
        for location, record in matches
    ]

    markers = []
    marker_occurrences: Counter[tuple[str, tuple[int, int]]] = Counter()
    for marker in parse_mim_markers(markers_path):
        identity = (marker.text, marker.position)
        identical_occurrence = marker_occurrences[identity]
        marker_occurrences[identity] += 1
        x, y = canonical_position(region_id, marker.position)
        markers.append(
            {
                "id": mim_marker_id(region_id, marker, identical_occurrence),
                "label": marker.text,
                "note": "",
                "position": [round(x, 3), round(y, 3)],
            }
        )

    status_counts = Counter(str(entry["status"]) for entry in progress)
    audit = {
        "progress": len(progress),
        "statuses": {
            status: status_counts.get(status, 0)
            for status in ("unvisited", "active", "visited")
        },
        "notes": sum(bool(str(entry["note"])) for entry in progress),
        "customMarkers": len(markers),
    }
    return progress, markers, audit


def mim_source_fingerprint(
    source_files: list[dict[str, str]],
    mapping_version: str = MIM_IMPORT_MAPPING_VERSION,
) -> str:
    fingerprint_input = {
        "mappingVersion": mapping_version,
        "sourceFiles": sorted(source_files, key=lambda entry: entry["path"]),
    }
    canonical = json.dumps(
        fingerprint_input,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def normalize(value: str) -> str:
    return "".join(
        character
        for character in value.casefold().replace("ё", "е")
        if character.isalnum()
    )


def contains_cyrillic(value: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", value))


def load_translations(data_files: Path, stem: str) -> tuple[dict[str, list[str]], dict[str, str]]:
    by_russian: dict[str, list[str]] = defaultdict(list)
    by_english: dict[str, str] = {}
    for extension in ("cel", "mrk", "top"):
        path = data_files / f"{stem}.{extension}"
        for line in path.read_text(encoding="cp1251").splitlines():
            if "\t" not in line:
                continue
            english, russian = (part.strip() for part in line.split("\t", 1))
            if not english or not russian:
                continue
            if contains_cyrillic(english):
                continue
            by_russian[normalize(russian)].append(english)
            by_english.setdefault(english, russian)
    return dict(by_russian), by_english


def build_candidates(
    refs: Iterable[TeleportReference], by_english: dict[str, str]
) -> list[Candidate]:
    grouped: dict[str, list[TeleportReference]] = defaultdict(list)
    for ref in refs:
        folded = ref.destination.casefold()
        if "test" in folded or "todd" in folded:
            continue
        grouped[ref.destination].append(ref)
    return [
        Candidate(
            english=english,
            russian=by_english.get(english, english),
            refs=tuple(sorted(group, key=lambda ref: (ref.reference_id, ref.coordinate))),
        )
        for english, group in sorted(grouped.items())
    ]


def distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def resolve_english_name(
    location: MimLocation,
    position: tuple[float, float],
    by_russian: dict[str, list[str]],
    candidates: list[Candidate],
) -> ResolvedName:
    exact = by_russian.get(normalize(location.name), [])
    if exact:
        english = sorted(set(exact), key=lambda value: (value.count(","), len(value), value))[0]
        candidate = next((item for item in candidates if item.english == english), None)
        return ResolvedName(english, "translation", candidate)
    if not contains_cyrillic(location.name):
        candidate = next((item for item in candidates if item.english == location.name), None)
        return ResolvedName(location.name, "mim-en", candidate)

    ranked: list[tuple[float, float, Candidate]] = []
    normalized_name = normalize(location.name)
    for candidate in candidates:
        nearest = min(distance(position, ref.coordinate) for ref in candidate.refs)
        if nearest > 12_000:
            continue
        similarity = SequenceMatcher(None, normalized_name, normalize(candidate.russian)).ratio()
        proximity = max(0.0, 1 - nearest / 12_000)
        ranked.append((similarity * 0.78 + proximity * 0.22, nearest, candidate))

    if ranked:
        score, nearest, candidate = max(ranked, key=lambda value: (value[0], -value[1]))
        if nearest <= 128 or score >= 0.46:
            return ResolvedName(candidate.english, "esm-nearest", candidate)
    return ResolvedName(location.name, "ru-fallback", None)


def entrance_payload(place_id: str, candidate: Candidate | None) -> list[dict[str, object]]:
    if candidate is None:
        return []
    return [
        {
            "id": f"{place_id}.entry-{ref.reference_id:08x}",
            "coordinate": [round(ref.coordinate[0], 3), round(ref.coordinate[1], 3)],
            "exteriorCell": list(ref.exterior_cell),
            "sourcePlugin": ref.plugin,
            "sourceRef": f"0x{ref.reference_id:08x}",
        }
        for ref in candidate.refs
    ]


def build_mim_places(
    region_id: str,
    locations: list[MimLocation],
    by_russian: dict[str, list[str]],
    candidates: list[Candidate],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], set[str]]:
    places: list[dict[str, object]] = []
    english_names: list[dict[str, object]] = []
    russian_names: list[dict[str, object]] = []
    matched_candidates: set[str] = set()

    for location in locations:
        place_id = f"{DATASET_ID}.{region_id}.mim-{location.index:04d}"
        mim_position = canonical_position(region_id, location.position)
        manual_names = MANUAL_NAMES.get((region_id, location.index), {})
        resolved = resolve_english_name(location, mim_position, by_russian, candidates)
        if "en" in manual_names:
            resolved = ResolvedName(manual_names["en"], "manual", resolved.candidate)
        if resolved.candidate is not None:
            matched_candidates.add(resolved.candidate.english)
        # MIM points were manually placed for presentation. When the matched ESM
        # destination exists, publish its nearest exterior door as the canonical
        # location; retain the calibrated MIM transform only for MIM-only places.
        position = (
            min(
                (ref.coordinate for ref in resolved.candidate.refs),
                key=lambda coordinate: distance(mim_position, coordinate),
            )
            if resolved.candidate is not None
            else mim_position
        )
        cell = [math.floor(position[0] / 8192), math.floor(position[1] / 8192)]
        places.append(
            {
                "id": place_id,
                "regionId": region_id,
                "type": classify_place(location.category, resolved.english),
                "mapPosition": [round(position[0], 3), round(position[1], 3)],
                "exteriorCell": cell,
                "mimCategory": location.category,
                "minZoom": location.detail_level,
                "entrances": entrance_payload(place_id, resolved.candidate),
                "sources": [
                    {
                        "kind": "mim",
                        "plugin": "mwmain.gdb",
                        "recordId": None,
                        "mimIndex": location.index,
                    }
                ],
            }
        )
        english_names.append(
            {"placeId": place_id, "name": resolved.english, "aliases": []}
        )
        russian_names.append(
            {
                "placeId": place_id,
                "name": manual_names.get("ru", location.name),
                "aliases": [],
            }
        )

    return places, english_names, russian_names, matched_candidates


def supplement_esm_places(
    region_id: str,
    candidates: list[Candidate],
    matched_candidates: set[str],
    existing_positions: list[tuple[float, float]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    places: list[dict[str, object]] = []
    english_names: list[dict[str, object]] = []
    russian_names: list[dict[str, object]] = []

    for candidate in candidates:
        if candidate.english in matched_candidates:
            continue
        position = candidate.refs[0].coordinate
        if any(distance(position, existing) <= 96 for existing in existing_positions):
            continue
        digest = hashlib.sha1(
            f"{candidate.refs[0].plugin}\0{candidate.english}".encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()[:12]
        place_id = f"{DATASET_ID}.{region_id}.esm-{digest}"
        places.append(
            {
                "id": place_id,
                "regionId": region_id,
                "type": classify_place(None, candidate.english),
                "mapPosition": [round(position[0], 3), round(position[1], 3)],
                "exteriorCell": list(candidate.refs[0].exterior_cell),
                "mimCategory": None,
                "minZoom": 4,
                "entrances": entrance_payload(place_id, candidate),
                "sources": [
                    {
                        "kind": "esm",
                        "plugin": candidate.refs[0].plugin,
                        "recordId": candidate.english,
                        "mimIndex": None,
                    }
                ],
            }
        )
        english_names.append(
            {"placeId": place_id, "name": candidate.english, "aliases": []}
        )
        russian_names.append(
            {"placeId": place_id, "name": candidate.russian, "aliases": []}
        )

    return places, english_names, russian_names


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def artifact_summary(path: Path, public_root: Path) -> dict[str, object]:
    relative = path.relative_to(public_root).as_posix()
    return {
        "url": f"/datasets/generated/original-goty/{relative}",
        "mediaType": "application/json",
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def build(source_root: Path, output_root: Path) -> dict[str, object]:
    bsa_root = source_root / "bsa"
    data_files = source_root / "game" / "Data Files"
    maps_root = source_root / "Maps"

    for filename, expected_hash in EXPECTED_ESM_HASHES.items():
        actual_hash = sha256(bsa_root / filename)
        if actual_hash != expected_hash:
            raise ValueError(f"Unexpected {filename} SHA-256: {actual_hash}")

    region_inputs = (
        (
            "vvardenfell",
            maps_root / "mim_morrowind" / "mwmain.gdb",
            maps_root / "mim_morrowind" / "bigmap_hi.jpg",
            bsa_root / "Morrowind.esm",
            "morrowind",
        ),
        (
            "solstheim",
            maps_root / "mim_bloodmoon" / "mwmain.gdb",
            maps_root / "mim_bloodmoon" / "bigmap_hi.jpg",
            bsa_root / "Bloodmoon.esm",
            "bloodmoon",
        ),
    )

    all_places: list[dict[str, object]] = []
    all_english: list[dict[str, object]] = []
    all_russian: list[dict[str, object]] = []
    all_progress: list[dict[str, object]] = []
    all_custom_markers: list[dict[str, object]] = []
    mim_source_files: list[dict[str, str]] = []
    mim_import_regions: dict[str, object] = {}
    audit_regions: dict[str, object] = {}
    raster_specs: list[dict[str, object]] = []

    for region_id, mim_path, raster_path, esm_path, translation_stem in region_inputs:
        assert_mim_layout(region_id, mim_path)
        locations = parse_mim_locations(mim_path)
        region_progress, region_markers, progress_audit = build_mim_import_region(
            region_id,
            locations,
            mim_path.parent / "user.gdb",
            mim_path.parent / "markers.gdb",
        )
        all_progress.extend(region_progress)
        all_custom_markers.extend(region_markers)
        mim_import_regions[region_id] = progress_audit
        for filename in ("mwmain.gdb", "user.gdb", "markers.gdb"):
            source_path = mim_path.parent / filename
            mim_source_files.append(
                {
                    "path": source_path.relative_to(maps_root).as_posix(),
                    "sha256": sha256(source_path),
                }
            )
        by_russian, by_english = load_translations(data_files, translation_stem)
        candidates = build_candidates(extract_world_data(esm_path).teleports, by_english)
        places, english, russian, matched = build_mim_places(
            region_id, locations, by_russian, candidates
        )
        extras, extra_english, extra_russian = supplement_esm_places(
            region_id,
            candidates,
            matched,
            [tuple(place["mapPosition"]) for place in places],
        )
        all_places.extend(places + extras)
        all_english.extend(english + extra_english)
        all_russian.extend(russian + extra_russian)

        unresolved = [entry for entry in english if contains_cyrillic(str(entry["name"]))]
        if unresolved:
            unresolved_ids = ", ".join(str(entry["placeId"]) for entry in unresolved)
            raise ValueError(f"Unresolved English names in {region_id}: {unresolved_ids}")
        audit_regions[region_id] = {
            "mimPlaces": len(places),
            "esmSupplementPlaces": len(extras),
            "unresolvedEnglish": len(unresolved),
            "unresolvedPlaceIds": [entry["placeId"] for entry in unresolved],
        }

        copied_raster = output_root / "rasters" / f"{region_id}.jpg"
        copied_raster.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raster_path, copied_raster)
        extent = MIM_EXTENT if region_id == "vvardenfell" else canonical_solstheim_extent()
        pixel_size = [3300, 3800] if region_id == "vvardenfell" else [3072, 3840]
        raster_specs.append(
            {
                "id": f"{DATASET_ID}.{region_id}",
                "regionId": region_id,
                "kind": "static-image",
                "imageUrl": f"/datasets/generated/original-goty/rasters/{region_id}.jpg",
                "mediaType": "image/jpeg",
                "pixelSize": pixel_size,
                "extent": [round(value, 3) for value in extent],
                "sha256": sha256(copied_raster),
            }
        )

    combined = sorted(
        zip(all_places, all_english, all_russian, strict=True),
        key=lambda values: str(values[0]["id"]),
    )
    all_places = [values[0] for values in combined]
    all_english = [values[1] for values in combined]
    all_russian = [values[2] for values in combined]
    all_progress.sort(key=lambda entry: str(entry["placeId"]))
    all_custom_markers.sort(key=lambda entry: str(entry["id"]))
    mim_source_files.sort(key=lambda entry: entry["path"])
    source_fingerprint = mim_source_fingerprint(mim_source_files)

    locations_path = output_root / "locations.json"
    english_path = output_root / "locales" / "en.json"
    russian_path = output_root / "locales" / "ru.json"
    assets_path = output_root / "map-assets.json"
    mim_import_path = output_root / "mim-import.json"
    write_json(
        locations_path,
        {
            "schemaVersion": 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "places": all_places,
        },
    )
    write_json(
        english_path,
        {
            "schemaVersion": 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "locale": "en",
            "places": all_english,
        },
    )
    write_json(
        russian_path,
        {
            "schemaVersion": 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "locale": "ru",
            "places": all_russian,
        },
    )
    write_json(
        assets_path,
        {
            "schemaVersion": 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "projection": "TES3:WORLD",
            "rasters": raster_specs,
        },
    )
    write_json(
        mim_import_path,
        {
            "schemaVersion": 1,
            "kind": "mim-progress",
            "targetDatasetId": DATASET_ID,
            "targetSnapshotId": SNAPSHOT_ID,
            "sourceFingerprint": source_fingerprint,
            "sourceFiles": mim_source_files,
            "progress": all_progress,
            "customMarkers": all_custom_markers,
        },
    )
    aggregate_statuses = {
        status: sum(
            int(region["statuses"][status])
            for region in mim_import_regions.values()
        )
        for status in ("unvisited", "active", "visited")
    }
    audit = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "places": len(all_places),
        "regions": audit_regions,
        "mimImport": {
            "mappingVersion": MIM_IMPORT_MAPPING_VERSION,
            "sourceFingerprint": source_fingerprint,
            "sourceFiles": len(mim_source_files),
            "progress": len(all_progress),
            "statuses": aggregate_statuses,
            "notes": sum(
                int(region["notes"]) for region in mim_import_regions.values()
            ),
            "customMarkers": len(all_custom_markers),
            "regions": mim_import_regions,
        },
        "artifacts": {
            "locations": artifact_summary(locations_path, output_root),
            "en": artifact_summary(english_path, output_root),
            "ru": artifact_summary(russian_path, output_root),
            "mapAssets": artifact_summary(assets_path, output_root),
            "mimImport": artifact_summary(mim_import_path, output_root),
        },
    }
    write_json(output_root / "audit.json", audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Original GOTY local dataset")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("../morr-dev"),
        help="Path containing bsa, game and Maps",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("apps/web/public/datasets/generated/original-goty"),
    )
    arguments = parser.parse_args()
    audit = build(arguments.source_root.resolve(), arguments.output_root.resolve())
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
