from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DATASET_ID = "test-dataset"
SNAPSHOT_ID = "test:dataset:0123456789abcdef"
PYRAMID_ID = "test-dataset.basemap"
CATALOG_HASH = "c" * 64
TILE_HASH = "d" * 64


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def descriptor(url: str, payload: bytes, media_type: str = "application/json") -> dict[str, Any]:
    return {
        "bytes": len(payload),
        "mediaType": media_type,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "url": url,
    }


def build_runtime() -> tuple[dict[str, bytes], dict[str, str]]:
    paths = {
        "manifest": "/datasets/manifests/test-dataset.json",
        "locations": f"/datasets/generated/test-dataset/catalogs/{CATALOG_HASH}/locations.json",
        "locale": f"/datasets/generated/test-dataset/catalogs/{CATALOG_HASH}/locales/en.json",
        "catalogAudit": f"/datasets/metadata/test-dataset/catalogs/{CATALOG_HASH}/catalog-audit.json",
        "mapAssets": f"/datasets/metadata/test-dataset/{TILE_HASH}/map-assets.json",
        "coverage": f"/datasets/metadata/test-dataset/{TILE_HASH}/tile-coverage.json",
        "quality": f"/datasets/metadata/test-dataset/{TILE_HASH}/basemap-audit.json",
        "receipt": f"/datasets/metadata/test-dataset/{TILE_HASH}/seam-stabilization.json",
        "tile": f"/datasets/generated/test-dataset/{TILE_HASH}/tiles/0/0/0.webp",
    }
    identity = {"datasetId": DATASET_ID, "schemaVersion": 1, "snapshotId": SNAPSHOT_ID}
    locations = json_bytes({**identity, "places": []})
    locale = json_bytes({**identity, "locale": "en", "places": []})
    catalog_audit = json_bytes({**identity, "status": "passed"})
    coverage = json_bytes(
        {
            **identity,
            "encoding": "x-y-ranges-v1",
            "levels": [{"columns": [{"x": 0, "yRanges": [[0, 0]]}], "z": 0}],
            "tileCount": 1,
            "tilePyramidId": PYRAMID_ID,
        }
    )
    quality = json_bytes({**identity, "status": "passed"})
    receipt = json_bytes({**identity, "status": "passed"})
    map_assets = json_bytes(
        {
            **identity,
            "projection": "TES3:WORLD",
            "rasters": [],
            "tilePyramids": [
                {
                    "coverage": descriptor(paths["coverage"], coverage),
                    "derivation": {
                        "implementationSha256": "5" * 64,
                        "kind": "cross-shard-seam-stabilization",
                        "receipt": descriptor(paths["receipt"], receipt),
                        "sourceInventorySha256": "4" * 64,
                        "version": "fixture-v1",
                    },
                    "extent": [0, 0, 512, 512],
                    "id": PYRAMID_ID,
                    "integrity": {
                        "assetTreeFingerprint": "8" * 64,
                        "inputFingerprint": "9" * 64,
                        "inventoryFileSha256": "2" * 64,
                        "inventorySha256": "1" * 64,
                        "planFingerprint": "6" * 64,
                        "productionSourceFingerprint": "7" * 64,
                        "profileFingerprint": "3" * 64,
                        "provenanceFingerprint": "a" * 64,
                        "rendererFingerprint": "b" * 64,
                        "tileCount": 1,
                        "totalBytes": 12,
                    },
                    "kind": "xyz-pyramid",
                    "maxZoom": 0,
                    "mediaType": "image/webp",
                    "minZoom": 0,
                    "origin": [0, 512],
                    "qualityReport": descriptor(paths["quality"], quality),
                    "regionIds": ["fixture"],
                    "resolutions": [1],
                    "sparse": True,
                    "tileSize": 512,
                    "urlTemplate": f"/datasets/generated/test-dataset/{TILE_HASH}/tiles/{{z}}/{{x}}/{{y}}.webp",
                }
            ],
        }
    )
    manifest = json_bytes(
        {
            "artifacts": {
                "catalogAudit": descriptor(paths["catalogAudit"], catalog_audit),
                "locales": [{"artifact": descriptor(paths["locale"], locale), "locale": "en"}],
                "locations": descriptor(paths["locations"], locations),
                "tiles": {
                    "manifestUrl": paths["mapAssets"],
                    "sha256": hashlib.sha256(map_assets).hexdigest(),
                },
            },
            **identity,
        }
    )
    index = json_bytes(
        {
            "datasets": [{"datasetId": DATASET_ID, "manifestUrl": paths["manifest"], "order": 0}],
            "defaultDatasetId": DATASET_ID,
            "schemaVersion": 1,
        }
    )
    webp = b"RIFF" + (4).to_bytes(4, "little") + b"WEBP"
    runtime = {
        "/datasets/index.json": index,
        paths["manifest"]: manifest,
        paths["locations"]: locations,
        paths["locale"]: locale,
        paths["catalogAudit"]: catalog_audit,
        paths["mapAssets"]: map_assets,
        paths["coverage"]: coverage,
        paths["quality"]: quality,
        paths["receipt"]: receipt,
        paths["tile"]: webp,
    }
    return runtime, paths


def write_dist(root: Path) -> dict[str, str]:
    runtime, paths = build_runtime()
    (root / "assets").mkdir(parents=True)
    (root / "assets/app-123.js").write_bytes(b"console.log('fixture')\n")
    (root / "assets/app-123.css").write_bytes(b"body{}\n")
    (root / "index.html").write_text(
        '<!doctype html><div id="root"></div><script type="module" '
        'src="/assets/app-123.js"></script><link rel="stylesheet" href="/assets/app-123.css">\n',
        encoding="utf-8",
    )
    for url, payload in runtime.items():
        if url.startswith("/datasets/generated/"):
            continue
        path = root / url.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    stale = root / "datasets/metadata/test-dataset/stale-snapshot/unused.json"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"{}\n")
    generated = root / paths["tile"].lstrip("/")
    generated.parent.mkdir(parents=True)
    generated.write_bytes(runtime[paths["tile"]])
    return paths
