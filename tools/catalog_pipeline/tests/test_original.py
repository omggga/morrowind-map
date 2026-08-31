from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.catalog_pipeline.original import (
    DATASET_ID,
    DEFAULT_SOURCE_ROOT,
    EXPECTED_CATALOG_COUNTS,
    EXPECTED_RESOLUTION_COUNTS,
    INPUT_FINGERPRINT,
    PINNED_INPUTS,
    SNAPSHOT_ID,
    _parser,
    _source_descriptors,
    build_original_catalog,
)


class OriginalCatalogContractTests(unittest.TestCase):
    def test_identity_is_derived_from_exact_en_base_trio(self) -> None:
        self.assertEqual(DATASET_ID, "original-goty-hd")
        self.assertEqual(
            [(source.name, source.relative_path, source.bytes, source.sha256) for source in PINNED_INPUTS],
            [
                (
                    "Morrowind.esm",
                    "bsa/Morrowind.esm",
                    79_837_557,
                    "5c3c8c2cbd20e25901b59b3ece33d36b7ef0e3d60ad8d11828bcc61a5ead1647",
                ),
                (
                    "Tribunal.esm",
                    "bsa/Tribunal.esm",
                    4_565_686,
                    "2ace511f23cc2a9ddd5f3aa59c7919789b9378cf4b17c8ae3375dd6b782f3f2b",
                ),
                (
                    "Bloodmoon.esm",
                    "bsa/Bloodmoon.esm",
                    9_631_798,
                    "bd27090d0e6ad4c1bf1abc83f1a2dac56fcc82cae7bfe8263c413fb301801357",
                ),
            ],
        )
        self.assertEqual(
            INPUT_FINGERPRINT,
            "e1647b0b9a967ad04b3810f728efc9cfcac302e8268042789342d98a573aed63",
        )
        self.assertEqual(SNAPSHOT_ID, "original:goty:8b2690c0ce1c954e")

    def test_cli_has_no_alternate_content_root_option(self) -> None:
        parser = _parser(Path("/repo"))
        with self.assertRaises(SystemExit):
            parser.parse_args(["build", "--source-root", "/untrusted"])

    def test_source_loader_rejects_any_other_content_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "refusing alternate content path"):
                _source_descriptors(Path(directory))

    def test_pinned_counts_include_full_en_catalog_and_zero_drop_resolution(self) -> None:
        self.assertEqual(EXPECTED_CATALOG_COUNTS["places"], 1036)
        self.assertEqual(EXPECTED_CATALOG_COUNTS["entrances"], 1205)
        self.assertEqual(
            EXPECTED_CATALOG_COUNTS["byRegion"],
            {"solstheim": 92, "vvardenfell": 944},
        )
        self.assertEqual(EXPECTED_RESOLUTION_COUNTS["namedTeleportCandidates"], 1205)
        self.assertEqual(EXPECTED_RESOLUTION_COUNTS["resolvedDoorBases"], 1205)
        self.assertEqual(EXPECTED_RESOLUTION_COUNTS["resolvedDestinationCells"], 1205)

    @unittest.skipUnless(
        all((DEFAULT_SOURCE_ROOT / source.relative_path).is_file() for source in PINNED_INPUTS),
        "Pinned Original GOTY source files are not available",
    )
    def test_real_pinned_inputs_build_expected_en_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog"
            result = build_original_catalog(
                source_root=DEFAULT_SOURCE_ROOT,
                output_root=output,
                repo_root=Path(__file__).resolve().parents[3],
            )
            self.assertTrue((output / "locales/en.json").is_file())
            self.assertFalse((output / "locales/ru.json").exists())
        grouping = result.audit["grouping"]
        self.assertEqual(grouping["places"], 1036)
        self.assertEqual(grouping["entrances"], 1205)
        self.assertEqual(grouping["byRegion"], {"solstheim": 92, "vvardenfell": 944})
        self.assertEqual(result.audit["resolution"]["resolvedDestinationCells"], 1205)
        self.assertEqual(result.audit["exclusions"]["unreachableInteriorCells"], 388)
        self.assertTrue(result.audit["integrity"]["zeroUnresolvedDestinations"])

    def test_source_loader_checks_pinned_byte_count_before_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            data_root = source_root / "bsa"
            data_root.mkdir()
            for source in PINNED_INPUTS:
                (source_root / source.relative_path).write_bytes(b"wrong")
            with (
                patch("tools.catalog_pipeline.original.DEFAULT_SOURCE_ROOT", source_root.resolve()),
                patch("tools.catalog_pipeline.original._sha256_file") as sha256_file,
            ):
                with self.assertRaisesRegex(ValueError, "size mismatch"):
                    _source_descriptors(source_root)
                sha256_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
