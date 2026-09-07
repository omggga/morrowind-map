from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tools.tr_release.candidate import (
    activate_candidate,
    build_candidate,
    canonical_json_bytes,
    verify_candidate,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _artifact(payload: bytes, *, url: str | None = None, path: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }
    if url is not None:
        value.update({"url": url, "mediaType": "application/json"})
    if path is not None:
        value["path"] = path
    return value


class CandidateFixture:
    dataset_id = "tamriel-rebuilt-27.01"
    snapshot_id = "tr:tamriel-rebuilt-27.01:0123456789abcdef"
    current_tr_id = "poison-song-26.08"
    original_id = "original-goty-hd"
    extent = [-8192, -16384, 24576, 32768]
    origin = [-8192, 32768]
    resolutions = [128, 64, 32, 16]

    def __init__(self, root: Path) -> None:
        self.root = root
        self.active_root = root / "active"
        self.generated_root = root / "generated"
        self.metadata_root = root / "metadata"
        self.candidate_root = root / "candidate"
        self.active_manifests = self.active_root / "manifests"
        self.active_manifests.mkdir(parents=True)
        self.generated_root.mkdir()
        self.metadata_root.mkdir()

        self.original_manifest = {
            "schemaVersion": 1,
            "datasetId": self.original_id,
            "mapKey": "original",
            "snapshotId": "original:goty:immutable",
        }
        self.current_tr_manifest = {
            "schemaVersion": 1,
            "datasetId": self.current_tr_id,
            "mapKey": "tamriel-rebuilt",
            "snapshotId": "tr:poison-song-26.08:old",
        }
        self._write(
            self.active_manifests / f"{self.original_id}.json",
            self.original_manifest,
            canonical=False,
        )
        self._write(
            self.active_manifests / f"{self.current_tr_id}.json",
            self.current_tr_manifest,
            canonical=False,
        )
        self.active_index = {
            "schemaVersion": 1,
            "defaultDatasetId": self.original_id,
            "datasets": [
                {
                    "datasetId": self.original_id,
                    "manifestUrl": f"/datasets/manifests/{self.original_id}.json",
                    "order": 0,
                },
                {
                    "datasetId": self.current_tr_id,
                    "manifestUrl": f"/datasets/manifests/{self.current_tr_id}.json",
                    "order": 1,
                },
            ],
        }
        self._write(self.active_root / "index.json", self.active_index, canonical=False)
        self.original_artifact = self.active_root / "generated" / self.original_id / "keep.bin"
        self.original_artifact.parent.mkdir(parents=True)
        self.original_artifact.write_bytes(b"immutable original artifact")

        self.profile: dict[str, Any] = {
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "mapKey": "tamriel-rebuilt",
            "title": {"en": "Tamriel Rebuilt 27.01"},
            "summary": {"en": "Pinned current Tamriel Rebuilt release."},
            "release": {"name": "Example", "version": "27.01", "build": None},
            "regions": [
                {
                    "id": "vvardenfell",
                    "title": {"en": "Vvardenfell"},
                    "kind": "exterior",
                    "status": "available",
                },
                {
                    "id": "tr-mainland",
                    "title": {"en": "TR Mainland"},
                    "kind": "exterior",
                    "status": "available",
                },
            ],
            "dataDirectories": [
                {"id": "base-game", "order": 0, "status": "confirmed"},
                {"id": "tamriel-data-27.01", "order": 1, "status": "confirmed"},
                {"id": "tamriel-rebuilt-27.01", "order": 2, "status": "confirmed"},
            ],
            "fallbackArchives": [
                {
                    "name": "Morrowind.bsa",
                    "sha256": "1" * 64,
                    "order": 0,
                    "required": True,
                    "registered": True,
                }
            ],
            "contentFiles": [
                {
                    "name": "Morrowind.esm",
                    "kind": "esm",
                    "version": None,
                    "sha256": "2" * 64,
                    "loadOrder": 0,
                    "inclusion": "required",
                    "enabled": True,
                },
                {
                    "name": "TR_Mainland.esm",
                    "kind": "esm",
                    "version": "27.01",
                    "sha256": "3" * 64,
                    "loadOrder": 1,
                    "inclusion": "required",
                    "enabled": True,
                },
            ],
            "excludedModules": [
                {
                    "id": "tr-factions",
                    "status": "disabled",
                    "notes": ["Excluded from the canonical core-only profile."],
                }
            ],
        }
        self.lock: dict[str, Any] = {
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "map": {
                "extent": list(self.extent),
                "center": [8192, 8192],
                "origin": list(self.origin),
                "resolutions": list(self.resolutions),
                "producer": {
                    "rendererFingerprint": "8" * 64,
                    "productionSourceFingerprint": "9" * 64,
                },
            },
            "catalog": {"implementationSha256": "7" * 64},
        }
        self._prepare_basemap()
        self._prepare_catalog()

    @staticmethod
    def _write(path: Path, value: object, *, canonical: bool = True) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            canonical_json_bytes(value)
            if canonical
            else (json.dumps(value, indent=2) + "\n").encode("utf-8")
        )
        path.write_bytes(payload)
        return payload

    def _prepare_basemap(self) -> None:
        inventory = "a" * 64
        metadata_version = self.metadata_root / self.dataset_id / inventory
        generated_version = self.generated_root / self.dataset_id / inventory
        tile = generated_version / "tiles/0/0/0.webp"
        tile.parent.mkdir(parents=True)
        tile.write_bytes(b"webp fixture")
        self.tile_path = tile

        tile_record = {
            "bytes": len(tile.read_bytes()),
            "path": "tiles/0/0/0.webp",
            "sha256": _sha256(tile.read_bytes()),
            "x": 0,
            "y": 0,
            "z": 0,
        }
        tiles_bytes = canonical_json_bytes(tile_record)
        metadata_version.mkdir(parents=True, exist_ok=True)
        self.tiles_inventory_path = metadata_version / "tiles.ndjson"
        self.tiles_inventory_path.write_bytes(tiles_bytes)

        support_bytes = b"quality evidence\n"
        (metadata_version / "quality-evidence.txt").parent.mkdir(parents=True, exist_ok=True)
        (metadata_version / "quality-evidence.txt").write_bytes(support_bytes)
        quality_core = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "passes": True,
            "gates": {
                "inventory": {
                    "inventorySha256": inventory,
                    "passes": True,
                    "tileCount": 1,
                    "totalBytes": len(tile.read_bytes()),
                }
            },
            "artifacts": {
                "fixture": _artifact(support_bytes, path="quality-evidence.txt"),
                "tiles": _artifact(tiles_bytes, path="tiles.ndjson"),
            },
        }
        quality = {
            **quality_core,
            "auditSha256": _sha256(canonical_json_bytes(quality_core)[:-1]),
        }
        quality_bytes = self._write(metadata_version / "basemap-audit.json", quality)

        coverage = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "tileCount": 1,
        }
        coverage_bytes = self._write(metadata_version / "tile-coverage.json", coverage)
        receipt = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
        }
        receipt_bytes = self._write(metadata_version / "seam-stabilization.json", receipt)

        metadata_url = f"/datasets/metadata/{self.dataset_id}/{inventory}"
        map_assets = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "projection": "TES3:WORLD",
            "rasters": [],
            "tilePyramids": [
                {
                    "id": f"{self.dataset_id}.basemap",
                    "regionIds": ["vvardenfell", "tr-mainland"],
                    "kind": "xyz-pyramid",
                    "urlTemplate": (
                        f"/datasets/generated/{self.dataset_id}/{inventory}"
                        "/tiles/{z}/{x}/{y}.webp"
                    ),
                    "mediaType": "image/webp",
                    "tileSize": 512,
                    "extent": list(self.extent),
                    "origin": list(self.origin),
                    "resolutions": list(self.resolutions),
                    "minZoom": 0,
                    "maxZoom": len(self.resolutions) - 1,
                    "sparse": True,
                    "coverage": _artifact(
                        coverage_bytes, url=f"{metadata_url}/tile-coverage.json"
                    ),
                    "qualityReport": _artifact(
                        quality_bytes, url=f"{metadata_url}/basemap-audit.json"
                    ),
                    "derivation": {
                        "receipt": _artifact(
                            receipt_bytes,
                            url=f"{metadata_url}/seam-stabilization.json",
                        )
                    },
                    "integrity": {
                        "inventorySha256": inventory,
                        "productionSourceFingerprint": "9" * 64,
                        "rendererFingerprint": "8" * 64,
                        "tileCount": 1,
                        "totalBytes": len(tile.read_bytes()),
                    },
                }
            ],
        }
        self.map_assets_path = metadata_version / "map-assets.json"
        self._write(self.map_assets_path, map_assets)

    def _prepare_catalog(self) -> None:
        locations = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "places": [],
        }
        english = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "locale": "en",
            "places": [],
        }
        locations_bytes = canonical_json_bytes(locations)
        english_bytes = canonical_json_bytes(english)
        inventory = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "implementationSha256": "7" * 64,
            "artifacts": {
                "locations": _artifact(locations_bytes, path="locations.json"),
                "english": _artifact(english_bytes, path="locales/en.json"),
            },
        }
        inventory_sha = _sha256(canonical_json_bytes(inventory)[:-1])
        audit_core = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "snapshotId": self.snapshot_id,
            "catalogInventorySha256": inventory_sha,
            "exclusions": {},
            "inventory": inventory,
            "extractor": {"sha256": "7" * 64},
            "grouping": {},
            "passes": True,
            "records": {},
            "resolution": {},
        }
        audit = {
            **audit_core,
            "auditSha256": _sha256(canonical_json_bytes(audit_core)[:-1]),
        }
        generated_version = (
            self.generated_root / self.dataset_id / "catalogs" / inventory_sha
        )
        self.locations_path = generated_version / "locations.json"
        self.english_path = generated_version / "locales/en.json"
        self.locations_path.parent.mkdir(parents=True, exist_ok=True)
        self.english_path.parent.mkdir(parents=True, exist_ok=True)
        self.locations_path.write_bytes(locations_bytes)
        self.english_path.write_bytes(english_bytes)
        self.catalog_audit_path = (
            self.metadata_root
            / self.dataset_id
            / "catalogs"
            / inventory_sha
            / "catalog-audit.json"
        )
        self._write(self.catalog_audit_path, audit)

    def build(self):
        return build_candidate(
            self.profile,
            self.lock,
            generated_root=self.generated_root,
            metadata_root=self.metadata_root,
            active_datasets_root=self.active_root,
            candidate_root=self.candidate_root,
        )

    def verify(self):
        return verify_candidate(
            self.profile,
            self.lock,
            generated_root=self.generated_root,
            metadata_root=self.metadata_root,
            active_datasets_root=self.active_root,
            candidate_root=self.candidate_root,
        )

    def activate(self):
        return activate_candidate(
            self.profile,
            self.lock,
            generated_root=self.generated_root,
            metadata_root=self.metadata_root,
            active_datasets_root=self.active_root,
            candidate_root=self.candidate_root,
        )


class CandidateReleaseTests(unittest.TestCase):
    def test_build_accepts_cli_active_path_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))

            bundle = build_candidate(
                fixture.profile,
                fixture.lock,
                generated_root=fixture.generated_root,
                metadata_root=fixture.metadata_root,
                active_index_path=fixture.active_root / "index.json",
                active_manifests_root=fixture.active_manifests,
                candidate_root=fixture.candidate_root,
            )

            self.assertEqual(bundle.dataset_id, fixture.dataset_id)
            self.assertEqual(bundle.to_dict()["manifest"], str(bundle.manifest_path))

    def test_build_accepts_plain_current_profile_and_lock_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            profile = copy.deepcopy(fixture.profile)
            profile["dataDirectories"] = [
                {"id": "base-game", "path": "base"},
                {"id": "tamriel-rebuilt-core", "path": "tr-core"},
            ]
            profile["contentFiles"] = ["Morrowind.esm", "TR_Mainland.esm"]
            profile["fallbackArchives"] = ["Morrowind.bsa"]
            profile["requiredInputs"] = [
                {
                    "id": "morrowind-esm",
                    "directoryId": "base-game",
                    "filename": "Morrowind.esm",
                },
                {
                    "id": "tr-mainland-esm",
                    "directoryId": "tamriel-rebuilt-core",
                    "filename": "TR_Mainland.esm",
                },
                {
                    "id": "morrowind-bsa",
                    "directoryId": "base-game",
                    "filename": "Morrowind.bsa",
                },
            ]
            profile["excludedOptionalModules"] = [
                {"id": "tr-factions", "relativePath": "optional/TR_Factions.esp"}
            ]
            del profile["excludedModules"]
            lock = copy.deepcopy(fixture.lock)
            lock["renderer"] = lock.pop("map")
            lock["source"] = {
                "inputs": [
                    {
                        "id": "morrowind-esm",
                        "directoryId": "base-game",
                        "filename": "Morrowind.esm",
                        "relativePath": "base/Morrowind.esm",
                        "bytes": 1,
                        "sha256": "2" * 64,
                    },
                    {
                        "id": "tr-mainland-esm",
                        "directoryId": "tamriel-rebuilt-core",
                        "filename": "TR_Mainland.esm",
                        "relativePath": "tr-core/TR_Mainland.esm",
                        "bytes": 1,
                        "sha256": "3" * 64,
                    },
                    {
                        "id": "morrowind-bsa",
                        "directoryId": "base-game",
                        "filename": "Morrowind.bsa",
                        "relativePath": "base/Morrowind.bsa",
                        "bytes": 1,
                        "sha256": "1" * 64,
                    },
                ],
                "dataTrees": [],
            }

            bundle = build_candidate(
                profile,
                lock,
                generated_root=fixture.generated_root,
                metadata_root=fixture.metadata_root,
                active_datasets_root=fixture.active_root,
                candidate_root=fixture.candidate_root,
            )

            manifest = json.loads(bundle.manifest_path.read_bytes())
            self.assertEqual(
                [item["name"] for item in manifest["profile"]["contentFiles"]],
                ["Morrowind.esm", "TR_Mainland.esm", "TR_Factions.esp"],
            )
            self.assertEqual(
                manifest["profile"]["contentFiles"][1]["sha256"], "3" * 64
            )
            self.assertEqual(
                manifest["profile"]["registeredArchives"][0]["sha256"], "1" * 64
            )
            self.assertEqual(
                [item["id"] for item in manifest["profile"]["dataDirectories"]],
                ["base-game", "tamriel-rebuilt-core"],
            )

    def test_build_creates_canonical_inactive_candidate_bound_to_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            active_index_before = (fixture.active_root / "index.json").read_bytes()
            active_manifests_before = {
                path.name: path.read_bytes() for path in fixture.active_manifests.iterdir()
            }

            bundle = fixture.build()

            self.assertEqual(
                (fixture.active_root / "index.json").read_bytes(), active_index_before
            )
            self.assertEqual(
                {path.name: path.read_bytes() for path in fixture.active_manifests.iterdir()},
                active_manifests_before,
            )
            self.assertFalse(
                (fixture.active_manifests / f"{fixture.dataset_id}.json").exists()
            )
            manifest_bytes = bundle.manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
            self.assertEqual(manifest_bytes, canonical_json_bytes(manifest))
            self.assertNotIn("mimImport", manifest["artifacts"])
            self.assertEqual(
                manifest["artifacts"]["locations"]["bytes"],
                len(fixture.locations_path.read_bytes()),
            )
            self.assertEqual(
                manifest["artifacts"]["tiles"]["sha256"],
                _sha256(fixture.map_assets_path.read_bytes()),
            )
            self.assertEqual(fixture.verify(), bundle)

    def test_add_cyrodiil_preserves_original_and_tr_and_can_be_updated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            baseline = json.loads((fixture.active_root / "index.json").read_bytes())
            fixture.profile["mapKey"] = "project-cyrodiil"
            bundle = fixture.build()
            index = json.loads(bundle.index_path.read_bytes())
            self.assertEqual(index["datasets"][:2], baseline["datasets"])
            self.assertEqual(index["datasets"][2]["datasetId"], fixture.dataset_id)
            self.assertEqual(json.loads(bundle.manifest_path.read_bytes())["mapKey"], "project-cyrodiil")
            fixture.activate()
            from tools.tr_release.candidate import _active_state, _candidate_index
            state = _active_state(fixture.active_root)
            updated = _candidate_index(dataset_id="cyrodiil-next", state=state, map_key="project-cyrodiil")
            self.assertEqual(updated["datasets"][:2], baseline["datasets"])
            self.assertEqual(len(updated["datasets"]), 3)
            tr = _candidate_index(dataset_id="tr-next", state=state)
            self.assertEqual(tr["datasets"][2], index["datasets"][2])
            skyrim = _candidate_index(dataset_id="dragonstar-25.05", state=state, map_key="home-of-nords")
            self.assertEqual(skyrim["datasets"][:3], index["datasets"])
            self.assertEqual(skyrim["datasets"][3]["order"], 3)
            sky_manifest = fixture.active_root / "manifests/dragonstar-25.05.json"
            sky_manifest.write_text(json.dumps({"datasetId": "dragonstar-25.05", "mapKey": "home-of-nords"}))
            (fixture.active_root / "index.json").write_text(json.dumps(skyrim))
            state = _active_state(fixture.active_root)
            updated = _candidate_index(dataset_id="dragonstar-next", state=state, map_key="home-of-nords")
            self.assertEqual(updated["datasets"][:3], index["datasets"])
            self.assertEqual(len(updated["datasets"]), 4)
            tr = _candidate_index(dataset_id="tr-next", state=state)
            self.assertEqual(tr["datasets"][2:], skyrim["datasets"][2:])
            azurian = _candidate_index(dataset_id="azurian-isles-0.3.1", state=state, map_key="azurian-isles")
            self.assertEqual(azurian["datasets"][:4], skyrim["datasets"])
            az_manifest = fixture.active_root / "manifests/azurian-isles-0.3.1.json"
            az_manifest.write_text(json.dumps({"datasetId": "azurian-isles-0.3.1", "mapKey": "azurian-isles"}))
            (fixture.active_root / "index.json").write_text(json.dumps(azurian))
            state = _active_state(fixture.active_root)
            updated = _candidate_index(dataset_id="azurian-isles-next", state=state, map_key="azurian-isles")
            self.assertEqual(updated["datasets"][:4], skyrim["datasets"])
            self.assertEqual(updated["datasets"][4]["order"], 4)
            tr = _candidate_index(dataset_id="tr-next", state=state)
            self.assertEqual(tr["datasets"][2:], azurian["datasets"][2:])

    def test_verify_fails_closed_when_a_bound_artifact_is_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            fixture.build()
            fixture.locations_path.write_bytes(fixture.locations_path.read_bytes() + b" ")

            with self.assertRaisesRegex(ValueError, "Locations artifact .* changed"):
                fixture.verify()

    def test_verify_fails_closed_when_a_published_tile_is_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            fixture.build()
            fixture.tile_path.write_bytes(b"tampered WebP payload")

            with self.assertRaisesRegex(ValueError, "Published tile .* changed"):
                fixture.verify()

    def test_verify_rejects_missing_extra_and_symlinked_tiles(self) -> None:
        cases = ("missing", "extra", "symlink")
        for case in cases:
            if case == "symlink" and not hasattr(os, "symlink"):
                continue
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                fixture = CandidateFixture(Path(directory))
                fixture.build()
                if case == "missing":
                    fixture.tile_path.unlink()
                    expected = "missing published tiles"
                elif case == "extra":
                    extra = fixture.tile_path.with_name("1.webp")
                    extra.write_bytes(b"unexpected tile")
                    expected = "unexpected published tile"
                else:
                    outside = fixture.root / "outside.webp"
                    outside.write_bytes(b"outside tile")
                    fixture.tile_path.unlink()
                    fixture.tile_path.symlink_to(outside)
                    expected = "symlink"

                with self.assertRaisesRegex(ValueError, expected):
                    fixture.verify()

    def test_candidate_rejects_producer_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            fixture.lock["map"]["producer"]["rendererFingerprint"] = "6" * 64
            with self.assertRaisesRegex(ValueError, "Renderer fingerprint"):
                fixture.build()

        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            fixture.lock["catalog"]["implementationSha256"] = "6" * 64
            with self.assertRaisesRegex(ValueError, "implementation"):
                fixture.build()

    def test_build_rejects_current_active_tr_dataset_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            profile = copy.deepcopy(fixture.profile)
            profile["datasetId"] = fixture.current_tr_id
            lock = copy.deepcopy(fixture.lock)
            lock["datasetId"] = fixture.current_tr_id

            with self.assertRaisesRegex(ValueError, "new datasetId"):
                build_candidate(
                    profile,
                    lock,
                    generated_root=fixture.generated_root,
                    metadata_root=fixture.metadata_root,
                    active_datasets_root=fixture.active_root,
                    candidate_root=fixture.candidate_root,
                )

    def test_activation_preserves_original_and_switches_index_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            bundle = fixture.build()
            original_manifest_path = (
                fixture.active_manifests / f"{fixture.original_id}.json"
            )
            original_manifest_before = original_manifest_path.read_bytes()
            original_artifact_before = fixture.original_artifact.read_bytes()
            candidate_manifest_before = bundle.manifest_path.read_bytes()

            activated = fixture.activate()

            self.assertEqual(activated, bundle)
            self.assertEqual(original_manifest_path.read_bytes(), original_manifest_before)
            self.assertEqual(fixture.original_artifact.read_bytes(), original_artifact_before)
            self.assertEqual(
                (fixture.active_manifests / f"{fixture.dataset_id}.json").read_bytes(),
                candidate_manifest_before,
            )
            index = json.loads((fixture.active_root / "index.json").read_bytes())
            self.assertEqual(
                [entry["datasetId"] for entry in index["datasets"]],
                [fixture.original_id, fixture.dataset_id],
            )
            self.assertEqual(index["defaultDatasetId"], fixture.original_id)

    def test_activation_rejects_canonical_candidate_tampering_before_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            bundle = fixture.build()
            active_index_before = (fixture.active_root / "index.json").read_bytes()
            manifest = json.loads(bundle.manifest_path.read_bytes())
            manifest["title"]["en"] = "Changed before verification"
            bundle.manifest_path.write_bytes(canonical_json_bytes(manifest))

            with self.assertRaisesRegex(ValueError, "Candidate manifest differs"):
                fixture.activate()

            self.assertEqual(
                (fixture.active_root / "index.json").read_bytes(), active_index_before
            )
            self.assertFalse(
                (fixture.active_manifests / f"{fixture.dataset_id}.json").exists()
            )

    def test_activation_stages_verified_bytes_after_candidate_files_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            bundle = fixture.build()
            verified_manifest = bundle.manifest_path.read_bytes()
            verified_index = bundle.index_path.read_bytes()
            original_verify = verify_candidate

            def verify_then_tamper(*args, **kwargs):
                verified = original_verify(*args, **kwargs)
                manifest = json.loads(verified.manifest_path.read_bytes())
                manifest["title"]["en"] = "Changed after verification"
                verified.manifest_path.write_bytes(canonical_json_bytes(manifest))
                index = json.loads(verified.index_path.read_bytes())
                index["defaultDatasetId"] = fixture.dataset_id
                verified.index_path.write_bytes(canonical_json_bytes(index))
                return verified

            with mock.patch(
                "tools.tr_release.candidate.verify_candidate",
                side_effect=verify_then_tamper,
            ):
                fixture.activate()

            self.assertEqual(
                (fixture.active_manifests / f"{fixture.dataset_id}.json").read_bytes(),
                verified_manifest,
            )
            self.assertEqual(
                (fixture.active_root / "index.json").read_bytes(), verified_index
            )

    def test_activation_rejects_active_index_change_after_candidate_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CandidateFixture(Path(directory))
            fixture.build()
            original_verify = verify_candidate

            def verify_then_switch_active(*args, **kwargs):
                verified = original_verify(*args, **kwargs)
                switched_id = "tamriel-rebuilt-26.09"
                switched_manifest = {
                    "schemaVersion": 1,
                    "datasetId": switched_id,
                    "mapKey": "tamriel-rebuilt",
                    "snapshotId": f"tr:{switched_id}:1111111111111111",
                }
                fixture._write(
                    fixture.active_manifests / f"{switched_id}.json",
                    switched_manifest,
                    canonical=False,
                )
                switched_index = copy.deepcopy(fixture.active_index)
                switched_index["datasets"][1] = {
                    "datasetId": switched_id,
                    "manifestUrl": f"/datasets/manifests/{switched_id}.json",
                    "order": 1,
                }
                fixture._write(
                    fixture.active_root / "index.json", switched_index, canonical=False
                )
                return verified

            with (
                mock.patch(
                    "tools.tr_release.candidate.verify_candidate",
                    side_effect=verify_then_switch_active,
                ),
                self.assertRaisesRegex(ValueError, "Active datasets changed"),
            ):
                fixture.activate()

            self.assertFalse(
                (fixture.active_manifests / f"{fixture.dataset_id}.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
