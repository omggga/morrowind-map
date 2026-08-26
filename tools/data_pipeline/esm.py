from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class TeleportReference:
    plugin: str
    reference_id: int
    base_id: str
    destination: str
    coordinate: tuple[float, float]
    exterior_cell: tuple[int, int]


@dataclass(frozen=True)
class ExteriorCell:
    plugin: str
    name: str
    grid: tuple[int, int]


@dataclass(frozen=True)
class EsmWorldData:
    teleports: tuple[TeleportReference, ...]
    named_exterior_cells: tuple[ExteriorCell, ...]


def _decode_zstring(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("cp1252", errors="replace").strip()


def _records(path: Path) -> Iterator[tuple[bytes, bytes]]:
    with path.open("rb") as stream:
        while True:
            header = stream.read(16)
            if not header:
                return
            if len(header) != 16:
                raise ValueError(f"Truncated record header in {path}")
            record_type, size, _unknown, _flags = struct.unpack("<4sIII", header)
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError(f"Truncated {record_type!r} record in {path}")
            yield record_type, payload


def _subrecords(payload: bytes) -> Iterator[tuple[bytes, bytes]]:
    offset = 0
    while offset < len(payload):
        if offset + 8 > len(payload):
            raise ValueError("Truncated subrecord header")
        subrecord_type, size = struct.unpack_from("<4sI", payload, offset)
        offset += 8
        end = offset + size
        if end > len(payload):
            raise ValueError(f"Truncated {subrecord_type!r} subrecord")
        yield subrecord_type, payload[offset:end]
        offset = end


def extract_world_data(path: Path) -> EsmWorldData:
    plugin = path.name
    teleports: list[TeleportReference] = []
    exterior_cells: list[ExteriorCell] = []

    for record_type, payload in _records(path):
        if record_type != b"CELL":
            continue

        cell_name = ""
        cell_grid: tuple[int, int] | None = None
        is_exterior = False
        in_references = False
        current: dict[str, object] | None = None

        def finish_reference() -> None:
            if not is_exterior or current is None or current.get("deleted"):
                return
            destination = current.get("destination")
            coordinate = current.get("coordinate")
            reference_id = current.get("reference_id")
            if not isinstance(destination, str) or not destination:
                return
            if not isinstance(coordinate, tuple) or not isinstance(reference_id, int):
                return
            x, y = coordinate
            teleports.append(
                TeleportReference(
                    plugin=plugin,
                    reference_id=reference_id,
                    base_id=str(current.get("base_id", "")),
                    destination=destination,
                    coordinate=(x, y),
                    exterior_cell=(math.floor(x / 8192), math.floor(y / 8192)),
                )
            )

        for subrecord_type, value in _subrecords(payload):
            if subrecord_type == b"FRMR":
                finish_reference()
                in_references = True
                current = {"reference_id": struct.unpack_from("<I", value)[0]}
                continue

            if not in_references:
                if subrecord_type == b"NAME":
                    cell_name = _decode_zstring(value)
                elif subrecord_type == b"DATA" and len(value) >= 12:
                    flags, x, y = struct.unpack_from("<Iii", value)
                    is_exterior = flags & 1 == 0
                    if is_exterior:
                        cell_grid = (x, y)
                continue

            if current is None:
                continue
            if subrecord_type == b"NAME":
                current["base_id"] = _decode_zstring(value)
            elif subrecord_type == b"DNAM":
                current["destination"] = _decode_zstring(value)
            elif subrecord_type == b"DATA" and len(value) >= 24:
                x, y = struct.unpack_from("<2f", value)
                current["coordinate"] = (x, y)
            elif subrecord_type == b"DELE":
                current["deleted"] = True

        finish_reference()
        if is_exterior and cell_name and cell_grid is not None:
            exterior_cells.append(ExteriorCell(plugin=plugin, name=cell_name, grid=cell_grid))

    return EsmWorldData(tuple(teleports), tuple(exterior_cells))
