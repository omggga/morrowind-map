from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from tools.land_renderer.land import audit_effective_textures, load_terrain
from tools.land_renderer.vfs import VirtualFileSystem


def subrecord(name: bytes, payload: bytes) -> bytes:
    return struct.pack("<4sI", name, len(payload)) + payload


def record(name: bytes, payload: bytes) -> bytes:
    return struct.pack("<4sIII", name, len(payload), 0, 0) + payload


def ltex(record_id: str, index: int, path: str | None, *, deleted: bool = False) -> bytes:
    payload = subrecord(b"NAME", record_id.encode("ascii") + b"\0")
    payload += subrecord(b"INTV", struct.pack("<i", index))
    if path is not None:
        payload += subrecord(b"DATA", path.encode("ascii") + b"\0")
    if deleted:
        payload += subrecord(b"DELE", b"\0\0\0")
    return record(b"LTEX", payload)


def land(
    grid: tuple[int, int],
    *,
    flags: int = 7,
    height_base: float = 10.0,
    deltas: bytes | None = None,
    normals: bytes | None = None,
    texture_values: tuple[int, ...] | None = None,
    deleted: bool = False,
) -> bytes:
    payload = subrecord(b"INTV", struct.pack("<ii", *grid))
    payload += subrecord(b"DATA", struct.pack("<I", flags))
    if deleted:
        payload += subrecord(b"DELE", b"\0\0\0")
        return record(b"LAND", payload)
    if deltas is None:
        deltas = b"\0" * 4_225
    payload += subrecord(b"VNML", normals or bytes([0, 0, 127]) * 4_225)
    payload += subrecord(b"VHGT", struct.pack("<f", height_base) + deltas + b"\0\0\0")
    payload += subrecord(b"WNAM", b"\0" * 81)
    payload += subrecord(b"VCLR", bytes([255, 240, 230]) * 4_225)
    if texture_values is None:
        texture_values = (0,) * 256
    payload += subrecord(b"VTEX", struct.pack("<256H", *texture_values))
    return record(b"LAND", payload)


class LandParserTests(unittest.TestCase):
    def test_decodes_vhgt_deltas_and_transposes_vtex(self) -> None:
        deltas = bytearray(4_225)
        deltas[0] = 1
        deltas[65] = 2
        deltas[66] = 3
        raw_textures = tuple(range(256))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "terrain.esm"
            path.write_bytes(
                land(
                    (4, -7),
                    deltas=bytes(deltas),
                    normals=bytes([255, 0, 127]) * 4_225,
                    texture_values=raw_textures,
                )
            )

            dataset = load_terrain([path])

        cell = dataset.cells[(4, -7)]
        assert cell.heights is not None
        assert cell.textures is not None
        self.assertEqual(cell.source_plugin, 0)
        self.assertEqual(cell.normals[:3], (-1, 0, 127))  # type: ignore[index]
        self.assertEqual(cell.heights[0], 88.0)
        self.assertEqual(cell.heights[1], 88.0)
        self.assertEqual(cell.heights[65], 104.0)
        self.assertEqual(cell.heights[66], 128.0)
        self.assertEqual(cell.textures[0], 0)
        self.assertEqual(cell.textures[1], 1)
        self.assertEqual(cell.textures[4], 16)
        self.assertEqual(cell.textures[16], 4)
        self.assertEqual(cell.textures[64], 64)

    def test_applies_land_overrides_deletions_and_plugin_scoped_ltex(self) -> None:
        base_textures = (1,) + (0,) * 255
        mod_textures = (3,) + (0,) * 255
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.esm"
            mod = root / "mod.esp"
            base.write_bytes(
                ltex("grass", 0, "land/base.tga")
                + land((1, 2), texture_values=base_textures)
                + land((9, 9))
            )
            mod.write_bytes(
                ltex("GRASS", 5, "land/override.dds")
                + ltex("stone", 2, "land/stone.dds")
                + land((3, 4), texture_values=mod_textures)
                + land((9, 9), deleted=True)
            )

            dataset = load_terrain([base, mod])

        self.assertEqual(set(dataset.cells), {(1, 2), (3, 4)})
        base_cell = dataset.cells[(1, 2)]
        mod_cell = dataset.cells[(3, 4)]
        self.assertEqual(base_cell.source_plugin, 0)
        self.assertEqual(mod_cell.source_plugin, 1)
        self.assertEqual(dataset.palette_ids[(0, 0)], "grass")
        self.assertEqual(dataset.palette_ids[(1, 2)], "stone")
        base_texture = dataset.resolve_texture(base_cell, 1)
        mod_texture = dataset.resolve_texture(mod_cell, 3)
        self.assertIsNotNone(base_texture)
        self.assertIsNotNone(mod_texture)
        assert base_texture is not None and mod_texture is not None
        self.assertEqual(base_texture.path, "land/override.dds")
        self.assertEqual(base_texture.source_plugin, 1)
        self.assertEqual(mod_texture.path, "land/stone.dds")
        self.assertIsNone(dataset.resolve_texture(base_cell, 0))

    def test_last_land_record_wins_as_a_whole_and_filter_limits_decoding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.esm"
            mod = root / "mod.esp"
            base.write_bytes(land((1, 2)) + land((3, 4)))
            mod.write_bytes(land((1, 2), flags=0))

            dataset = load_terrain([base, mod], wanted_cells={(1, 2)})

        self.assertEqual(set(dataset.cells), {(1, 2)})
        cell = dataset.cells[(1, 2)]
        self.assertEqual(cell.source_plugin, 1)
        self.assertIsNone(cell.heights)
        self.assertIsNone(cell.normals)
        self.assertIsNone(cell.colors)
        self.assertIsNone(cell.textures)

    def test_rejects_malformed_land_arrays(self) -> None:
        payload = subrecord(b"INTV", struct.pack("<ii", 0, 0))
        payload += subrecord(b"DATA", struct.pack("<I", 1))
        payload += subrecord(b"VHGT", b"short")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.esm"
            path.write_bytes(record(b"LAND", payload))
            with self.assertRaisesRegex(ValueError, "VHGT.*4232"):
                load_terrain([path])

    def test_audits_all_effective_vtex_without_retaining_vertex_arrays(self) -> None:
        raw_textures = (1, 2, 4) + (0,) * 253
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "terrain.esm"
            assets = root / "assets"
            (assets / "textures" / "land").mkdir(parents=True)
            (assets / "textures" / "land" / "grass.dds").write_bytes(b"dds")
            plugin.write_bytes(
                ltex("grass", 0, "land/grass.tga")
                + ltex("stone", 1, "land/missing.tga")
                + land((8, -3), texture_values=raw_textures)
            )
            dataset = load_terrain([plugin], wanted_cells=set())
            audit = audit_effective_textures(
                dataset, VirtualFileSystem().mount_loose(assets)
            )

        self.assertEqual(dataset.cells, {})
        self.assertEqual(set(dataset.texture_usage[(8, -3)].texture_indices), {1, 2, 4})
        self.assertEqual(audit.cell_count, 1)
        self.assertEqual(audit.reference_count, 3)
        self.assertEqual(audit.occurrence_count, 3)
        self.assertEqual(audit.resolved_count, 1)
        self.assertFalse(audit.ok)
        self.assertEqual(
            [(issue.vtex_index, issue.reason) for issue in audit.unresolved],
            [(2, "missing_asset"), (4, "missing_ltex")],
        )


if __name__ == "__main__":
    unittest.main()
