from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from tools.land_renderer.land import LandCell
from tools.land_renderer.spike import (
    CONTROL_SITES,
    EXPECTED_SHA256,
    adapt_cell,
    build_render_world,
    coordinate_report,
    effective_asset_fingerprint,
    validate_inputs,
    wanted_control_cells,
)
from tools.land_renderer.terrain import RgbaImage
from tools.land_renderer.vfs import VirtualFileSystem


class SpikeProfileTests(unittest.TestCase):
    def test_five_controls_are_unique_and_include_the_poison_song_nan_iban_cell(self) -> None:
        self.assertEqual(len(CONTROL_SITES), 5)
        self.assertEqual(len({site.slug for site in CONTROL_SITES}), 5)
        self.assertEqual(CONTROL_SITES[-1].cell, (41, -30))
        self.assertEqual(coordinate_report(CONTROL_SITES[-1])["nativeTile"], {"z": 7, "x": 69, "y": 63})

    def test_control_neighborhood_has_a_one_cell_gutter(self) -> None:
        wanted = wanted_control_cells(radius=1)
        for site in CONTROL_SITES:
            for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
                self.assertIn((site.cell[0] + dx, site.cell[1] + dy), wanted)

    def test_input_validation_is_fail_closed(self) -> None:
        original = dict(EXPECTED_SHA256)
        try:
            EXPECTED_SHA256.clear()
            EXPECTED_SHA256["fixture.esm"] = hashlib.sha256(b"expected").hexdigest()
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "fixture.esm"
                path.write_bytes(b"wrong")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    validate_inputs(root)
                path.write_bytes(b"expected")
                result = validate_inputs(root)
            self.assertEqual(result["fixture.esm"]["bytes"], len(b"expected"))
        finally:
            EXPECTED_SHA256.clear()
            EXPECTED_SHA256.update(original)


class LandAdapterTests(unittest.TestCase):
    def test_preserves_plugin_scoped_vtex_keys_and_decodes_vertex_colors(self) -> None:
        colors = bytes((10, 20, 30)) * (65 * 65)
        parsed = LandCell(
            grid=(-3, -2),
            flags=7,
            source_plugin=4,
            source_path=Path("TR_Mainland.esm"),
            heights=(1.0,) * (65 * 65),
            normals=None,
            colors=colors,
            textures=(0, 3) + (2,) * 254,
        )

        rendered = adapt_cell(parsed)

        self.assertEqual(rendered.grid, (-3, -2))
        self.assertEqual(rendered.texture_keys[:3], (None, (4, 3), (4, 2)))
        self.assertEqual(rendered.vertex_colors[0], (10, 20, 30))  # type: ignore[index]

    def test_build_render_world_returns_cells_textures_and_asset_audit(self) -> None:
        parsed = LandCell(
            grid=(0, 0),
            flags=7,
            source_plugin=0,
            source_path=Path("fixture.esm"),
            heights=(1.0,) * (65 * 65),
            normals=None,
            colors=None,
            textures=(1,) * 256,
        )

        class Dataset:
            cells = {(0, 0): parsed}

            @staticmethod
            def resolve_texture_for_plugin(source_plugin: int, vtex_index: int):
                return type("Texture", (), {"record_id": "ground", "path": "ground.tga"})()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            textures = root / "textures"
            textures.mkdir()
            (textures / "ground.dds").write_bytes(b"ground")
            (textures / "_land_default.dds").write_bytes(b"default")
            vfs = VirtualFileSystem().mount_loose(root)
            with patch(
                "tools.land_renderer.spike.decode_texture",
                return_value=RgbaImage.solid(1, 1, (1, 2, 3, 255)),
            ):
                world, assets = build_render_world(  # type: ignore[arg-type]
                    Dataset(), vfs, texture_size=1, executable="magick"
                )

        self.assertIn((0, 0), world.cells)
        self.assertIn((0, 1), world.textures)
        self.assertEqual(assets[0]["logicalPath"], "textures/ground.dds")

    def test_effective_asset_fingerprint_changes_with_a_loose_payload(self) -> None:
        @dataclass(frozen=True)
        class Usage:
            source_plugin: int
            texture_indices: tuple[int, ...]

        class Dataset:
            texture_usage = {(0, 0): Usage(0, (1,))}

            @staticmethod
            def resolve_texture_for_plugin(source_plugin: int, vtex_index: int):
                self.assertEqual((source_plugin, vtex_index), (0, 1))
                return type("Texture", (), {"record_id": "ground", "path": "ground.tga"})()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            textures = root / "textures"
            textures.mkdir()
            (textures / "ground.dds").write_bytes(b"first")
            (textures / "_land_default.dds").write_bytes(b"default")
            vfs = VirtualFileSystem().mount_loose(root)
            first = effective_asset_fingerprint(Dataset(), vfs)  # type: ignore[arg-type]
            (textures / "ground.dds").write_bytes(b"second")
            vfs = VirtualFileSystem().mount_loose(root)
            second = effective_asset_fingerprint(Dataset(), vfs)  # type: ignore[arg-type]

        self.assertNotEqual(first[0], second[0])
        self.assertEqual(first[1:], (2, 2))


if __name__ == "__main__":
    unittest.main()
