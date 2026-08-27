from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from tools.land_renderer.vfs import VirtualFileSystem


def bsa_bytes(files: list[tuple[str, bytes]]) -> bytes:
    name_offsets: list[int] = []
    names = bytearray()
    relative_offsets: list[int] = []
    data = bytearray()
    for name, payload in files:
        name_offsets.append(len(names))
        names.extend(name.encode("cp1252") + b"\0")
        relative_offsets.append(len(data))
        data.extend(payload)
    count = len(files)
    directory_size = count * 12 + len(names)
    return (
        struct.pack("<III", 0x100, directory_size, count)
        + b"".join(
            struct.pack("<II", len(payload), offset)
            for (_, payload), offset in zip(files, relative_offsets, strict=True)
        )
        + b"".join(struct.pack("<I", offset) for offset in name_offsets)
        + names
        + b"\0" * (count * 8)
        + data
    )


class VirtualFileSystemTests(unittest.TestCase):
    def test_later_mount_wins_across_bsa_and_loose_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_bsa = root / "first.bsa"
            second_bsa = root / "second.bsa"
            loose = root / "loose"
            first_bsa.write_bytes(bsa_bytes([("textures/a.dds", b"first")]))
            second_bsa.write_bytes(bsa_bytes([("textures/a.dds", b"last")]))
            (loose / "Textures").mkdir(parents=True)
            (loose / "Textures" / "A.DDS").write_bytes(b"loose")

            vfs = VirtualFileSystem().mount_bsa(first_bsa).mount_bsa(second_bsa)
            self.assertEqual(vfs.read("textures/a.dds"), b"last")

            vfs.mount_loose(loose)
            self.assertEqual(vfs.read("TEXTURES\\A.dds"), b"loose")
            resolved = vfs.resolve("textures/a.dds")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.source_kind, "loose")

            # Loose files have engine-style priority over archives even if an archive
            # is mounted later; mount order only decides precedence within a class.
            vfs.mount_bsa(second_bsa)
            self.assertEqual(vfs.read("textures/a.dds"), b"loose")
            resolved = vfs.resolve("textures/a.dds")
            assert resolved is not None
            self.assertEqual(resolved.source_kind, "loose")

    def test_resolves_openmw_style_texture_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loose = root / "loose"
            (loose / "textures" / "land").mkdir(parents=True)
            (loose / "textures" / "land" / "ground.dds").write_bytes(b"dds")
            (loose / "textures" / "fallback.tga").write_bytes(b"tga")
            (loose / "textures" / "no_extension").write_bytes(b"raw")
            (loose / "textures" / "no_extension.dds").write_bytes(b"not-selected")
            vfs = VirtualFileSystem().mount_loose(loose)

            resolved = vfs.resolve_texture("land\\ground.tga")
            prefixed = vfs.resolve_texture("Data Files/Textures/land/ground.bmp")
            basename = vfs.resolve_texture("nested/fallback.tga")
            extensionless = vfs.resolve_texture("no_extension")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.logical_path, "textures/land/ground.dds")
        self.assertEqual(prefixed.logical_path, "textures/land/ground.dds")  # type: ignore[union-attr]
        self.assertEqual(basename.logical_path, "textures/fallback.tga")  # type: ignore[union-attr]
        self.assertEqual(extensionless.logical_path, "textures/no_extension")  # type: ignore[union-attr]

    def test_missing_and_unsafe_paths_fail_closed(self) -> None:
        vfs = VirtualFileSystem()
        self.assertIsNone(vfs.resolve("textures/missing.dds"))
        with self.assertRaises(FileNotFoundError):
            vfs.read("textures/missing.dds")
        for value in ("../secret", "/absolute/path", "C:\\absolute\\path", "\0"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    vfs.resolve(value)


if __name__ == "__main__":
    unittest.main()
