from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any


def install(
    publish: ModuleType,
    production: ModuleType,
    *,
    origin: tuple[int, int],
) -> None:
    """Install the tight-grid Original validator without editing Poison code."""

    def validate_source(
        source_root: Path,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> Any:
        source_root = source_root.resolve()
        inventory_path = source_root / "inventory.json"
        inventory, inventory_bytes = publish._read_json_object(
            inventory_path, "Tile inventory"
        )
        expected_identity = {
            "schemaVersion": 1,
            "datasetId": publish.DATASET_ID,
            "snapshotId": publish.SNAPSHOT_ID,
            "tileFormat": "image/webp",
            "tilePixels": publish.TILE_PIXELS,
            "minZoom": publish.MIN_ZOOM,
            "maxZoom": publish.MAX_ZOOM,
            "extent": list(publish.POISON_WORLD_EXTENT),
            "origin": [float(origin[0]), float(origin[1])],
        }
        for key, expected in expected_identity.items():
            if inventory.get(key) != expected:
                raise ValueError(
                    f"Inventory {key} mismatch: expected {expected!r}, "
                    f"got {inventory.get(key)!r}"
                )
        entries = publish._validated_tile_entries(inventory.get("tiles"))
        source_scope = publish._validate_pinned_tile_topology(entries)
        tile_count = publish._positive_integer(
            inventory.get("tileCount"), "Inventory tileCount"
        )
        total_bytes = publish._positive_integer(
            inventory.get("totalBytes"), "Inventory totalBytes"
        )
        if tile_count != len(entries):
            raise ValueError("Inventory tileCount does not match tiles")
        if total_bytes != sum(int(entry["bytes"]) for entry in entries):
            raise ValueError("Inventory totalBytes does not match tiles")
        logical_sha256 = publish._fingerprint(
            inventory.get("inventorySha256"), "Inventory inventorySha256"
        )
        core = {
            key: value for key, value in inventory.items() if key != "inventorySha256"
        }
        if publish._sha256_bytes(publish._canonical_json_bytes(core)) != logical_sha256:
            raise ValueError("Inventory logical SHA-256 does not match its payload")
        provenance_fingerprint = publish._fingerprint(
            inventory.get("provenanceFingerprint"),
            "Inventory provenanceFingerprint",
        )
        plan_fingerprint = publish._fingerprint(
            inventory.get("planFingerprint"), "Inventory planFingerprint"
        )
        if plan_fingerprint != publish.EXPECTED_PLAN_FINGERPRINT:
            raise ValueError(
                "Inventory planFingerprint does not match the pinned Original GOTY plan"
            )

        provenance, provenance_bytes = publish._read_json_object(
            source_root / "provenance.json", "Provenance"
        )
        publish._validate_identity(provenance, label="Provenance", inventory=inventory)
        if (
            publish._verified_publication_provenance(provenance)
            != provenance_fingerprint
        ):
            raise ValueError("Provenance fingerprint does not match inventory")
        if provenance.get("openmwCommit") != publish.OPENMW_COMMIT:
            raise ValueError("Provenance OpenMW commit does not match the pinned renderer")
        profile_fingerprint = publish._fingerprint(
            provenance.get("profileFingerprint"), "Provenance profileFingerprint"
        )
        production_source_fingerprint = publish._fingerprint(
            provenance.get("productionSourceFingerprint"),
            "Provenance productionSourceFingerprint",
        )
        image = provenance.get("image")
        if not isinstance(image, dict) or not isinstance(image.get("labels"), dict):
            raise ValueError("Provenance image labels are missing")
        renderer_fingerprint = publish._fingerprint(
            image["labels"].get("io.morrowind-map.renderer-fingerprint"),
            "Provenance rendererFingerprint",
        )
        asset_audit = provenance.get("assetAudit")
        input_audit = provenance.get("inputAudit")
        if not isinstance(asset_audit, dict) or not isinstance(input_audit, dict):
            raise ValueError("Provenance asset/input audit is malformed")
        asset_tree_fingerprint = publish._sha256_bytes(
            publish._canonical_json_bytes(asset_audit)
        )
        input_fingerprint = publish._sha256_bytes(
            publish._canonical_json_bytes(input_audit)
        )

        plan, plan_bytes = publish._read_json_object(
            source_root / "plan.json", "Production plan"
        )
        publish._validate_identity(plan, label="Production plan", inventory=inventory)
        if plan.get("planFingerprint") != plan_fingerprint:
            raise ValueError("Production plan fingerprint does not match inventory")
        raw_shards = plan.get("shards")
        if not isinstance(raw_shards, list):
            raise ValueError("Production plan shards are malformed")
        cells: list[tuple[int, int]] = []
        for shard in raw_shards:
            if not isinstance(shard, dict) or not isinstance(shard.get("cells"), list):
                raise ValueError("Production plan shard is malformed")
            for raw_cell in shard["cells"]:
                if (
                    not isinstance(raw_cell, list)
                    or len(raw_cell) != 2
                    or not all(
                        isinstance(value, int) and not isinstance(value, bool)
                        for value in raw_cell
                    )
                ):
                    raise ValueError("Production plan cell is malformed")
                cells.append((raw_cell[0], raw_cell[1]))
        if plan != production.plan_report(cells):
            raise ValueError("Production plan does not recompute exactly")
        native_tiles = {
            production.TileKey(int(entry["z"]), int(entry["x"]), int(entry["y"]))
            for entry in entries
            if int(entry["z"]) == publish.NATIVE_ZOOM
        }
        if native_tiles != {production.native_tile_for_cell(cell) for cell in cells}:
            raise ValueError("Production plan does not match the native inventory")
        source_scope["shards"] = len(raw_shards)
        source_scope["rawCrossShardProbes"] = publish.EXPECTED_QUALITY_SCOPE[
            "rawCrossShardProbes"
        ]
        if source_scope != publish.EXPECTED_QUALITY_SCOPE:
            raise ValueError(
                "Production source does not match the pinned Original GOTY quality scope"
            )

        publish._validate_tile_tree(source_root, entries, progress=progress)
        return publish.ValidatedInventory(
            payload=inventory,
            inventory_sha256=logical_sha256,
            inventory_file_sha256=publish._sha256_bytes(inventory_bytes),
            provenance_file_sha256=publish._sha256_bytes(provenance_bytes),
            plan_file_sha256=publish._sha256_bytes(plan_bytes),
            tile_count=tile_count,
            total_bytes=total_bytes,
            tile_entries=entries,
            provenance=provenance,
            provenance_fingerprint=provenance_fingerprint,
            plan_fingerprint=plan_fingerprint,
            profile_fingerprint=profile_fingerprint,
            renderer_fingerprint=renderer_fingerprint,
            production_source_fingerprint=production_source_fingerprint,
            asset_tree_fingerprint=asset_tree_fingerprint,
            input_fingerprint=input_fingerprint,
            source_scope=source_scope,
        )

    frozen_build_publish_metadata = publish.build_publish_metadata

    def build_publish_metadata(source_root: Path, inventory: Any) -> Any:
        metadata = frozen_build_publish_metadata(source_root, inventory)
        map_assets = copy.deepcopy(metadata.map_assets)
        pyramid = map_assets["tilePyramids"][0]
        pyramid["extent"] = list(publish.POISON_WORLD_EXTENT)
        pyramid["origin"] = list(origin)
        return replace(metadata, map_assets=map_assets)

    publish.validate_source = validate_source
    publish.build_publish_metadata = build_publish_metadata
