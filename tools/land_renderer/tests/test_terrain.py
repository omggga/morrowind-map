from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.land_renderer.terrain import (
    Lighting,
    RenderStyle,
    RgbaImage,
    TerrainCell,
    TerrainWorld,
    encode_webp,
    image_sha256,
    render_cell,
    render_grid,
    shade_point,
    write_webp,
)
from tools.land_renderer.tiles import RasterGrid, WorldExtent


def flat_cell(
    cell_x: int,
    cell_y: int,
    texture_key: str,
    *,
    height: float = 100.0,
    vertex_color: tuple[int, int, int] | None = None,
) -> TerrainCell:
    return TerrainCell(
        cell_x,
        cell_y,
        (height,) * (65 * 65),
        (texture_key,) * (16 * 16),
        None if vertex_color is None else (vertex_color,) * (65 * 65),
    )


class ImageTests(unittest.TestCase):
    def test_repeat_sampler_wraps_and_bilinearly_blends(self) -> None:
        image = RgbaImage(
            2,
            2,
            bytes(
                (
                    255,
                    0,
                    0,
                    255,
                    0,
                    255,
                    0,
                    255,
                    0,
                    0,
                    255,
                    255,
                    255,
                    255,
                    255,
                    255,
                )
            ),
        )
        self.assertEqual(image.sample_repeat(0.25, 0.25), (255, 0, 0, 255))
        self.assertEqual(image.sample_repeat(1.25, -0.75), (255, 0, 0, 255))
        self.assertEqual(image.sample_repeat(0.5, 0.5), (128, 128, 128, 255))

    def test_crop_copies_rows_without_aliasing(self) -> None:
        image = RgbaImage(3, 2, bytes(range(24)))
        cropped = image.crop(1, 0, 2, 2)
        self.assertEqual((cropped.width, cropped.height), (2, 2))
        self.assertEqual(cropped.pixels, bytes(range(4, 12)) + bytes(range(16, 24)))


class TerrainSamplingTests(unittest.TestCase):
    def test_height_interpolation_uses_south_to_north_rows(self) -> None:
        heights = []
        for y in range(65):
            for x in range(65):
                heights.append(x * 10.0 + y * 100.0)
        cell = TerrainCell(0, 0, heights, ("ground",) * 256)
        world = TerrainWorld({(0, 0): cell}, {"ground": RgbaImage.solid(1, 1, (1, 2, 3, 255))})
        self.assertEqual(world.sample_height(64.0, 64.0), 55.0)
        self.assertEqual(world.sample_height(128.0, 256.0), 210.0)

    def test_height_and_texture_sampling_crosses_cell_edges_globally(self) -> None:
        west = flat_cell(0, 0, "west", height=10.0)
        east = flat_cell(1, 0, "east", height=20.0)
        world = TerrainWorld(
            {(0, 0): west, (1, 0): east},
            {
                "west": RgbaImage.solid(1, 1, (200, 0, 0, 255)),
                "east": RgbaImage.solid(1, 1, (0, 0, 200, 255)),
            },
        )
        self.assertEqual(world.sample_height(8_191.0, 1_000.0), 10.0)
        self.assertEqual(world.sample_height(8_193.0, 1_000.0), 20.0)
        self.assertEqual(world.texture_weights(8_192.0 - 256.0, 256.0), {"west": 1.0})
        self.assertEqual(world.texture_weights(8_192.0, 256.0), {"west": 0.5, "east": 0.5})

    def test_flat_vertical_light_preserves_texture_and_vertex_colour_modulates_it(self) -> None:
        cell = flat_cell(0, 0, "ground", vertex_color=(128, 255, 64))
        world = TerrainWorld(
            {(0, 0): cell},
            {"ground": RgbaImage.solid(1, 1, (200, 100, 80, 255))},
            default_water_height=None,
        )
        style = RenderStyle(lighting=Lighting((0.0, 0.0, 1.0), 0.25, 0.75))
        self.assertEqual(shade_point(world, 4_096.0, 4_096.0, style), (100, 100, 20, 255))

    def test_missing_texture_is_visible_and_not_silently_hidden(self) -> None:
        cell = flat_cell(0, 0, "missing")
        world = TerrainWorld({(0, 0): cell}, {}, default_water_height=None)
        style = RenderStyle(
            lighting=Lighting((0.0, 0.0, 1.0), 1.0, 0.0),
            use_vertex_colors=False,
        )
        sampled = shade_point(world, 256.0, 256.0, style)
        self.assertEqual(sampled, (140, 12, 140, 255))
        self.assertGreater(sampled[0], 100)
        self.assertGreater(sampled[2], 100)


class RendererTests(unittest.TestCase):
    def setUp(self) -> None:
        cell = flat_cell(0, 0, "ground")
        self.world = TerrainWorld(
            {(0, 0): cell},
            {"ground": RgbaImage.solid(1, 1, (20, 40, 60, 255))},
            default_water_height=None,
        )
        self.style = RenderStyle(
            lighting=Lighting((0.0, 0.0, 1.0), 1.0, 0.0),
            use_vertex_colors=False,
        )

    def test_render_grid_samples_pixel_centres_top_to_bottom(self) -> None:
        image = render_grid(
            self.world,
            RasterGrid(WorldExtent(248.0, 248.0, 280.0, 264.0), 2, 1),
            style=self.style,
        )
        self.assertEqual((image.width, image.height), (2, 1))
        self.assertEqual(image.pixels, bytes((20, 40, 60, 255)) * 2)

    def test_gutter_render_crops_back_to_exact_512_pixels(self) -> None:
        image = render_cell(self.world, 0, 0, style=self.style, gutter_pixels=1)
        self.assertEqual((image.width, image.height), (512, 512))
        self.assertEqual(len(image.pixels), 512 * 512 * 4)
        self.assertEqual(
            image_sha256(image),
            hashlib.sha256(b"RGBA:512x512\0" + image.pixels).hexdigest(),
        )


class WebpTests(unittest.TestCase):
    def test_actual_webp_encoding_is_stable_when_imagemagick_is_available(self) -> None:
        image = RgbaImage.solid(2, 2, (12, 34, 56, 255))
        try:
            first = encode_webp(image)
            second = encode_webp(image)
        except RuntimeError as error:
            if "executable not found" in str(error):
                self.skipTest(str(error))
            raise
        self.assertEqual(first, second)
        self.assertEqual(first[:4], b"RIFF")
        self.assertEqual(first[8:12], b"WEBP")

    def test_writer_is_atomic_and_reports_hash(self) -> None:
        payload = b"RIFF" + (4).to_bytes(4, "little") + b"WEBP"
        image = RgbaImage.solid(1, 1, (1, 2, 3, 255))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "control.webp"
            with patch("tools.land_renderer.terrain.encode_webp", return_value=payload):
                result = write_webp(image, output)
            self.assertEqual(output.read_bytes(), payload)
        self.assertEqual(result.byte_length, len(payload))
        self.assertEqual(result.sha256, hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
