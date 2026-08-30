from __future__ import annotations

import unittest

from tools.land_renderer.terrain import RgbaImage
from tools.openmw_renderer.images import (
    DEFAULT_GRADE,
    GRADE_VERSION,
    PRODUCTION_ALPHA_MODE,
    PRODUCTION_GRADE,
    PRODUCTION_GRADE_VERSION,
    GradeStyle,
    apply_grade,
    normalize_binary_alpha,
    pixel_difference,
    seam_overlap,
)


def grid_image(rows: list[list[int]]) -> RgbaImage:
    height = len(rows)
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("Fixture rows must have equal widths")
    pixels = bytes(channel for row in rows for value in row for channel in (value, value, value, 255))
    return RgbaImage(width, height, pixels)


class GradeTests(unittest.TestCase):
    def test_legacy_default_grade_has_exact_deterministic_pixels_and_preserves_alpha(self) -> None:
        source = RgbaImage(
            3,
            1,
            bytes((100, 150, 200, 17, 0, 0, 0, 99, 255, 255, 255, 201)),
        )
        expected = bytes((105, 157, 208, 17, 0, 0, 0, 99, 255, 255, 255, 201))

        first = apply_grade(source)
        second = apply_grade(source)

        self.assertEqual(first, second)
        self.assertEqual(first.pixels, expected)
        self.assertEqual((first.width, first.height), (3, 1))
        self.assertEqual(GRADE_VERSION, "mim-muted-v1")
        self.assertEqual(DEFAULT_GRADE, GradeStyle(104, 108, 92))

    def test_production_v4_grade_has_exact_single_pass_pixels(self) -> None:
        source = RgbaImage(
            3,
            1,
            bytes((100, 150, 200, 17, 0, 0, 0, 99, 255, 255, 255, 201)),
        )

        graded = apply_grade(source, PRODUCTION_GRADE)

        self.assertEqual(
            graded.pixels,
            bytes((117, 170, 223, 17, 0, 0, 0, 99, 255, 255, 255, 201)),
        )
        self.assertEqual(PRODUCTION_GRADE_VERSION, "mim-opaque-v4")
        self.assertEqual(PRODUCTION_GRADE, GradeStyle(114, 102, 92))

    def test_binary_alpha_preserves_rgb_and_transparent_sparse_holes(self) -> None:
        source = RgbaImage(
            4,
            1,
            bytes(
                (
                    10, 20, 30, 0,
                    40, 50, 60, 1,
                    70, 80, 90, 109,
                    100, 110, 120, 255,
                )
            ),
        )

        opaque = normalize_binary_alpha(source)

        self.assertEqual(
            opaque.pixels,
            bytes(
                (
                    10, 20, 30, 0,
                    40, 50, 60, 255,
                    70, 80, 90, 255,
                    100, 110, 120, 255,
                )
            ),
        )
        self.assertEqual(
            PRODUCTION_ALPHA_MODE,
            "binary-nonzero",
        )

    def test_grade_style_rejects_percentages_outside_supported_range(self) -> None:
        invalid_styles = (
            {"brightness_percent": -1},
            {"contrast_percent": 301},
            {"saturation_percent": -1},
        )
        for values in invalid_styles:
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, "between 0 and 300"):
                    GradeStyle(**values)


class PixelDifferenceTests(unittest.TestCase):
    def test_pixel_difference_reports_exact_channel_statistics(self) -> None:
        left = RgbaImage(2, 1, bytes((10, 20, 30, 40, 0, 0, 0, 255)))
        right = RgbaImage(2, 1, bytes((12, 18, 30, 50, 255, 0, 10, 250)))

        first = pixel_difference(left, right)
        second = pixel_difference(left, right)

        self.assertEqual(first, second)
        self.assertEqual(first.pixels, 2)
        self.assertEqual(first.differing_pixels, 2)
        self.assertEqual(first.differing_fraction, 1.0)
        self.assertEqual(first.mean_absolute_channel_delta, 35.5)
        self.assertEqual(first.maximum_channel_delta, 255)

    def test_pixel_difference_for_identical_images_is_zero(self) -> None:
        image = RgbaImage.solid(2, 2, (12, 34, 56, 78))
        difference = pixel_difference(image, image)
        self.assertEqual(difference.differing_pixels, 0)
        self.assertEqual(difference.differing_fraction, 0.0)
        self.assertEqual(difference.mean_absolute_channel_delta, 0.0)
        self.assertEqual(difference.maximum_channel_delta, 0)

    def test_pixel_difference_rejects_mismatched_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "same dimensions"):
            pixel_difference(
                RgbaImage.solid(1, 2, (0, 0, 0, 0)),
                RgbaImage.solid(2, 1, (0, 0, 0, 0)),
            )


class SeamOverlapTests(unittest.TestCase):
    def test_east_overlap_compares_full_symmetric_gutter(self) -> None:
        center = grid_image(
            [
                [1, 2, 10, 11],
                [3, 4, 12, 13],
                [5, 6, 14, 15],
                [7, 8, 16, 17],
            ]
        )
        east = grid_image(
            [
                [10, 11, 80, 81],
                [12, 13, 82, 83],
                [14, 15, 84, 85],
                [16, 17, 86, 87],
            ]
        )

        difference = seam_overlap(center, east, direction="east", gutter_pixels=1)

        self.assertEqual(difference.pixels, 8)
        self.assertEqual(difference.differing_pixels, 0)
        self.assertEqual(difference.maximum_channel_delta, 0)

    def test_north_overlap_compares_top_to_neighbor_bottom(self) -> None:
        center = grid_image(
            [
                [10, 11, 12, 13],
                [20, 21, 22, 23],
                [30, 31, 32, 33],
                [40, 41, 42, 43],
            ]
        )
        north = grid_image(
            [
                [80, 81, 82, 83],
                [90, 91, 92, 93],
                [10, 11, 12, 13],
                [20, 21, 22, 23],
            ]
        )

        difference = seam_overlap(center, north, direction="north", gutter_pixels=1)

        self.assertEqual(difference.pixels, 8)
        self.assertEqual(difference.differing_pixels, 0)
        self.assertEqual(difference.maximum_channel_delta, 0)

    def test_seam_overlap_reports_a_single_changed_pixel_deterministically(self) -> None:
        center = grid_image([[1, 2, 10, 11], [3, 4, 12, 13], [5, 6, 14, 15], [7, 8, 16, 17]])
        east = grid_image([[10, 11, 80, 81], [12, 13, 82, 83], [14, 15, 84, 85], [16, 18, 86, 87]])

        first = seam_overlap(center, east, direction="east", gutter_pixels=1)
        second = seam_overlap(center, east, direction="east", gutter_pixels=1)

        self.assertEqual(first, second)
        self.assertEqual(first.pixels, 8)
        self.assertEqual(first.differing_pixels, 1)
        self.assertEqual(first.differing_fraction, 0.125)
        self.assertEqual(first.mean_absolute_channel_delta, 3 / 32)
        self.assertEqual(first.maximum_channel_delta, 1)

    def test_seam_overlap_rejects_invalid_inputs(self) -> None:
        square = RgbaImage.solid(4, 4, (0, 0, 0, 255))
        cases = (
            (square, square, "east", 0, "positive gutter"),
            (square, RgbaImage.solid(3, 3, (0, 0, 0, 255)), "east", 1, "same dimensions"),
            (
                RgbaImage.solid(4, 3, (0, 0, 0, 255)),
                RgbaImage.solid(4, 3, (0, 0, 0, 255)),
                "east",
                1,
                "square native tiles",
            ),
            (
                RgbaImage.solid(2, 2, (0, 0, 0, 255)),
                RgbaImage.solid(2, 2, (0, 0, 0, 255)),
                "north",
                1,
                "square native tiles",
            ),
            (square, square, "west", 1, "east or north"),
        )
        for center, neighbor, direction, gutter, message in cases:
            with self.subTest(direction=direction, gutter=gutter, message=message):
                with self.assertRaisesRegex(ValueError, message):
                    seam_overlap(
                        center,
                        neighbor,
                        direction=direction,
                        gutter_pixels=gutter,
                    )


if __name__ == "__main__":
    unittest.main()
