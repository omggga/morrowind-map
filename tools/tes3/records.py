from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


RECORD_HEADER_SIZE = 16
SUBRECORD_HEADER_SIZE = 8


@dataclass(frozen=True)
class Record:
    """One bounded TES3 record, including load-order relevant header metadata."""

    record_type: bytes
    payload: bytes
    unknown: int
    flags: int
    offset: int

    @property
    def size(self) -> int:
        return len(self.payload)


@dataclass(frozen=True)
class Subrecord:
    """One subrecord whose offset is relative to its parent record payload."""

    subrecord_type: bytes
    payload: bytes
    offset: int

    @property
    def size(self) -> int:
        return len(self.payload)


def _tag_text(tag: bytes) -> str:
    return tag.decode("ascii", errors="backslashreplace")


def iter_records(path: Path) -> Iterator[Record]:
    """Stream records from an ESM/ESP without reading the whole plugin into memory."""

    path = Path(path)
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        while stream.tell() < file_size:
            offset = stream.tell()
            header = stream.read(RECORD_HEADER_SIZE)
            if len(header) != RECORD_HEADER_SIZE:
                raise ValueError(f"Truncated record header at {offset} in {path}")
            record_type, size, unknown, flags = struct.unpack("<4sIII", header)
            remaining = file_size - stream.tell()
            if size > remaining:
                raise ValueError(
                    f"Truncated {_tag_text(record_type)} record at {offset} in {path}: "
                    f"declares {size} bytes, only {remaining} remain"
                )
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError(
                    f"Truncated {_tag_text(record_type)} record at {offset} in {path}"
                )
            yield Record(record_type, payload, unknown, flags, offset)


def iter_subrecords(payload: bytes) -> Iterator[Subrecord]:
    """Iterate strictly bounded TES3 subrecords from a record payload."""

    offset = 0
    while offset < len(payload):
        header_offset = offset
        if len(payload) - offset < SUBRECORD_HEADER_SIZE:
            raise ValueError(f"Truncated subrecord header at payload offset {offset}")
        subrecord_type, size = struct.unpack_from("<4sI", payload, offset)
        offset += SUBRECORD_HEADER_SIZE
        end = offset + size
        if end > len(payload):
            raise ValueError(
                f"Truncated {_tag_text(subrecord_type)} subrecord at payload offset "
                f"{header_offset}: declares {size} bytes, only {len(payload) - offset} remain"
            )
        yield Subrecord(subrecord_type, payload[offset:end], header_offset)
        offset = end


def decode_zstring(value: bytes, *, encoding: str = "cp1252") -> str:
    """Decode a TES3 byte string up to its first NUL terminator."""

    return value.split(b"\0", 1)[0].decode(encoding, errors="replace")
