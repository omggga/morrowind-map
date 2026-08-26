from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from tools.data_pipeline.build_original import canonical_position, canonical_solstheim_extent
from tools.data_pipeline.esm import extract_world_data
from tools.data_pipeline.mim import classify_place, parse_mim_locations


def subrecord(name: bytes, value: bytes) -> bytes:
    return name + struct.pack("<I", len(value)) + value


class MimParserTests(unittest.TestCase):
    def test_reads_cp1251_location_blocks_without_losing_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mwmain.gdb"
            path.write_text(
                "loc\r\n nm = Балмора\r\n pc = 19\r\n dl = 0\r\n pd = -20000,-12000\r\nend\r\n",
                encoding="cp1251",
            )

            locations = parse_mim_locations(path)

        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0].name, "Балмора")
        self.assertEqual(locations[0].position, (-20_000, -12_000))
        self.assertEqual(classify_place(locations[0].category, locations[0].name), "settlement")
        self.assertEqual(classify_place(None, "Balmora, Guild of Fighters"), "guild")


class EsmParserTests(unittest.TestCase):
    def test_extracts_only_exterior_teleport_references(self) -> None:
        payload = b"".join(
            (
                subrecord(b"NAME", b"Balmora\0"),
                subrecord(b"DATA", struct.pack("<Iii", 2, -3, -2)),
                subrecord(b"FRMR", struct.pack("<I", 42)),
                subrecord(b"NAME", b"door_fixture\0"),
                subrecord(b"DNAM", b"Balmora, Fixture House\0"),
                subrecord(b"DATA", struct.pack("<6f", -20_000, -12_000, 0, 0, 0, 0)),
            )
        )
        record = b"CELL" + struct.pack("<III", len(payload), 0, 0) + payload
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Fixture.esm"
            path.write_bytes(record)

            world = extract_world_data(path)

        self.assertEqual(len(world.teleports), 1)
        self.assertEqual(world.teleports[0].destination, "Balmora, Fixture House")
        self.assertEqual(world.teleports[0].exterior_cell, (-3, -2))
        self.assertEqual(world.named_exterior_cells[0].name, "Balmora")


class GeoreferenceTests(unittest.TestCase):
    def test_keeps_vvardenfell_and_maps_bloodmoon_logical_space_to_tes3(self) -> None:
        self.assertEqual(canonical_position("vvardenfell", (-20_000, -12_000)), (-20_000, -12_000))
        x, y = canonical_position("solstheim", (-125_000, -130_000))
        self.assertAlmostEqual(x, -229_547.3274585)
        self.assertAlmostEqual(y, 115_992.353777)

    def test_uses_the_exact_bloodmoon_cell_grid_extent_for_the_raster(self) -> None:
        self.assertEqual(
            canonical_solstheim_extent(),
            (-229_376.0, 114_688.0, -131_072.0, 237_568.0),
        )


if __name__ == "__main__":
    unittest.main()
