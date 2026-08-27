from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from tools.tes3.bsa import BsaArchive
from tools.tes3.records import iter_records, iter_subrecords


def record(
    record_type: bytes,
    payload: bytes,
    *,
    unknown: int = 0,
    flags: int = 0,
) -> bytes:
    return struct.pack("<4sIII", record_type, len(payload), unknown, flags) + payload


def subrecord(subrecord_type: bytes, payload: bytes) -> bytes:
    return struct.pack("<4sI", subrecord_type, len(payload)) + payload


def bsa_bytes(files: list[tuple[str, bytes]], *, offsets: list[int] | None = None) -> bytes:
    encoded_names = [name.encode("cp1252") + b"\0" for name, _ in files]
    name_offsets: list[int] = []
    names = bytearray()
    for encoded in encoded_names:
        name_offsets.append(len(names))
        names.extend(encoded)

    relative_offsets: list[int] = []
    data = bytearray()
    for _, payload in files:
        relative_offsets.append(len(data))
        data.extend(payload)
    if offsets is not None:
        relative_offsets = offsets

    file_count = len(files)
    directory_size = file_count * 12 + len(names)
    header = struct.pack("<III", 0x100, directory_size, file_count)
    file_records = b"".join(
        struct.pack("<II", len(payload), relative_offset)
        for (_, payload), relative_offset in zip(files, relative_offsets, strict=True)
    )
    offsets_table = b"".join(struct.pack("<I", value) for value in name_offsets)
    hashes = b"\0" * (file_count * 8)
    return header + file_records + offsets_table + names + hashes + data


class Tes3RecordReaderTests(unittest.TestCase):
    def test_preserves_record_metadata_and_subrecord_offsets(self) -> None:
        payload = subrecord(b"NAME", b"terrain\0") + subrecord(b"DATA", b"abc")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.esm"
            path.write_bytes(record(b"LTEX", payload, unknown=17, flags=0x20))

            records = list(iter_records(path))
            children = list(iter_subrecords(records[0].payload))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, b"LTEX")
        self.assertEqual(records[0].unknown, 17)
        self.assertEqual(records[0].flags, 0x20)
        self.assertEqual(records[0].offset, 0)
        self.assertEqual(
            [(child.subrecord_type, child.payload, child.offset) for child in children],
            [(b"NAME", b"terrain\0", 0), (b"DATA", b"abc", 16)],
        )

    def test_rejects_truncated_records_and_subrecords(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.esm"
            path.write_bytes(struct.pack("<4sIII", b"LAND", 9, 0, 0) + b"short")
            with self.assertRaisesRegex(ValueError, "Truncated LAND record"):
                list(iter_records(path))

        with self.assertRaisesRegex(ValueError, "Truncated subrecord header"):
            list(iter_subrecords(b"DATA"))
        with self.assertRaisesRegex(ValueError, "Truncated DATA subrecord"):
            list(iter_subrecords(struct.pack("<4sI", b"DATA", 10) + b"x"))


class BsaArchiveTests(unittest.TestCase):
    def test_indexes_and_reads_tes3_bsa_entries_case_insensitively(self) -> None:
        fixture = bsa_bytes(
            [("Textures\\Land\\A.DDS", b"texture"), ("meshes\\b.nif", b"mesh")]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bsa"
            path.write_bytes(fixture)

            archive = BsaArchive(path)

            self.assertEqual(archive.read("textures/land/a.dds"), b"texture")
            self.assertEqual(archive.read("MESHES/B.NIF"), b"mesh")
            entry = archive.get("textures\\land\\a.dds")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.name, "Textures\\Land\\A.DDS")
            self.assertEqual(entry.size, 7)

    def test_rejects_bad_magic_out_of_bounds_data_and_unsafe_names(self) -> None:
        fixtures = (
            ("magic", struct.pack("<III", 7, 0, 0), "magic"),
            (
                "bounds",
                bsa_bytes([("textures/a.dds", b"x")], offsets=[99]),
                "outside archive",
            ),
            (
                "traversal",
                bsa_bytes([("..\\outside.dds", b"x")]),
                "parent traversal",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, payload, message in fixtures:
                with self.subTest(label=label):
                    path = root / f"{label}.bsa"
                    path.write_bytes(payload)
                    with self.assertRaisesRegex(ValueError, message):
                        BsaArchive(path)


if __name__ == "__main__":
    unittest.main()
