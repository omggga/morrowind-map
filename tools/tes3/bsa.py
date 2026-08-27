from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


TES3_BSA_MAGIC = 0x100
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _ascii_lower(value: str) -> str:
    """Match TES3/OpenMW resource lookup: fold ASCII A-Z, not all Unicode."""

    return value.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


def normalize_resource_path(value: str) -> str:
    """Return a case-insensitive TES3 resource key and reject escaping paths."""

    if "\0" in value:
        raise ValueError("Resource path contains a NUL byte")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _WINDOWS_DRIVE.match(normalized):
        raise ValueError(f"Absolute resource path is not allowed: {value!r}")

    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"Resource path contains parent traversal: {value!r}")
        parts.append(part)
    if not parts:
        raise ValueError("Resource path is empty")
    return _ascii_lower("/".join(parts))


@dataclass(frozen=True)
class BsaEntry:
    name: str
    logical_path: str
    size: int
    offset: int
    hash_low: int
    hash_high: int


class BsaArchive:
    """Read-only index for the uncompressed TES3 BSA format."""

    def __init__(self, path: Path):
        self.path = Path(path)
        entries = self._read_index()
        self.entries: Mapping[str, BsaEntry] = MappingProxyType(entries)

    @staticmethod
    def _read_exact(stream: object, size: int, description: str) -> bytes:
        value = stream.read(size)  # type: ignore[attr-defined]
        if len(value) != size:
            raise ValueError(f"Truncated TES3 BSA {description}")
        return value

    def _read_index(self) -> dict[str, BsaEntry]:
        file_size = self.path.stat().st_size
        with self.path.open("rb") as stream:
            header = self._read_exact(stream, 12, f"header in {self.path}")
            magic, directory_size, file_count = struct.unpack("<III", header)
            if magic != TES3_BSA_MAGIC:
                raise ValueError(
                    f"Invalid TES3 BSA magic 0x{magic:08x} in {self.path}; "
                    f"expected 0x{TES3_BSA_MAGIC:08x}"
                )
            minimum_directory_size = file_count * 12
            if directory_size < minimum_directory_size:
                raise ValueError(
                    f"Invalid TES3 BSA directory size {directory_size} for "
                    f"{file_count} files in {self.path}"
                )
            data_base = 12 + directory_size + file_count * 8
            if data_base > file_size:
                raise ValueError(f"TES3 BSA directory extends outside archive {self.path}")

            raw_file_records = self._read_exact(
                stream, file_count * 8, f"file records in {self.path}"
            )
            raw_name_offsets = self._read_exact(
                stream, file_count * 4, f"name offsets in {self.path}"
            )
            names_size = directory_size - minimum_directory_size
            names = self._read_exact(stream, names_size, f"name table in {self.path}")
            raw_hashes = self._read_exact(
                stream, file_count * 8, f"hash table in {self.path}"
            )

        entries: dict[str, BsaEntry] = {}
        for index in range(file_count):
            size, relative_offset = struct.unpack_from("<II", raw_file_records, index * 8)
            name_offset = struct.unpack_from("<I", raw_name_offsets, index * 4)[0]
            hash_low, hash_high = struct.unpack_from("<II", raw_hashes, index * 8)
            if name_offset >= len(names):
                raise ValueError(
                    f"TES3 BSA name offset {name_offset} is outside name table in {self.path}"
                )
            terminator = names.find(b"\0", name_offset)
            if terminator < 0:
                raise ValueError(f"Unterminated TES3 BSA filename in {self.path}")
            name = names[name_offset:terminator].decode("cp1252", errors="replace")
            logical_path = normalize_resource_path(name)
            absolute_offset = data_base + relative_offset
            if absolute_offset > file_size or size > file_size - absolute_offset:
                raise ValueError(
                    f"TES3 BSA entry {name!r} extends outside archive {self.path}"
                )
            if logical_path in entries:
                raise ValueError(
                    f"Duplicate case-insensitive TES3 BSA path {logical_path!r} in {self.path}"
                )
            entries[logical_path] = BsaEntry(
                name=name,
                logical_path=logical_path,
                size=size,
                offset=absolute_offset,
                hash_low=hash_low,
                hash_high=hash_high,
            )
        return entries

    def get(self, logical_path: str) -> BsaEntry | None:
        return self.entries.get(normalize_resource_path(logical_path))

    def read_entry(self, entry: BsaEntry) -> bytes:
        with self.path.open("rb") as stream:
            stream.seek(entry.offset)
            payload = stream.read(entry.size)
        if len(payload) != entry.size:
            raise ValueError(f"Truncated TES3 BSA entry {entry.name!r} in {self.path}")
        return payload

    def read(self, logical_path: str) -> bytes:
        entry = self.get(logical_path)
        if entry is None:
            raise FileNotFoundError(f"Resource {logical_path!r} is not present in {self.path}")
        return self.read_entry(entry)
