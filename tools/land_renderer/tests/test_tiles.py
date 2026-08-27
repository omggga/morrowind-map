from __future__ import annotations

import math
import unittest

from tools.land_renderer.tiles import (
    CELL_PIXEL_SIZE,
    CELL_REFERENCE_ZOOM,
    CELL_TILE_PIXELS,
    POISON_SONG_TILE_GRID,
    RasterGrid,
    WorldExtent,
    cell_extent,
    cell_pixel_to_world,
    cell_raster_grid,
    world_to_cell,
    world_to_cell_pixel,
)


class CellCoordinateTests(unittest.TestCase):
    def test_negative_cell_boundaries_use_floor_semantics(self) -> None:
        self.assertEqual(world_to_cell(-0.001, -0.001), (-1, -1))
        self.assertEqual(world_to_cell(-8_192.0, -8_192.0), (-1, -1))
        self.assertEqual(world_to_cell(-8_192.001, -8_192.001), (-2, -2))
        self.assertEqual(world_to_cell(8_192.0, 8_192.0), (1, 1))

    def test_cell_extent_and_pixel_centres_use_16_world_units_per_pixel(self) -> None:
        self.assertEqual(
            cell_extent(-3, -2),
            WorldExtent(-24_576.0, -16_384.0, -16_384.0, -8_192.0),
        )
        self.assertEqual(CELL_PIXEL_SIZE, 16.0)
        self.assertEqual(
            cell_pixel_to_world(-3, -2, 0, 0, center=True),
            (-24_568.0, -8_200.0),
        )
        self.assertEqual(
            cell_pixel_to_world(-3, -2, 511, 511, center=True),
            (-16_392.0, -16_376.0),
        )

    def test_world_pixel_round_trip_inverts_y_exactly_once(self) -> None:
        grid = RasterGrid(WorldExtent(-10.0, -30.0, 30.0, 10.0), 4, 4)
        fixtures = (
            (-10.0, 10.0, 0.0, 0.0),
            (30.0, -30.0, 4.0, 4.0),
            (0.0, 0.0, 1.0, 1.0),
        )
        for world_x, world_y, column, row in fixtures:
            with self.subTest(world=(world_x, world_y)):
                self.assertEqual(grid.world_to_pixel(world_x, world_y), (column, row))
                self.assertEqual(grid.pixel_to_world(column, row), (world_x, world_y))

    def test_cell_local_pixel_position_round_trips_fractional_input(self) -> None:
        source = (-20_000.25, -12_000.75)
        cell_x, cell_y, column, row = world_to_cell_pixel(*source)
        self.assertEqual((cell_x, cell_y), (-3, -2))
        restored = cell_pixel_to_world(cell_x, cell_y, column, row)
        self.assertTrue(math.isclose(restored[0], source[0], abs_tol=1e-12))
        self.assertTrue(math.isclose(restored[1], source[1], abs_tol=1e-12))

    def test_gutter_expands_dimensions_without_changing_resolution(self) -> None:
        grid = cell_raster_grid(7, -19, gutter_pixels=3)
        self.assertEqual((grid.width, grid.height), (518, 518))
        self.assertEqual(grid.units_per_pixel_x, CELL_PIXEL_SIZE)
        self.assertEqual(grid.units_per_pixel_y, CELL_PIXEL_SIZE)
        self.assertEqual(grid.extent, WorldExtent(57_296.0, -155_696.0, 65_584.0, -147_408.0))


class TileGridTests(unittest.TestCase):
    def test_poison_song_control_cells_have_canonical_reference_tiles(self) -> None:
        fixtures = {
            (-3, -2): (25, 35),
            (7, -19): (35, 52),
            (16, -29): (44, 62),
            (19, -14): (47, 47),
            (41, -30): (69, 63),
        }
        for cell, tile in fixtures.items():
            with self.subTest(cell=cell):
                self.assertEqual(POISON_SONG_TILE_GRID.cell_to_tile(*cell), tile)
                self.assertEqual(
                    POISON_SONG_TILE_GRID.tile_extent(*tile, CELL_REFERENCE_ZOOM),
                    cell_extent(*cell),
                )

    def test_zoom_changes_world_span_and_preserves_top_left_xyz_orientation(self) -> None:
        self.assertEqual(POISON_SONG_TILE_GRID.tile_world_size(7), 8_192.0)
        self.assertEqual(POISON_SONG_TILE_GRID.tile_world_size(6), 16_384.0)
        extent = POISON_SONG_TILE_GRID.tile_extent(25, 35, 7)
        self.assertEqual(
            POISON_SONG_TILE_GRID.world_to_tile(extent.min_x, extent.max_y, 7),
            (25, 35),
        )
        self.assertEqual(
            POISON_SONG_TILE_GRID.world_to_tile(extent.max_x, extent.min_y, 7),
            (26, 36),
        )

    def test_world_tile_pixel_round_trip_is_subpixel_exact(self) -> None:
        world = (-20_000.25, -12_000.75)
        tile_x, tile_y, column, row = POISON_SONG_TILE_GRID.world_to_tile_pixel(*world, 7)
        self.assertEqual((tile_x, tile_y), (25, 35))
        restored = POISON_SONG_TILE_GRID.tile_raster_grid(tile_x, tile_y, 7).pixel_to_world(
            column, row
        )
        self.assertAlmostEqual(restored[0], world[0])
        self.assertAlmostEqual(restored[1], world[1])
        self.assertEqual(CELL_TILE_PIXELS, 512)


if __name__ == "__main__":
    unittest.main()
