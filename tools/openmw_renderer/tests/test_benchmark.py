from __future__ import annotations

import unittest

from tools.land_renderer.spike import CONTROL_SITES
from tools.openmw_renderer.benchmark import (
    PRODUCTION_SEAM_MAX_CHANNEL_DELTA,
    PRODUCTION_SEAM_MAX_DIFFERING_FRACTION,
    PRODUCTION_SEAM_MAX_MEAN_CHANNEL_DELTA,
    _seam_passes,
    control_cells,
    control_shards,
)


class ProductionBenchmarkTests(unittest.TestCase):
    def test_five_controls_expand_to_five_complete_disjoint_3x3_shards(self) -> None:
        shards = control_shards()
        cells = control_cells()

        self.assertEqual(len(shards), 5)
        self.assertEqual(len(cells), 45)
        self.assertTrue(all(len(shard.targets) == 9 for shard in shards))
        self.assertTrue(all(site.cell in cells for site in CONTROL_SITES))

    def test_production_seam_tolerance_is_bounded(self) -> None:
        boundary = {
            "differingFraction": PRODUCTION_SEAM_MAX_DIFFERING_FRACTION,
            "mean_absolute_channel_delta": PRODUCTION_SEAM_MAX_MEAN_CHANNEL_DELTA,
            "maximum_channel_delta": PRODUCTION_SEAM_MAX_CHANNEL_DELTA,
        }

        self.assertTrue(_seam_passes(boundary))
        self.assertFalse(
            _seam_passes(
                {
                    **boundary,
                    "mean_absolute_channel_delta": (
                        PRODUCTION_SEAM_MAX_MEAN_CHANNEL_DELTA + 0.001
                    ),
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
