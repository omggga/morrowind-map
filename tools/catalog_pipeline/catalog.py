from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Mapping

from tools.catalog_pipeline.tes3 import (
    CELL_SIZE,
    CellKey,
    EffectiveCell,
    EffectiveWorld,
    ReferenceVersion,
    canonical_ref_id,
)


PLACE_ID_POLICY_VERSION = "tes3-place-id-v1"
ENTRANCE_ID_POLICY_VERSION = "tes3-entrance-id-v1"
GROUPING_POLICY_VERSION = "tes3-cell-and-exterior-8-neighbor-v1"
CLASSIFICATION_POLICY_VERSION = "tes3-place-type-v2"
REGION_POLICY_VERSION = "tes3-effective-land-source-v1"
ALIAS_POLICY_VERSION = "tes3-effective-spellings-v1"
CELL_DELETE_POLICY_VERSION = "tes3-cell-tombstone-v1"
KNOWN_REGIONS = ("vvardenfell", "solstheim", "tr-mainland", "cyrodiil", "skyrim", "azurian-isles")
PLACE_TYPES = {
    "settlement",
    "guild",
    "temple",
    "cave",
    "mine",
    "ship",
    "shrine",
    "ancestral-tomb",
    "stronghold",
    "dwemer-ruin",
    "house",
    "shop",
    "landmark",
    "other",
}
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[.:-][a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class CatalogBuild:
    locations: dict[str, object]
    english: dict[str, object]
    counts: dict[str, object]
    dropped: dict[str, int]
    resolution: dict[str, int]
    gates: dict[str, bool]
    policy: dict[str, object]
    policy_fingerprint: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalized_plugin_regions(plugin_regions: Mapping[str, str]) -> dict[str, str]:
    normalized = {
        canonical_ref_id(plugin): region for plugin, region in plugin_regions.items()
    }
    if len(normalized) != len(plugin_regions):
        raise ValueError("Plugin region mapping contains ASCII-case duplicate keys")
    unknown = sorted(set(normalized.values()) - set(KNOWN_REGIONS))
    if unknown:
        raise ValueError(f"Plugin region mapping contains unknown regions: {unknown}")
    return dict(sorted(normalized.items()))


def policy_descriptor(plugin_regions: Mapping[str, str]) -> dict[str, object]:
    return {
        "placeId": PLACE_ID_POLICY_VERSION,
        "entranceId": ENTRANCE_ID_POLICY_VERSION,
        "grouping": GROUPING_POLICY_VERSION,
        "classification": CLASSIFICATION_POLICY_VERSION,
        "region": REGION_POLICY_VERSION,
        "aliases": ALIAS_POLICY_VERSION,
        "cellDelete": CELL_DELETE_POLICY_VERSION,
        "cellSize": CELL_SIZE,
        "regions": list(KNOWN_REGIONS[:3]) + [region for region in KNOWN_REGIONS[3:] if region in plugin_regions.values()],
        "pluginRegions": _normalized_plugin_regions(plugin_regions),
    }


def policy_fingerprint(plugin_regions: Mapping[str, str]) -> str:
    return hashlib.sha256(_canonical_bytes(policy_descriptor(plugin_regions))).hexdigest()


def _digest(parts: Iterable[object]) -> str:
    return hashlib.sha256(_canonical_bytes(list(parts))).hexdigest()[:20]


def place_id(dataset_id: str, kind: str, identity: str) -> str:
    digest = _digest((PLACE_ID_POLICY_VERSION, kind, identity))
    return f"{dataset_id}.place-{digest}"


def entrance_id(dataset_id: str, origin_plugin: str, local_index: int) -> str:
    digest = _digest(
        (ENTRANCE_ID_POLICY_VERSION, canonical_ref_id(origin_plugin), local_index)
    )
    return f"{dataset_id}.entrance-{digest}"


def _region_for_grid(
    world: EffectiveWorld,
    grid: tuple[int, int],
    plugin_regions: Mapping[str, str],
) -> str:
    land_plugin = world.land_sources.get(grid)
    if land_plugin is None:
        raise ValueError(f"Catalog exterior cell {grid} has no effective LAND record")
    region = plugin_regions.get(canonical_ref_id(land_plugin))
    if region is None:
        raise ValueError(
            f"Effective LAND source {land_plugin!r} for exterior cell {grid} "
            "has no region mapping"
        )
    return region


def _region_for_reference(
    world: EffectiveWorld,
    reference: ReferenceVersion,
    plugin_regions: Mapping[str, str],
) -> str:
    grid = reference.effective_cell.grid
    if grid is None:
        raise ValueError(f"Catalog entrance {reference.key} is not in an exterior cell")
    return _region_for_grid(world, grid, plugin_regions)


def _aliases(name: str, historical_names: Iterable[str] = ()) -> list[str]:
    candidates = sorted(
        {" ".join(value.split()) for value in historical_names if value.strip()},
        key=lambda value: (canonical_ref_id(value), value),
    )

    result: dict[str, str] = {}
    primary = canonical_ref_id(name.strip())
    for candidate in candidates:
        folded = canonical_ref_id(candidate)
        if folded == primary:
            continue
        result.setdefault(folded, candidate)
    return [result[key] for key in sorted(result)]


_INTERIOR_NAME_RULES = (
    (re.compile(r"\b(?:ancestral tomb|family tomb)\b"), "ancestral-tomb"),
    (re.compile(r"\bmine\b"), "mine"),
    (re.compile(r"\b(?:cave|cavern|caverns|grotto)\b"), "cave"),
    (re.compile(r"\b(?:shrine|sanctuary)\b"), "shrine"),
    (re.compile(r"\b(?:temple|chapel|oratory|monastery)\b"), "temple"),
    (re.compile(r"\bguild(?:hall)?\b"), "guild"),
    (re.compile(r"\b(?:ship|shipwreck|vessel)\b"), "ship"),
    (re.compile(r"\b(?:fort|fortress|stronghold|citadel|castle|keep)\b"), "stronghold"),
    (
        re.compile(
            r"\b(?:shop|trader|smith|weaponsmith|armorer|outfitter|apothecary|"
            r"alchemist|bookseller|clothier|pawnbroker|tavern|inn|general supplies|"
            r"general merchandise)\b"
        ),
        "shop",
    ),
    (
        re.compile(
            r"\b(?:house|home|hut|shack|manor|estate|residence|villa|tent|yurt|"
            r"quarters|housing|apartment)\b"
        ),
        "house",
    ),
    (re.compile(r"\b(?:dwemer|dwarven)\b"), "dwemer-ruin"),
)
_CIVIC_SUFFIX = re.compile(
    r"\b(?:house|home|hut|shack|manor|estate|residence|villa|tent|yurt|quarters|"
    r"housing|apartment|shop|trader|smith|weaponsmith|armorer|outfitter|apothecary|"
    r"alchemist|bookseller|clothier|pawnbroker|tavern|inn|tradehouse|guild|temple)\b"
)
_DWEMER_BASE = re.compile(r"(?:^|_)(?:dwrv|dwe)(?:_|$)")
_EXTERIOR_NAME_RULES = (
    (re.compile(r"\b(?:ancestral tomb|family tomb|barrow)\b"), "ancestral-tomb"),
    (re.compile(r"\b(?:mine|mineshaft|quarry|excavations?)\b"), "mine"),
    (re.compile(r"\b(?:cave|cavern|caverns|grotto)\b"), "cave"),
    (re.compile(r"\b(?:shrine|sanctuary|altar)\b"), "shrine"),
    (re.compile(r"\b(?:temple|chapel|oratory|monastery)\b"), "temple"),
    (re.compile(r"\b(?:dwemer|dwarven)\b"), "dwemer-ruin"),
    (re.compile(r"\b(?:fort|fortress|stronghold|citadel|castle|keep|outpost)\b"), "stronghold"),
    (re.compile(r"\b(?:camp|plantation|farm|village|town|city|port)\b"), "settlement"),
)


def _classify_interior(
    name: str,
    base_ids: Iterable[str],
    civic_exterior_prefixes: set[str],
) -> tuple[str, str]:
    normalized_name = canonical_ref_id(name)
    for pattern, place_type in _INTERIOR_NAME_RULES:
        if pattern.search(normalized_name):
            return place_type, f"name:{place_type}"
    normalized_bases = tuple(canonical_ref_id(base_id) for base_id in base_ids)
    if any("ship_" in base_id or "_ship" in base_id for base_id in normalized_bases):
        return "ship", "base:ship-door"
    if any("cave" in base_id or "cavern" in base_id for base_id in normalized_bases):
        return "cave", "base:cave-door"
    prefix, separator, _ = normalized_name.partition(",")
    civic_prefix = bool(separator and prefix in civic_exterior_prefixes)
    if not civic_prefix and any(_DWEMER_BASE.search(base_id) for base_id in normalized_bases):
        return "dwemer-ruin", "base:dwemer-door"
    return "other", "fallback:other"


def classify_place(name: str, base_ids: Iterable[str] = (), *, exterior: bool = False) -> str:
    if exterior:
        normalized_name = canonical_ref_id(name)
        for pattern, place_type in _EXTERIOR_NAME_RULES:
            if pattern.search(normalized_name):
                return place_type
        return "landmark"
    return _classify_interior(name, base_ids, set())[0]


def _related_to_exterior(exterior_name: str, interior_name: str) -> bool:
    prefix_to_remove = "solstheim, "
    if exterior_name.startswith(prefix_to_remove):
        exterior_name = exterior_name[len(prefix_to_remove) :]
    if interior_name.startswith(prefix_to_remove):
        interior_name = interior_name[len(prefix_to_remove) :]
    prefixes = {exterior_name}
    for suffix in (" ruin", " ruins", " entrance", " excavation", " excavations"):
        if exterior_name.endswith(suffix):
            prefixes.add(exterior_name[: -len(suffix)])
    related_suffixes = ("monastery", "temple", "cave", "cavern", "grotto", "mine", "tomb")
    return any(
        interior_name == prefix
        or interior_name.startswith(f"{prefix},")
        or interior_name.startswith(f"{prefix}:")
        or interior_name in {f"{prefix} {suffix}" for suffix in related_suffixes}
        for prefix in prefixes
        if prefix
    )


def _classify_exterior(
    name: str,
    region: str,
    interior_evidence: Iterable[tuple[str, str, str]],
    civic_exterior_prefixes: set[str],
) -> tuple[str, str]:
    normalized_name = canonical_ref_id(name)
    for pattern, place_type in _EXTERIOR_NAME_RULES:
        if pattern.search(normalized_name):
            return place_type, f"name:{place_type}"
    if normalized_name in civic_exterior_prefixes:
        return "settlement", "evidence:civic-interior"
    related_types = [
        place_type
        for interior_name, interior_region, place_type in interior_evidence
        if interior_region == region and _related_to_exterior(normalized_name, interior_name)
    ]
    if any(place_type in {"house", "shop", "guild"} for place_type in related_types):
        return "settlement", "evidence:civic-interior"
    specialized = [place_type for place_type in related_types if place_type != "other"]
    distinct = set(specialized)
    if len(distinct) == 1:
        place_type = next(iter(distinct))
        if place_type == "cave" and len(specialized) * 2 < len(related_types):
            return "landmark", "fallback:landmark"
        return place_type, f"evidence:related-{place_type}"
    return "landmark", "fallback:landmark"


def _minimum_zoom(place_type: str, *, exterior: bool) -> int:
    if exterior or place_type == "settlement":
        return 2
    if place_type in {"landmark", "stronghold", "dwemer-ruin"}:
        return 3
    return 4


def _rounded_position(position: tuple[float, float, float] | tuple[float, float]) -> list[float]:
    return [round(float(position[0]), 3), round(float(position[1]), 3)]


def _coordinate_cell(position: list[float]) -> list[int]:
    return [math.floor(position[0] / CELL_SIZE), math.floor(position[1] / CELL_SIZE)]


def _entrance_payload(dataset_id: str, reference: ReferenceVersion) -> dict[str, object]:
    if reference.position is None:
        raise ValueError("Cannot publish an entrance without DATA position")
    coordinate = _rounded_position(reference.position)
    return {
        "id": entrance_id(dataset_id, reference.origin_plugin, reference.key.local_index),
        "coordinate": coordinate,
        "exteriorCell": _coordinate_cell(coordinate),
        "sourcePlugin": reference.origin_plugin,
        "sourceRef": f"0x{reference.key.local_index:08x}",
    }


def _entrance_medoid(entrances: list[dict[str, object]]) -> dict[str, object]:
    def distance_sum(candidate: dict[str, object]) -> tuple[float, str]:
        x, y = candidate["coordinate"]
        total = 0.0
        for other in entrances:
            ox, oy = other["coordinate"]
            total += math.hypot(float(x) - float(ox), float(y) - float(oy))
        return total, str(candidate["id"])

    return min(entrances, key=distance_sum)


def _connected_components(cells: Iterable[EffectiveCell]) -> list[list[EffectiveCell]]:
    by_grid = {cell.grid: cell for cell in cells if cell.grid is not None}
    result: list[list[EffectiveCell]] = []
    while by_grid:
        start = min(by_grid)
        queue = deque([start])
        component: list[EffectiveCell] = []
        while queue:
            grid = queue.popleft()
            cell = by_grid.pop(grid, None)
            if cell is None:
                continue
            component.append(cell)
            x, y = grid
            queue.extend(
                (x + dx, y + dy)
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                if dx or dy
            )
        component.sort(key=lambda cell: cell.grid or (0, 0))
        result.append(component)
    return result


def _exact_keys(value: object, expected: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{label} fields do not match the catalog contract")
    return value


def _point(value: object, *, integer: bool, label: str) -> list[float] | list[int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be a two-coordinate array")
    if integer:
        if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
            raise ValueError(f"{label} must contain integers")
    elif any(
        not isinstance(item, (int, float))
        or isinstance(item, bool)
        or not math.isfinite(float(item))
        for item in value
    ):
        raise ValueError(f"{label} must contain finite numbers")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) > 160 or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is not a valid identifier")
    return value


def validate_catalog_bundle(
    locations: Mapping[str, object],
    english: Mapping[str, object],
    *,
    known_plugins: set[str],
) -> dict[str, bool]:
    _exact_keys(locations, {"schemaVersion", "datasetId", "snapshotId", "places"}, "Locations")
    _exact_keys(
        english,
        {"schemaVersion", "datasetId", "snapshotId", "locale", "places"},
        "English locale",
    )
    if locations["schemaVersion"] != 1 or english["schemaVersion"] != 1:
        raise ValueError("Catalog schemaVersion must be 1")
    dataset_id = _identifier(locations["datasetId"], "Locations datasetId")
    if (
        english["datasetId"] != dataset_id
        or english["snapshotId"] != locations["snapshotId"]
        or english["locale"] != "en"
    ):
        raise ValueError("Locations and English locale identities differ")
    if not isinstance(locations["snapshotId"], str) or not locations["snapshotId"]:
        raise ValueError("Catalog snapshotId must be a non-empty string")
    places = locations.get("places")
    localized = english.get("places")
    if not isinstance(places, list) or not isinstance(localized, list):
        raise ValueError("Catalog places must be arrays")
    place_ids = [str(place["id"]) for place in places]
    locale_ids = [str(place["placeId"]) for place in localized]
    entrance_ids = [
        str(entrance["id"])
        for place in places
        for entrance in place["entrances"]
    ]
    if len(place_ids) != len(set(place_ids)):
        raise ValueError("Place IDs are not globally unique")
    if len(entrance_ids) != len(set(entrance_ids)):
        raise ValueError("Entrance IDs are not globally unique")
    if place_ids != sorted(place_ids):
        raise ValueError("Places are not deterministically sorted by ID")
    if locale_ids != place_ids:
        raise ValueError("English locale coverage/order does not exactly match locations")
    for place, locale in zip(places, localized, strict=True):
        _exact_keys(
            place,
            {
                "id",
                "regionId",
                "type",
                "mapPosition",
                "exteriorCell",
                "mimCategory",
                "minZoom",
                "entrances",
                "sources",
            },
            "Place",
        )
        _exact_keys(locale, {"placeId", "name", "aliases"}, "Localized place")
        _identifier(place["id"], "Place id")
        if not str(place["id"]).startswith(f"{dataset_id}."):
            raise ValueError(f"Place ID is not dataset-scoped: {place['id']}")
        if place["type"] not in PLACE_TYPES:
            raise ValueError(f"Unknown place type: {place['type']}")
        map_position = _point(place["mapPosition"], integer=False, label="Place mapPosition")
        exterior_cell = _point(place["exteriorCell"], integer=True, label="Place exteriorCell")
        if _coordinate_cell(map_position) != exterior_cell:
            raise ValueError(f"Place coordinate/cell mismatch: {place['id']}")
        if (
            not isinstance(place["minZoom"], (int, float))
            or isinstance(place["minZoom"], bool)
            or not 0 <= float(place["minZoom"]) <= 20
        ):
            raise ValueError(f"Invalid place minZoom: {place['id']}")
        if place["mimCategory"] is not None and (
            not isinstance(place["mimCategory"], int)
            or isinstance(place["mimCategory"], bool)
            or place["mimCategory"] < 0
        ):
            raise ValueError(f"Invalid place mimCategory: {place['id']}")
        if place["regionId"] not in KNOWN_REGIONS:
            raise ValueError(f"Unknown place region: {place['regionId']}")
        if locale["placeId"] != place["id"]:
            raise ValueError(f"Localized Place ID mismatch: {place['id']}")
        if not isinstance(locale["name"], str) or not locale["name"].strip():
            raise ValueError(f"Blank English place name: {place['id']}")
        aliases = locale["aliases"]
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ValueError(f"Invalid aliases: {place['id']}")
        folded_aliases = [str(alias).strip().casefold() for alias in aliases]
        if any(not alias for alias in folded_aliases) or len(folded_aliases) != len(
            set(folded_aliases)
        ):
            raise ValueError(f"Blank or duplicate alias: {place['id']}")
        if str(locale["name"]).strip().casefold() in folded_aliases:
            raise ValueError(f"Primary name repeated as alias: {place['id']}")
        if not isinstance(place["sources"], list) or not place["sources"]:
            raise ValueError(f"Place has no sources: {place['id']}")
        for source in place["sources"]:
            _exact_keys(source, {"kind", "plugin", "recordId", "mimIndex"}, "Place source")
            if not isinstance(source["plugin"], str) or not source["plugin"]:
                raise ValueError(f"Invalid source plugin: {place['id']}")
            if canonical_ref_id(str(source["plugin"])) not in known_plugins:
                raise ValueError(f"Unknown source plugin: {source['plugin']}")
            if (
                source["kind"] != "esm"
                or not isinstance(source["recordId"], str)
                or not source["recordId"]
                or source["mimIndex"] is not None
            ):
                raise ValueError(f"Invalid ESM source tuple: {place['id']}")
        if not isinstance(place["entrances"], list):
            raise ValueError(f"Invalid entrance list: {place['id']}")
        for entrance in place["entrances"]:
            _exact_keys(
                entrance,
                {"id", "coordinate", "exteriorCell", "sourcePlugin", "sourceRef"},
                "Entrance",
            )
            _identifier(entrance["id"], "Entrance id")
            if not str(entrance["id"]).startswith(f"{dataset_id}."):
                raise ValueError(f"Entrance ID is not dataset-scoped: {entrance['id']}")
            if (
                not isinstance(entrance["sourcePlugin"], str)
                or not entrance["sourcePlugin"]
                or not isinstance(entrance["sourceRef"], str)
                or not entrance["sourceRef"]
            ):
                raise ValueError(f"Invalid entrance provenance: {entrance['id']}")
            if canonical_ref_id(str(entrance["sourcePlugin"])) not in known_plugins:
                raise ValueError(f"Unknown entrance plugin: {entrance['sourcePlugin']}")
            coordinate = _point(entrance["coordinate"], integer=False, label="Entrance coordinate")
            entrance_cell = _point(
                entrance["exteriorCell"], integer=True, label="Entrance exteriorCell"
            )
            if _coordinate_cell(coordinate) != entrance_cell:
                raise ValueError(f"Entrance coordinate/cell mismatch: {entrance['id']}")
    return {
        "uniquePlaceIds": True,
        "uniqueEntranceIds": True,
        "exactEnglishCoverage": True,
        "coordinateCellConsistency": True,
        "knownRegions": True,
        "knownPlugins": True,
        "sourceKindConsistency": True,
        "deterministicOrdering": True,
        "normalizedAliases": True,
    }


def build_catalog(
    world: EffectiveWorld,
    *,
    dataset_id: str,
    snapshot_id: str,
    plugin_regions: Mapping[str, str],
    allowed_regions: tuple[str, ...] | None = None,
) -> CatalogBuild:
    normalized_plugin_regions = _normalized_plugin_regions(plugin_regions)
    descriptor = policy_descriptor(normalized_plugin_regions)
    descriptor_fingerprint = policy_fingerprint(normalized_plugin_regions)
    if allowed_regions is not None:
        if not allowed_regions or set(allowed_regions) - set(normalized_plugin_regions.values()):
            raise ValueError("Catalog scope must contain known plugin regions")
        descriptor["allowedRegions"] = sorted(allowed_regions)
        descriptor_fingerprint = hashlib.sha256(_canonical_bytes(descriptor)).hexdigest()
    dropped: Counter[str] = Counter()
    resolution: Counter[str] = Counter()
    entrance_groups: dict[CellKey, list[ReferenceVersion]] = defaultdict(list)
    destination_spellings: dict[CellKey, set[str]] = defaultdict(set)

    for reference in world.references.values():
        resolution["effectiveReferencesScanned"] += 1
        if reference.deleted:
            dropped["deletedReference"] += 1
            continue
        if reference.effective_cell.kind != "exterior":
            continue
        resolution["exteriorReferences"] += 1
        if reference.door_destination is None:
            continue
        resolution["exteriorTeleports"] += 1
        if not reference.destination_cell:
            dropped["exteriorDestinationPolicy"] += 1
            resolution["exteriorToExteriorTeleports"] += 1
            continue
        resolution["namedTeleportCandidates"] += 1
        if not reference.base_id:
            dropped["missingBaseId"] += 1
            continue
        if canonical_ref_id(reference.base_id) not in world.doors:
            dropped["unresolvedOrNonDoorBase"] += 1
            continue
        resolution["resolvedDoorBases"] += 1
        destination_key = CellKey.interior(reference.destination_cell)
        destination = world.cells.get(destination_key)
        if destination is None or not destination.is_interior:
            dropped["unresolvedInteriorDestination"] += 1
            continue
        resolution["resolvedDestinationCells"] += 1
        if reference.position is None or not all(math.isfinite(value) for value in reference.position):
            dropped["missingOrNonFinitePosition"] += 1
            continue
        containing_grid = reference.effective_cell.grid
        if containing_grid is None or reference.exterior_cell != containing_grid:
            dropped["positionOutsideEffectiveCell"] += 1
            continue
        if allowed_regions is not None and (
            containing_grid not in world.land_sources
            or _region_for_reference(world, reference, normalized_plugin_regions) not in allowed_regions
        ):
            dropped["outsideMapScope"] += 1
            continue
        entrance_groups[destination_key].append(reference)
        destination_spellings[destination_key].add(reference.destination_cell)
        resolution["catalogEntrances"] += 1

    actionable = (
        "missingBaseId",
        "unresolvedOrNonDoorBase",
        "unresolvedInteriorDestination",
        "missingOrNonFinitePosition",
        "positionOutsideEffectiveCell",
    )
    failures = {key: dropped[key] for key in actionable if dropped[key]}
    if failures:
        raise ValueError(f"Actionable catalog reference failures: {failures}")

    place_rows: list[tuple[dict[str, object], dict[str, object]]] = []
    region_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    type_rule_counts: Counter[str] = Counter()
    named_exterior_cells = {
        canonical_ref_id(cell.name)
        for cell in world.cells.values()
        if not cell.is_interior and cell.name.strip()
    }
    civic_exterior_prefixes: set[str] = set()
    for destination_key in entrance_groups:
        normalized_name = canonical_ref_id(world.cells[destination_key].name)
        prefix, separator, suffix = normalized_name.partition(",")
        if separator and prefix in named_exterior_cells and _CIVIC_SUFFIX.search(suffix):
            civic_exterior_prefixes.add(prefix)
    interior_evidence: list[tuple[str, str, str]] = []

    for destination_key, references in entrance_groups.items():
        destination = world.cells[destination_key]
        regions = {
            _region_for_reference(world, reference, normalized_plugin_regions)
            for reference in references
        }
        if len(regions) != 1:
            raise ValueError(
                f"Destination {destination.name!r} has unresolved/cross-region entrances: {regions}"
            )
        region = next(iter(regions))
        assert region is not None
        pid = place_id(dataset_id, "interior", destination_key.identity)
        entrances = sorted(
            (_entrance_payload(dataset_id, reference) for reference in references),
            key=lambda value: str(value["id"]),
        )
        primary = _entrance_medoid(entrances)
        base_ids = sorted(
            {reference.base_id for reference in references}, key=canonical_ref_id
        )
        place_type, type_rule = _classify_interior(
            destination.name,
            base_ids,
            civic_exterior_prefixes,
        )
        aliases = _aliases(
            destination.name,
            (*destination.historical_names, *destination_spellings[destination_key]),
        )
        place_rows.append(
            (
                {
                    "id": pid,
                    "regionId": region,
                    "type": place_type,
                    "mapPosition": list(primary["coordinate"]),
                    "exteriorCell": list(primary["exteriorCell"]),
                    "mimCategory": None,
                    "minZoom": _minimum_zoom(place_type, exterior=False),
                    "entrances": entrances,
                    "sources": [
                        {
                            "kind": "esm",
                            "plugin": destination.plugin,
                            "recordId": destination.name,
                            "mimIndex": None,
                        }
                    ],
                },
                {"placeId": pid, "name": destination.name.strip(), "aliases": aliases},
            )
        )
        region_counts[region] += 1
        type_counts[place_type] += 1
        type_rule_counts[type_rule] += 1
        interior_evidence.append(
            (canonical_ref_id(destination.name), region, place_type)
        )

    exterior_buckets: dict[str, list[EffectiveCell]] = defaultdict(list)
    for cell in world.cells.values():
        if cell.is_interior or not cell.name.strip():
            continue
        if allowed_regions is not None and (
            cell.grid not in world.land_sources
            or _region_for_grid(world, cell.grid, normalized_plugin_regions) not in allowed_regions
        ):
            continue
        exterior_buckets[canonical_ref_id(cell.name)].append(cell)

    exterior_components = 0
    for name_key, cells in sorted(exterior_buckets.items()):
        for component in _connected_components(cells):
            exterior_components += 1
            component_regions = {
                _region_for_grid(world, cell.grid, normalized_plugin_regions)
                for cell in component
                if cell.grid is not None
            }
            if len(component_regions) != 1:
                grids = [cell.grid for cell in component]
                raise ValueError(
                    f"Named exterior component {name_key!r} has no or mixed LAND regions "
                    f"{component_regions}: {grids}"
                )
            region = next(iter(component_regions))
            anchor = component[0].grid
            assert anchor is not None
            identity = f"{name_key}\0{anchor[0]},{anchor[1]}"
            pid = place_id(dataset_id, "exterior", identity)
            mean_x = sum((cell.grid or (0, 0))[0] for cell in component) / len(component)
            mean_y = sum((cell.grid or (0, 0))[1] for cell in component) / len(component)
            representative = min(
                component,
                key=lambda cell: (
                    math.hypot((cell.grid or (0, 0))[0] - mean_x, (cell.grid or (0, 0))[1] - mean_y),
                    cell.grid or (0, 0),
                ),
            )
            grid = representative.grid
            assert grid is not None
            position = [grid[0] * CELL_SIZE + CELL_SIZE / 2, grid[1] * CELL_SIZE + CELL_SIZE / 2]
            name = component[-1].name.strip()
            place_type, type_rule = _classify_exterior(
                name,
                region,
                interior_evidence,
                civic_exterior_prefixes,
            )
            historical = {historical for cell in component for historical in cell.historical_names}
            sources = [
                {
                    "kind": "esm",
                    "plugin": cell.plugin,
                    "recordId": f"CELL exterior {cell.grid[0]},{cell.grid[1]}",
                    "mimIndex": None,
                }
                for cell in component
                if cell.grid is not None
            ]
            sources.sort(
                key=lambda value: (
                    canonical_ref_id(str(value["plugin"])),
                    str(value["recordId"]),
                )
            )
            place_rows.append(
                (
                    {
                        "id": pid,
                        "regionId": region,
                        "type": place_type,
                        "mapPosition": position,
                        "exteriorCell": list(grid),
                        "mimCategory": None,
                        "minZoom": _minimum_zoom(place_type, exterior=True),
                        "entrances": [],
                        "sources": sources,
                    },
                    {"placeId": pid, "name": name, "aliases": _aliases(name, historical)},
                )
            )
            region_counts[region] += 1
            type_counts[place_type] += 1
            type_rule_counts[type_rule] += 1

    place_rows.sort(key=lambda row: str(row[0]["id"]))
    locations = {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "snapshotId": snapshot_id,
        "places": [row[0] for row in place_rows],
    }
    english = {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "snapshotId": snapshot_id,
        "locale": "en",
        "places": [row[1] for row in place_rows],
    }
    gates = validate_catalog_bundle(
        locations,
        english,
        known_plugins={canonical_ref_id(plugin.name) for plugin in world.plugins},
    )
    gates["allActionableReferencesResolved"] = not failures
    gates["exactCellGrouping"] = True
    gates["effectiveLandRegionResolution"] = True
    gates["singleRegionPerPlace"] = True

    entrance_count = sum(len(row[0]["entrances"]) for row in place_rows)
    aliases_count = sum(len(row[1]["aliases"]) for row in place_rows)
    multi_entrance = sum(len(row[0]["entrances"]) > 1 for row in place_rows)
    entrances_in_multi = sum(
        len(row[0]["entrances"])
        for row in place_rows
        if len(row[0]["entrances"]) > 1
    )
    counts = {
        "places": len(place_rows),
        "interiorPlaces": len(entrance_groups),
        "namedExteriorCells": sum(len(cells) for cells in exterior_buckets.values()),
        "namedExteriorPlaces": exterior_components,
        "entrances": entrance_count,
        "multiEntrancePlaces": multi_entrance,
        "entrancesInMultiEntrancePlaces": entrances_in_multi,
        "maximumEntrancesPerPlace": max(
            (len(row[0]["entrances"]) for row in place_rows), default=0
        ),
        "aliases": aliases_count,
        "byRegion": dict(sorted(region_counts.items())),
        "byType": dict(sorted(type_counts.items())),
        "byTypeRule": dict(sorted(type_rule_counts.items())),
    }
    return CatalogBuild(
        locations=locations,
        english=english,
        counts=counts,
        dropped=dict(sorted(dropped.items())),
        resolution=dict(sorted(resolution.items())),
        gates=gates,
        policy=descriptor,
        policy_fingerprint=descriptor_fingerprint,
    )
