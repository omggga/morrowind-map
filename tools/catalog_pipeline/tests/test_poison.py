from __future__ import annotations

import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.catalog_pipeline.catalog import _aliases, validate_catalog_bundle
from tools.catalog_pipeline.tes3 import PluginInput
from tools.catalog_pipeline.poison import (
    AUDIT_VERSION,
    DATASET_ID,
    SNAPSHOT_ID,
    _artifact,
    _catalog_artifact_metrics,
    _canonical_json_bytes,
    _implementation_audit,
    _json_file_bytes,
    _known_master_size_exception,
    _publish_tree,
    _sha256_bytes,
    validate_catalog,
)


class CatalogDeterminismTests(unittest.TestCase):
    def test_alias_choice_is_independent_of_input_iteration_order(self) -> None:
        forward = _aliases("Primary", ["ÄFoo", "ÄfOO"])
        reverse = _aliases("Primary", ["ÄfOO", "ÄFoo"])

        self.assertEqual(forward, reverse)
        self.assertEqual(forward, ["ÄFoo"])

    def test_source_inventory_order_does_not_change_plugin_load_order(self) -> None:
        from tools.catalog_pipeline import poison

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = []
            for ident, name in (("td", "Tamriel_Data.esm"), ("oaab", "OAAB_Data.esm")):
                payload = name.encode()
                (root / name).write_bytes(payload)
                inputs.append(SimpleNamespace(logical_id=ident, relative_path=name,
                                              sha256=_sha256_bytes(payload)))
            with patch.object(poison, "SOURCE_INPUTS", tuple(inputs)), \
                 patch.object(poison, "CATALOG_SOURCE_IDS", ("oaab", "td")), \
                 patch.object(poison, "CONTENT_FILES", ("OAAB_Data.esm", "Tamriel_Data.esm")):
                plugins = poison._source_descriptors(root)
                self.assertEqual([plugin.name for plugin in plugins], ["OAAB_Data.esm", "Tamriel_Data.esm"])
                (root / "OAAB_Data.esm").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    poison._source_descriptors(root)
                with patch.object(poison, "SOURCE_INPUTS", tuple(inputs[:1])):
                    with self.assertRaisesRegex(RuntimeError, "do not match"):
                        poison._source_descriptors(root)

    def test_master_size_exception_is_explicit_and_hash_bound(self) -> None:
        dependent = PluginInput("TR_Mainland.esm", Path("TR_Mainland.esm"), "a" * 64)
        master = PluginInput("Tamriel_Data.esm", Path("Tamriel_Data.esm"), "b" * 64)
        exception = {
            "dependentSha256": dependent.sha256,
            "masterSha256": master.sha256,
            "advertisedBytes": 10,
            "actualBytes": 11,
            "reason": "fixture-mast-size",
        }

        with patch("tools.catalog_pipeline.poison.MASTER_SIZE_EXCEPTIONS", (exception,)):
            self.assertEqual(
                _known_master_size_exception(
                    dependent=dependent,
                    master=master,
                    advertised_size=10,
                    actual_size=11,
                ),
                "fixture-mast-size",
            )
            self.assertIsNone(
                _known_master_size_exception(
                    dependent=dependent,
                    master=master,
                    advertised_size=10,
                    actual_size=12,
                )
            )


class PoisonCatalogValidationTests(unittest.TestCase):
    @staticmethod
    def _write_fixture(root: Path, *, include_place: bool) -> dict[str, object]:
        place = {
            "id": f"{DATASET_ID}.place-a",
            "regionId": "vvardenfell",
            "type": "other",
            "mapPosition": [100.0, 200.0],
            "exteriorCell": [0, 0],
            "mimCategory": None,
            "minZoom": 4,
            "entrances": [],
            "sources": [
                {
                    "kind": "esm",
                    "plugin": "Morrowind.esm",
                    "recordId": "Fixture",
                    "mimIndex": None,
                }
            ],
        }
        locale_place = {
            "placeId": f"{DATASET_ID}.place-a",
            "name": "Fixture",
            "aliases": [],
        }
        locations = {
            "schemaVersion": 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "places": [place] if include_place else [],
        }
        english = {
            "schemaVersion": 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "locale": "en",
            "places": [locale_place] if include_place else [],
        }
        locations_bytes = _json_file_bytes(locations)
        english_bytes = _json_file_bytes(english)
        artifacts = {
            "locations": _artifact(locations_bytes, "locations.json"),
            "english": _artifact(english_bytes, "locales/en.json"),
        }
        policy = {"fixture": "v1"}
        policy_fingerprint = _sha256_bytes(_canonical_json_bytes(policy))
        inputs = [{"name": "Morrowind.esm"}]
        repo_root = Path(__file__).resolve().parents[3]
        extractor = _implementation_audit(repo_root)
        valid_locations = {**locations, "places": [place]}
        valid_english = {**english, "places": [locale_place]}
        grouping = _catalog_artifact_metrics(valid_locations, valid_english)
        grouping["byTypeRule"] = {"fallback:landmark": 1}
        semantic_gates = validate_catalog_bundle(
            valid_locations,
            valid_english,
            known_plugins={"morrowind.esm"},
        )
        inventory = {
            "schemaVersion": 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "inputs": inputs,
            "implementationSha256": extractor["sha256"],
            "policyFingerprint": policy_fingerprint,
            "artifacts": artifacts,
        }
        inventory_sha256 = _sha256_bytes(_canonical_json_bytes(inventory))
        audit_core = {
            "schemaVersion": 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "auditVersion": AUDIT_VERSION,
            "catalogInventorySha256": inventory_sha256,
            "inventory": inventory,
            "inputs": inputs,
            "extractor": extractor,
            "policy": policy,
            "policyFingerprint": policy_fingerprint,
            "records": {},
            "resolution": {},
            "grouping": grouping,
            "exclusions": {},
            "integrity": {
                **semantic_gates,
                "expectedWorldCounts": True,
                "expectedCatalogCounts": True,
                "expectedResolutionCounts": True,
                "expectedRegionCounts": True,
                "expectedExclusions": True,
                "canonicalJsonWithLf": True,
                "allCoordinatesWithinManifestExtent": True,
                "artifacts": artifacts,
            },
            "passes": True,
        }
        audit = {
            **audit_core,
            "auditSha256": _sha256_bytes(_canonical_json_bytes(audit_core)),
        }
        (root / "locales").mkdir(parents=True)
        (root / "locations.json").write_bytes(locations_bytes)
        (root / "locales/en.json").write_bytes(english_bytes)
        (root / "catalog-audit.json").write_bytes(_json_file_bytes(audit))
        return grouping

    def test_validator_rechecks_contract_after_all_self_hashes_are_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            valid_root = Path(directory) / "valid"
            invalid_root = Path(directory) / "invalid"
            valid_root.mkdir()
            invalid_root.mkdir()
            grouping = self._write_fixture(valid_root, include_place=True)
            self._write_fixture(invalid_root, include_place=False)
            catalog_counts = {
                key: grouping[key]
                for key in (
                    "places",
                    "interiorPlaces",
                    "namedExteriorCells",
                    "namedExteriorPlaces",
                    "entrances",
                    "multiEntrancePlaces",
                    "entrancesInMultiEntrancePlaces",
                    "maximumEntrancesPerPlace",
                    "aliases",
                    "byRegion",
                    "byType",
                )
            }
            region_counts = {
                key: grouping[key]
                for key in (
                    "entrancesByRegion",
                    "interiorPlacesByRegion",
                    "namedExteriorPlacesByRegion",
                )
            }
            with (
                patch("tools.catalog_pipeline.poison.EXPECTED_WORLD_COUNTS", {}),
                patch("tools.catalog_pipeline.poison.EXPECTED_CATALOG_COUNTS", catalog_counts),
                patch("tools.catalog_pipeline.poison.EXPECTED_RESOLUTION_COUNTS", {}),
                patch("tools.catalog_pipeline.poison.EXPECTED_REGION_COUNTS", region_counts),
                patch("tools.catalog_pipeline.poison.EXPECTED_EXCLUSIONS", {}),
            ):
                self.assertEqual(len(validate_catalog(valid_root).inventory_sha256), 64)
                with self.assertRaisesRegex(ValueError, "published catalog"):
                    validate_catalog(invalid_root)

    def test_immutable_publisher_rejects_root_and_nested_symlinks(self) -> None:
        artifacts = {Path("artifact.json"): b"{}\n"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = root / "actual"
            actual.mkdir()
            (actual / "artifact.json").write_bytes(b"{}\n")
            linked_root = root / "linked"
            try:
                linked_root.symlink_to(actual, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "symlink"):
                _publish_tree(linked_root, artifacts, boundary=root)

            nested = root / "nested"
            nested.mkdir()
            (nested / "artifact.json").symlink_to(actual / "artifact.json")
            with self.assertRaisesRegex(ValueError, "symlink"):
                _publish_tree(nested, artifacts, boundary=root)


if __name__ == "__main__":
    unittest.main()
