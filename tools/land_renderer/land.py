from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Collection, Mapping, Protocol, Sequence

from tools.tes3.records import Record, decode_zstring, iter_records, iter_subrecords


LAND_SIZE = 65
LAND_VERTEX_COUNT = LAND_SIZE * LAND_SIZE
LAND_TEXTURE_SIZE = 16
LAND_TEXTURE_COUNT = LAND_TEXTURE_SIZE * LAND_TEXTURE_SIZE
HEIGHT_SCALE = 8.0
DEFAULT_HEIGHT = -2048.0

FLAG_HEIGHTS_NORMALS = 0x1
FLAG_COLORS = 0x2
FLAG_TEXTURES = 0x4

_VNML_SIZE = LAND_VERTEX_COUNT * 3
_VHGT_SIZE = 4 + LAND_VERTEX_COUNT + 3
_VCLR_SIZE = LAND_VERTEX_COUNT * 3
_VTEX_SIZE = LAND_TEXTURE_COUNT * 2
_KNOWN_LAND_SUBRECORDS = {b"INTV", b"DATA", b"DELE", b"VNML", b"VHGT", b"WNAM", b"VCLR", b"VTEX"}
_KNOWN_LTEX_SUBRECORDS = {b"NAME", b"INTV", b"DATA", b"DELE"}


@dataclass(frozen=True)
class LandCell:
    grid: tuple[int, int]
    flags: int
    source_plugin: int
    source_path: Path
    heights: tuple[float, ...] | None
    normals: tuple[int, ...] | None
    colors: bytes | None
    textures: tuple[int, ...] | None


@dataclass(frozen=True)
class LandTexture:
    record_id: str
    index: int
    path: str
    source_plugin: int
    source_path: Path


@dataclass(frozen=True)
class LandTextureUsage:
    grid: tuple[int, int]
    source_plugin: int
    source_path: Path
    texture_indices: tuple[int, ...]


@dataclass(frozen=True)
class UnresolvedTexture:
    source_plugin: int
    vtex_index: int
    reason: str
    ltex_id: str | None
    texture_path: str | None
    occurrence_count: int
    example_cells: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class TextureAudit:
    cell_count: int
    reference_count: int
    occurrence_count: int
    resolved_count: int
    unresolved: tuple[UnresolvedTexture, ...]

    @property
    def ok(self) -> bool:
        return not self.unresolved


@dataclass(frozen=True)
class TerrainDataset:
    cells: Mapping[tuple[int, int], LandCell]
    palette_ids: Mapping[tuple[int, int], str]
    textures_by_id: Mapping[str, LandTexture]
    texture_usage: Mapping[tuple[int, int], LandTextureUsage]
    plugins: tuple[Path, ...]

    @property
    def effective_texture_usage(self) -> Mapping[tuple[int, int], LandTextureUsage]:
        return self.texture_usage

    def resolve_texture_for_plugin(
        self, source_plugin: int, vtex_index: int
    ) -> LandTexture | None:
        if vtex_index == 0:
            return None
        ltex_id = self.palette_ids.get((source_plugin, vtex_index - 1))
        if ltex_id is None:
            return None
        return self.textures_by_id.get(ltex_id)

    def resolve_texture(self, cell: LandCell, vtex_index: int) -> LandTexture | None:
        return self.resolve_texture_for_plugin(cell.source_plugin, vtex_index)


class TextureResolver(Protocol):
    def resolve_texture(self, texture_path: str) -> object | None: ...


@dataclass(frozen=True)
class _LandParts:
    grid: tuple[int, int]
    flags: int
    deleted: bool
    values: Mapping[bytes, bytes]


@dataclass(frozen=True)
class _LtexParts:
    record_id: str
    index: int
    path: str
    deleted: bool


def _require_size(tag: str, value: bytes, expected: int, source_path: Path) -> None:
    if len(value) != expected:
        raise ValueError(
            f"{tag} in {source_path} must be {expected} bytes, got {len(value)}"
        )


def _collect_subrecords(
    record: Record, known: set[bytes], source_path: Path
) -> tuple[dict[bytes, bytes], bool]:
    values: dict[bytes, bytes] = {}
    deleted = False
    for child in iter_subrecords(record.payload):
        tag = child.subrecord_type
        if tag not in known:
            readable = tag.decode("ascii", errors="backslashreplace")
            raise ValueError(
                f"Unknown {record.record_type!r} subrecord {readable} in {source_path}"
            )
        if tag == b"DELE":
            deleted = True
            continue
        if tag in values:
            readable = tag.decode("ascii", errors="backslashreplace")
            raise ValueError(f"Duplicate {readable} subrecord in {source_path}")
        values[tag] = child.payload
    return values, deleted


def _parse_land_parts(record: Record, source_path: Path) -> _LandParts:
    values, deleted = _collect_subrecords(record, _KNOWN_LAND_SUBRECORDS, source_path)
    location = values.get(b"INTV")
    if location is None:
        raise ValueError(f"LAND record is missing INTV in {source_path}")
    _require_size("LAND INTV", location, 8, source_path)
    grid = struct.unpack("<ii", location)
    raw_flags = values.get(b"DATA", b"\0\0\0\0")
    _require_size("LAND DATA", raw_flags, 4, source_path)
    flags = struct.unpack("<I", raw_flags)[0]
    return _LandParts(grid, flags, deleted, MappingProxyType(values))


def _decode_heights(value: bytes, source_path: Path) -> tuple[float, ...]:
    _require_size("LAND VHGT", value, _VHGT_SIZE, source_path)
    base = struct.unpack_from("<f", value)[0]
    if not math.isfinite(base):
        raise ValueError(f"LAND VHGT base height is not finite in {source_path}")
    deltas = struct.unpack_from(f"<{LAND_VERTEX_COUNT}b", value, 4)
    heights = [0.0] * LAND_VERTEX_COUNT
    row_offset = base
    for y in range(LAND_SIZE):
        row_start = y * LAND_SIZE
        row_offset += deltas[row_start]
        heights[row_start] = row_offset * HEIGHT_SCALE
        column_offset = row_offset
        for x in range(1, LAND_SIZE):
            index = row_start + x
            column_offset += deltas[index]
            heights[index] = column_offset * HEIGHT_SCALE
    return tuple(heights)


def _decode_textures(value: bytes, source_path: Path) -> tuple[int, ...]:
    _require_size("LAND VTEX", value, _VTEX_SIZE, source_path)
    source = struct.unpack("<256H", value)
    result = [0] * LAND_TEXTURE_COUNT
    read_position = 0
    for y1 in range(4):
        for x1 in range(4):
            for y2 in range(4):
                for x2 in range(4):
                    result[(y1 * 4 + y2) * LAND_TEXTURE_SIZE + (x1 * 4 + x2)] = source[
                        read_position
                    ]
                    read_position += 1
    return tuple(result)


def _texture_indices(parts: _LandParts, source_path: Path) -> tuple[int, ...]:
    value = parts.values.get(b"VTEX")
    if not (parts.flags & FLAG_TEXTURES) or value is None:
        return ()
    return tuple(sorted(set(_decode_textures(value, source_path)) - {0}))


def _decode_land(
    parts: _LandParts, source_plugin: int, source_path: Path
) -> LandCell:
    heights: tuple[float, ...] | None = None
    normals: tuple[int, ...] | None = None
    colors: bytes | None = None
    textures: tuple[int, ...] | None = None

    if parts.flags & FLAG_HEIGHTS_NORMALS:
        raw_heights = parts.values.get(b"VHGT")
        if raw_heights is not None:
            heights = _decode_heights(raw_heights, source_path)
        raw_normals = parts.values.get(b"VNML")
        if raw_normals is not None:
            _require_size("LAND VNML", raw_normals, _VNML_SIZE, source_path)
            normals = struct.unpack(f"<{_VNML_SIZE}b", raw_normals)
    if parts.flags & FLAG_COLORS:
        raw_colors = parts.values.get(b"VCLR")
        if raw_colors is not None:
            _require_size("LAND VCLR", raw_colors, _VCLR_SIZE, source_path)
            colors = raw_colors
    if parts.flags & FLAG_TEXTURES:
        raw_textures = parts.values.get(b"VTEX")
        if raw_textures is not None:
            textures = _decode_textures(raw_textures, source_path)

    return LandCell(
        grid=parts.grid,
        flags=parts.flags,
        source_plugin=source_plugin,
        source_path=source_path,
        heights=heights,
        normals=normals,
        colors=colors,
        textures=textures,
    )


def _parse_ltex(record: Record, source_path: Path) -> _LtexParts:
    values, deleted = _collect_subrecords(record, _KNOWN_LTEX_SUBRECORDS, source_path)
    raw_id = values.get(b"NAME")
    raw_index = values.get(b"INTV")
    if raw_id is None:
        raise ValueError(f"LTEX record is missing NAME in {source_path}")
    if raw_index is None:
        raise ValueError(f"LTEX record is missing INTV in {source_path}")
    _require_size("LTEX INTV", raw_index, 4, source_path)
    record_id = decode_zstring(raw_id)
    if not record_id:
        raise ValueError(f"LTEX NAME is empty in {source_path}")
    index = struct.unpack("<I", raw_index)[0]
    path = decode_zstring(values.get(b"DATA", b""))
    if not deleted and not path:
        raise ValueError(f"LTEX record {record_id!r} has no DATA path in {source_path}")
    return _LtexParts(record_id, index, path, deleted)


def load_terrain(
    plugins: Sequence[Path],
    wanted_cells: Collection[tuple[int, int]] | None = None,
) -> TerrainDataset:
    """Load effective TES3 LAND and its plugin-scoped LTEX palettes.

    Full vertex arrays are retained only for ``wanted_cells`` when supplied. A compact
    VTEX usage summary is always retained for every effective LAND record so callers
    can audit the complete world without the memory cost of all 65x65 height fields.
    """

    plugin_paths = tuple(Path(path) for path in plugins)
    wanted = None if wanted_cells is None else frozenset(wanted_cells)
    cells: dict[tuple[int, int], LandCell] = {}
    palette_ids: dict[tuple[int, int], str] = {}
    textures_by_id: dict[str, LandTexture] = {}
    texture_usage: dict[tuple[int, int], LandTextureUsage] = {}

    for source_plugin, source_path in enumerate(plugin_paths):
        for record in iter_records(source_path):
            if record.record_type == b"LTEX":
                texture = _parse_ltex(record, source_path)
                key = texture.record_id.casefold()
                if texture.deleted:
                    textures_by_id.pop(key, None)
                    continue
                palette_ids.setdefault((source_plugin, texture.index), key)
                textures_by_id[key] = LandTexture(
                    record_id=texture.record_id,
                    index=texture.index,
                    path=texture.path,
                    source_plugin=source_plugin,
                    source_path=source_path,
                )
                continue
            if record.record_type != b"LAND":
                continue

            parts = _parse_land_parts(record, source_path)
            if parts.deleted:
                cells.pop(parts.grid, None)
                texture_usage.pop(parts.grid, None)
                continue

            texture_usage[parts.grid] = LandTextureUsage(
                grid=parts.grid,
                source_plugin=source_plugin,
                source_path=source_path,
                texture_indices=_texture_indices(parts, source_path),
            )
            if wanted is None or parts.grid in wanted:
                cells[parts.grid] = _decode_land(parts, source_plugin, source_path)

    return TerrainDataset(
        cells=MappingProxyType(cells),
        palette_ids=MappingProxyType(palette_ids),
        textures_by_id=MappingProxyType(textures_by_id),
        texture_usage=MappingProxyType(texture_usage),
        plugins=plugin_paths,
    )


def audit_effective_textures(
    dataset: TerrainDataset, resolver: TextureResolver
) -> TextureAudit:
    """Resolve every unique effective non-default VTEX reference against a VFS."""

    occurrences: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for usage in dataset.texture_usage.values():
        for vtex_index in usage.texture_indices:
            occurrences.setdefault((usage.source_plugin, vtex_index), []).append(usage.grid)

    unresolved: list[UnresolvedTexture] = []
    resolved_count = 0
    for (source_plugin, vtex_index), grids in sorted(occurrences.items()):
        ltex_id = dataset.palette_ids.get((source_plugin, vtex_index - 1))
        texture = dataset.textures_by_id.get(ltex_id) if ltex_id is not None else None
        if ltex_id is None or texture is None:
            unresolved.append(
                UnresolvedTexture(
                    source_plugin=source_plugin,
                    vtex_index=vtex_index,
                    reason="missing_ltex",
                    ltex_id=ltex_id,
                    texture_path=None,
                    occurrence_count=len(grids),
                    example_cells=tuple(grids[:5]),
                )
            )
            continue
        if resolver.resolve_texture(texture.path) is None:
            unresolved.append(
                UnresolvedTexture(
                    source_plugin=source_plugin,
                    vtex_index=vtex_index,
                    reason="missing_asset",
                    ltex_id=ltex_id,
                    texture_path=texture.path,
                    occurrence_count=len(grids),
                    example_cells=tuple(grids[:5]),
                )
            )
            continue
        resolved_count += 1

    return TextureAudit(
        cell_count=len(dataset.texture_usage),
        reference_count=len(occurrences),
        occurrence_count=sum(len(grids) for grids in occurrences.values()),
        resolved_count=resolved_count,
        unresolved=tuple(unresolved),
    )
