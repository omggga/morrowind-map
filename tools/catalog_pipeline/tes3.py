from __future__ import annotations

import math
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from tools.tes3.records import Record, iter_records, iter_subrecords


CELL_INTERIOR = 0x01
CELL_SIZE = 8192
RECORD_FLAG_IGNORED = 0x1000
_ASCII_LOWER_TRANSLATION = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
)


def canonical_ref_id(value: str) -> str:
    """Match TES3/OpenMW ASCII-only case-insensitive record identity."""

    return value.translate(_ASCII_LOWER_TRANSLATION)


@dataclass(frozen=True, slots=True)
class PluginInput:
    name: str
    path: Path
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class MasterDependency:
    name: str
    advertised_size: int | None
    resolved_plugin_index: int


@dataclass(frozen=True, slots=True, order=True)
class CellKey:
    kind: str
    identity: str

    @classmethod
    def interior(cls, name: str) -> "CellKey":
        return cls("interior", canonical_ref_id(name))

    @classmethod
    def exterior(cls, x: int, y: int) -> "CellKey":
        return cls("exterior", f"{x},{y}")

    @property
    def grid(self) -> tuple[int, int] | None:
        if self.kind != "exterior":
            return None
        x, y = self.identity.split(",", 1)
        return int(x), int(y)


@dataclass(frozen=True, slots=True, order=True)
class ReferenceKey:
    origin_plugin_index: int
    local_index: int


@dataclass(frozen=True, slots=True)
class DoorRecord:
    record_id: str
    name: str
    plugin: str
    plugin_index: int
    offset: int


@dataclass(frozen=True, slots=True)
class ReferenceVersion:
    key: ReferenceKey
    raw_index: int
    origin_plugin: str
    winning_plugin: str
    winning_plugin_index: int
    source_cell: CellKey
    effective_cell: CellKey
    base_id: str
    position: tuple[float, float, float] | None
    door_destination: tuple[float, float, float] | None
    destination_cell: str
    deleted: bool
    moved: bool
    sequence: tuple[int, int, int]

    @property
    def exterior_cell(self) -> tuple[int, int] | None:
        if self.position is None:
            return None
        return (
            math.floor(self.position[0] / CELL_SIZE),
            math.floor(self.position[1] / CELL_SIZE),
        )


@dataclass(frozen=True, slots=True)
class CellContext:
    plugin: str
    plugin_index: int
    record_index: int
    references: tuple[ReferenceVersion, ...]


@dataclass(slots=True)
class EffectiveCell:
    key: CellKey
    name: str
    region: str
    plugin: str
    plugin_index: int
    first_plugin: str
    first_plugin_index: int
    offset: int
    contexts: list[CellContext] = field(default_factory=list)
    historical_names: set[str] = field(default_factory=set)

    @property
    def is_interior(self) -> bool:
        return self.key.kind == "interior"

    @property
    def grid(self) -> tuple[int, int] | None:
        return self.key.grid


@dataclass(frozen=True, slots=True)
class EffectiveWorld:
    plugins: tuple[PluginInput, ...]
    masters: tuple[tuple[MasterDependency, ...], ...]
    cells: dict[CellKey, EffectiveCell]
    doors: dict[str, DoorRecord]
    references: dict[ReferenceKey, ReferenceVersion]
    land_sources: dict[tuple[int, int], str]
    region_sources: dict[str, str]
    counts: dict[str, object]


@dataclass(frozen=True, slots=True)
class _ParsedCell:
    key: CellKey
    name: str
    region: str | None
    deleted: bool
    references: tuple[ReferenceVersion, ...]


def _decoded(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("cp1252", errors="strict")


def _deleted(subrecords: Iterable[object]) -> bool:
    return any(getattr(value, "subrecord_type", None) == b"DELE" for value in subrecords)


def _masters(record: Record) -> tuple[tuple[str, int | None], ...]:
    result: list[tuple[str, int | None]] = []
    pending_name: str | None = None
    for subrecord in iter_subrecords(record.payload):
        if subrecord.subrecord_type == b"MAST":
            if pending_name is not None:
                result.append((pending_name, None))
            pending_name = _decoded(subrecord.payload)
        elif subrecord.subrecord_type == b"DATA" and pending_name is not None:
            advertised_size = (
                struct.unpack_from("<Q", subrecord.payload)[0]
                if len(subrecord.payload) >= 8
                else None
            )
            result.append((pending_name, advertised_size))
            pending_name = None
    if pending_name is not None:
        result.append((pending_name, None))
    return tuple(result)


def _adjust_reference(
    raw_index: int,
    *,
    plugin_index: int,
    parent_indices: tuple[int, ...],
) -> ReferenceKey:
    parent_ordinal = (raw_index >> 24) & 0xFF
    if parent_ordinal and parent_ordinal <= len(parent_indices):
        return ReferenceKey(parent_indices[parent_ordinal - 1], raw_index & 0x00FF_FFFF)
    return ReferenceKey(plugin_index, raw_index)


def _parse_door(record: Record, *, plugin: str, plugin_index: int) -> tuple[str, DoorRecord | None]:
    record_id = ""
    name = ""
    subrecords = tuple(iter_subrecords(record.payload))
    for subrecord in subrecords:
        if subrecord.subrecord_type == b"NAME":
            record_id = _decoded(subrecord.payload)
        elif subrecord.subrecord_type == b"FNAM":
            name = _decoded(subrecord.payload)
    if not record_id:
        raise ValueError(f"DOOR without NAME at offset {record.offset} in {plugin}")
    key = canonical_ref_id(record_id)
    if _deleted(subrecords):
        return key, None
    return key, DoorRecord(record_id, name, plugin, plugin_index, record.offset)


def _reference_version(
    subrecords: tuple[object, ...],
    start: int,
    end: int,
    *,
    plugin: str,
    plugin_index: int,
    parent_indices: tuple[int, ...],
    source_cell: CellKey,
    moved_target: CellKey | None,
    record_index: int,
    reference_index: int,
) -> ReferenceVersion:
    first = subrecords[start]
    raw_index = struct.unpack_from("<I", first.payload)[0]
    key = _adjust_reference(
        raw_index,
        plugin_index=plugin_index,
        parent_indices=parent_indices,
    )
    base_id = ""
    position: tuple[float, float, float] | None = None
    door_destination: tuple[float, float, float] | None = None
    destination_cell = ""
    deleted = False
    for subrecord in subrecords[start + 1 : end]:
        if subrecord.subrecord_type == b"NAME":
            base_id = _decoded(subrecord.payload)
        elif subrecord.subrecord_type == b"DATA" and len(subrecord.payload) >= 24:
            position = struct.unpack_from("<3f", subrecord.payload)
        elif subrecord.subrecord_type == b"DODT" and len(subrecord.payload) >= 24:
            door_destination = struct.unpack_from("<3f", subrecord.payload)
        elif subrecord.subrecord_type == b"DNAM":
            destination_cell = _decoded(subrecord.payload)
        elif subrecord.subrecord_type == b"DELE":
            deleted = True
    return ReferenceVersion(
        key=key,
        raw_index=raw_index,
        origin_plugin="",
        winning_plugin=plugin,
        winning_plugin_index=plugin_index,
        source_cell=source_cell,
        effective_cell=moved_target or source_cell,
        base_id=base_id,
        position=position,
        door_destination=door_destination,
        destination_cell=destination_cell,
        deleted=deleted,
        moved=moved_target is not None,
        sequence=(plugin_index, record_index, reference_index),
    )


def _parse_cell(
    record: Record,
    *,
    plugin: str,
    plugin_index: int,
    parent_indices: tuple[int, ...],
    record_index: int,
) -> _ParsedCell:
    subrecords = tuple(iter_subrecords(record.payload))
    name = ""
    region: str | None = None
    flags: int | None = None
    grid = (0, 0)
    references_start = len(subrecords)
    for index, subrecord in enumerate(subrecords):
        if subrecord.subrecord_type in (b"FRMR", b"MVRF"):
            references_start = index
            break
        if subrecord.subrecord_type == b"NAME":
            name = _decoded(subrecord.payload)
        elif subrecord.subrecord_type == b"DATA" and len(subrecord.payload) >= 12:
            flags, x, y = struct.unpack_from("<Iii", subrecord.payload)
            grid = (x, y)
        elif subrecord.subrecord_type == b"RGNN":
            region = _decoded(subrecord.payload)
    if flags is None:
        raise ValueError(f"CELL without DATA at offset {record.offset} in {plugin}")
    key = CellKey.interior(name) if flags & CELL_INTERIOR else CellKey.exterior(*grid)
    deleted = _deleted(subrecords[:references_start])

    references: list[ReferenceVersion] = []
    index = references_start
    reference_index = 0
    while index < len(subrecords):
        marker = subrecords[index]
        moved_target: CellKey | None = None
        moved_raw: int | None = None
        if marker.subrecord_type == b"MVRF":
            if len(marker.payload) < 4:
                raise ValueError(f"Short MVRF at offset {record.offset} in {plugin}")
            moved_raw = struct.unpack_from("<I", marker.payload)[0]
            index += 1
            if index >= len(subrecords) or subrecords[index].subrecord_type != b"CNDT":
                raise ValueError(f"MVRF without CNDT at offset {record.offset} in {plugin}")
            target_payload = subrecords[index].payload
            if len(target_payload) < 8:
                raise ValueError(f"Short CNDT at offset {record.offset} in {plugin}")
            moved_target = CellKey.exterior(*struct.unpack_from("<ii", target_payload))
            index += 1
        if index >= len(subrecords) or subrecords[index].subrecord_type != b"FRMR":
            index += 1
            continue
        end = index + 1
        while end < len(subrecords) and subrecords[end].subrecord_type not in (b"FRMR", b"MVRF"):
            end += 1
        reference = _reference_version(
            subrecords,
            index,
            end,
            plugin=plugin,
            plugin_index=plugin_index,
            parent_indices=parent_indices,
            source_cell=key,
            moved_target=moved_target,
            record_index=record_index,
            reference_index=reference_index,
        )
        if moved_raw is not None:
            moved_key = _adjust_reference(
                moved_raw,
                plugin_index=plugin_index,
                parent_indices=parent_indices,
            )
            if moved_key != reference.key:
                raise ValueError(
                    f"MVRF/FRMR identity mismatch at offset {record.offset} in {plugin}"
                )
        references.append(reference)
        reference_index += 1
        index = end
    return _ParsedCell(key, name, region, deleted, tuple(references))


def _parse_land(record: Record) -> tuple[tuple[int, int] | None, bool]:
    grid: tuple[int, int] | None = None
    subrecords = tuple(iter_subrecords(record.payload))
    for subrecord in subrecords:
        if subrecord.subrecord_type == b"INTV" and len(subrecord.payload) >= 8:
            grid = struct.unpack_from("<ii", subrecord.payload)
            break
    return grid, _deleted(subrecords)


def merge_plugins(plugins: Iterable[PluginInput]) -> EffectiveWorld:
    ordered = tuple(plugins)
    if not ordered:
        raise ValueError("TES3 load order cannot be empty")
    names: dict[str, int] = {}
    for index, plugin in enumerate(ordered):
        folded = canonical_ref_id(plugin.name)
        if folded in names:
            raise ValueError(f"Duplicate content file in load order: {plugin.name}")
        if canonical_ref_id(plugin.path.name) != folded:
            raise ValueError(f"Plugin name/path mismatch: {plugin.name} != {plugin.path.name}")
        names[folded] = index

    cells: dict[CellKey, EffectiveCell] = {}
    doors: dict[str, DoorRecord] = {}
    land_sources: dict[tuple[int, int], str] = {}
    region_sources: dict[str, str] = {}
    plugin_masters: list[tuple[MasterDependency, ...]] = []
    counters: Counter[str] = Counter()
    records_by_plugin: dict[str, Counter[str]] = {}

    for plugin_index, plugin in enumerate(ordered):
        record_iterator = iter_records(plugin.path)
        try:
            header = next(record_iterator)
        except StopIteration as error:
            raise ValueError(f"Empty TES3 content file: {plugin.path}") from error
        if header.record_type != b"TES3":
            raise ValueError(f"First record is not TES3 in {plugin.path}")
        raw_masters = _masters(header)
        parent_indices: list[int] = []
        masters: list[MasterDependency] = []
        for master, advertised_size in raw_masters:
            parent = names.get(canonical_ref_id(master))
            if parent is None or parent >= plugin_index:
                raise ValueError(
                    f"{plugin.name} master {master!r} is missing from its earlier load order"
                )
            parent_indices.append(parent)
            masters.append(MasterDependency(master, advertised_size, parent))
        plugin_masters.append(tuple(masters))

        per_plugin: Counter[str] = Counter({"TES3": 1})
        for record_index, record in enumerate(record_iterator, start=1):
            record_type = record.record_type.decode("ascii", errors="backslashreplace")
            per_plugin[record_type] += 1
            counters["sourceRecords"] += 1
            if record.flags & RECORD_FLAG_IGNORED:
                counters["ignoredRecords"] += 1
                continue
            if record.record_type == b"DOOR":
                counters["rawDoorRecords"] += 1
                key, door = _parse_door(record, plugin=plugin.name, plugin_index=plugin_index)
                if key in doors:
                    counters["doorOverrides"] += 1
                if door is None:
                    counters["doorDeletions"] += 1
                    doors.pop(key, None)
                else:
                    doors[key] = door
            elif record.record_type == b"LAND":
                counters["rawLandRecords"] += 1
                grid, deleted = _parse_land(record)
                if grid is not None:
                    if deleted:
                        land_sources.pop(grid, None)
                        counters["landDeletions"] += 1
                    else:
                        if grid in land_sources:
                            counters["landOverrides"] += 1
                        land_sources[grid] = plugin.name
            elif record.record_type == b"REGN":
                counters["rawRegionRecords"] += 1
                subrecords = tuple(iter_subrecords(record.payload))
                region_id = next(
                    (
                        _decoded(subrecord.payload)
                        for subrecord in subrecords
                        if subrecord.subrecord_type == b"NAME"
                    ),
                    "",
                )
                if not region_id:
                    raise ValueError(
                        f"REGN without NAME at offset {record.offset} in {plugin.name}"
                    )
                key = canonical_ref_id(region_id)
                if key in region_sources:
                    counters["regionOverrides"] += 1
                if _deleted(subrecords):
                    counters["regionDeletions"] += 1
                    region_sources.pop(key, None)
                else:
                    region_sources[key] = plugin.name
            elif record.record_type == b"CELL":
                counters["rawCellRecords"] += 1
                parsed = _parse_cell(
                    record,
                    plugin=plugin.name,
                    plugin_index=plugin_index,
                    parent_indices=tuple(parent_indices),
                    record_index=record_index,
                )
                counters["rawReferenceVersions"] += len(parsed.references)
                counters["rawTeleportReferenceVersions"] += sum(
                    reference.door_destination is not None
                    for reference in parsed.references
                )
                existing = cells.get(parsed.key)
                if parsed.deleted:
                    counters["cellDeletions"] += 1
                    cells.pop(parsed.key, None)
                    continue
                context = CellContext(plugin.name, plugin_index, record_index, parsed.references)
                if existing is None:
                    cell = EffectiveCell(
                        key=parsed.key,
                        name=parsed.name,
                        region=parsed.region or "",
                        plugin=plugin.name,
                        plugin_index=plugin_index,
                        first_plugin=plugin.name,
                        first_plugin_index=plugin_index,
                        offset=record.offset,
                        contexts=[context],
                    )
                    if parsed.name:
                        cell.historical_names.add(parsed.name)
                    cells[parsed.key] = cell
                else:
                    counters["cellOverrides"] += 1
                    if parsed.name:
                        existing.historical_names.add(parsed.name)
                    existing.name = parsed.name
                    if parsed.region is not None:
                        existing.region = parsed.region
                    existing.plugin = plugin.name
                    existing.plugin_index = plugin_index
                    existing.offset = record.offset
                    existing.contexts.append(context)
        records_by_plugin[plugin.name] = per_plugin

    regular: dict[ReferenceKey, ReferenceVersion] = {}
    moved: dict[ReferenceKey, ReferenceVersion] = {}
    origin_plugins = {index: plugin.name for index, plugin in enumerate(ordered)}
    contexts = sorted(
        (context for cell in cells.values() for context in cell.contexts),
        key=lambda value: (value.plugin_index, value.record_index),
    )
    for context in contexts:
        for reference in context.references:
            reference = ReferenceVersion(
                key=reference.key,
                raw_index=reference.raw_index,
                origin_plugin=origin_plugins[reference.key.origin_plugin_index],
                winning_plugin=reference.winning_plugin,
                winning_plugin_index=reference.winning_plugin_index,
                source_cell=reference.source_cell,
                effective_cell=reference.effective_cell,
                base_id=reference.base_id,
                position=reference.position,
                door_destination=reference.door_destination,
                destination_cell=reference.destination_cell,
                deleted=reference.deleted,
                moved=reference.moved,
                sequence=reference.sequence,
            )
            target = moved if reference.moved else regular
            if reference.key in target:
                counters["referenceOverrides"] += 1
            target[reference.key] = reference
            counters["referenceVersions"] += 1
            if reference.deleted:
                counters["referenceDeletions"] += 1
            if reference.moved:
                counters["movedReferenceVersions"] += 1

    effective_references = dict(regular)
    effective_references.update(moved)
    for cell in cells.values():
        cell.contexts.clear()
    counters["effectiveCells"] = len(cells)
    counters["effectiveInteriorCells"] = sum(cell.is_interior for cell in cells.values())
    counters["effectiveExteriorCells"] = len(cells) - counters["effectiveInteriorCells"]
    counters["effectiveDoors"] = len(doors)
    counters["effectiveReferences"] = len(effective_references)
    counters["effectiveTeleportReferences"] = sum(
        reference.door_destination is not None
        for reference in effective_references.values()
        if not reference.deleted
    )
    counters["effectiveExteriorTeleportReferences"] = sum(
        reference.door_destination is not None
        and reference.effective_cell.kind == "exterior"
        for reference in effective_references.values()
        if not reference.deleted
    )
    counters["effectiveLand"] = len(land_sources)
    counters["effectiveRegions"] = len(region_sources)
    for counter_name in (
        "cellOverrides",
        "cellDeletions",
        "doorOverrides",
        "doorDeletions",
        "landOverrides",
        "landDeletions",
        "regionOverrides",
        "regionDeletions",
        "referenceOverrides",
        "referenceDeletions",
        "movedReferenceVersions",
        "ignoredRecords",
    ):
        counters.setdefault(counter_name, 0)

    return EffectiveWorld(
        plugins=ordered,
        masters=tuple(plugin_masters),
        cells=cells,
        doors=doors,
        references=effective_references,
        land_sources=land_sources,
        region_sources=region_sources,
        counts={
            **dict(sorted(counters.items())),
            "recordsByPlugin": {
                plugin: dict(sorted(counts.items()))
                for plugin, counts in records_by_plugin.items()
            },
        },
    )
