from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class ReleaseBootstrapTests(unittest.TestCase):
    def test_fresh_process_injects_release_identity_and_derived_contracts(self) -> None:
        script = r'''
import json
from pathlib import Path

from tools.tr_release.bootstrap import activate
from tools.tr_release.model import load_profile

profile = load_profile(Path("config/tr-release.json"))
profile_value = profile.to_dict()
directories = {item.id: item.path for item in profile.data_directories}
inputs = []
for item in profile.required_inputs:
    inputs.append({
        "id": item.id,
        "directoryId": item.directory_id,
        "filename": item.filename,
        "relativePath": f"{directories[item.directory_id]}/{item.filename}",
        "bytes": 1,
        "sha256": item.sha256 or "f" * 64,
    })
trees = [
    {"id": item.id, "relativePath": item.path, "files": 1, "bytes": 1, "sha256": "e" * 64}
    for item in profile.data_directories
]
tile_counts = {str(zoom): 1 for zoom in range(8)}
adjacencies = {str(zoom): {"east": 0, "north": 0} for zoom in range(8)}
lock = {
    "datasetId": profile.dataset_id,
    "snapshotId": profile.adopted_snapshot_id,
    "profileFingerprint": "a" * 64,
    "source": {"inputs": inputs, "dataTrees": trees},
    "renderer": {
        "extent": [0, 0, 8192, 8192],
        "origin": [0, 8192],
        "resolutions": [2048, 1024, 512, 256, 128, 64, 32, 16],
        "planFingerprint": "b" * 64,
        "tileCounts": tile_counts,
        "adjacencies": adjacencies,
        "scope": {
            "tiles": 8,
            "nativeTiles": 1,
            "lowerZoomTiles": 7,
            "shards": 1,
            "allFinalAdjacencies": 0,
            "nativeAdjacencies": 0,
            "nativeCrossShardAdjacencies": 0,
            "rawCrossShardProbes": 16,
        },
        "pinnedRawProbeIds": [
            "7/0/0:east:7/1/0",
            "7/0/1:north:7/0/0",
        ],
    },
    "catalog": {
        "worldCounts": {},
        "catalogCounts": {},
        "resolutionCounts": {},
        "regionCounts": {},
        "dropped": {},
        "exclusions": {},
    },
}
pipeline = activate(profile_value, lock)
print(json.dumps({
    "dataset": pipeline.production.DATASET_ID,
    "snapshot": pipeline.production.SNAPSHOT_ID,
    "image": pipeline.production.DEFAULT_PRODUCTION_IMAGE,
    "extent": pipeline.production.POISON_WORLD_EXTENT,
    "tileCounts": pipeline.publish.EXPECTED_TILE_COUNTS,
    "scope": pipeline.audit.EXPECTED_SCOPE,
    "catalogInputs": pipeline.catalog.CATALOG_SOURCE_IDS,
    "regions": pipeline.publish.TILE_REGIONS,
    "sourcePathsExist": all(Path(path).is_file() for path in pipeline.production.PRODUCTION_SOURCE_PATHS),
}))
'''
        completed = subprocess.run(
            (sys.executable, "-c", script),
            cwd=REPO_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        value = json.loads(completed.stdout)

        self.assertEqual(value["dataset"], "poison-song-26.08")
        self.assertEqual(value["snapshot"], "tr:poison-song-26.08:6964517551e0fcb0")
        self.assertEqual(value["image"], "morrowind-map-openmw:0.51.0-tr")
        self.assertEqual(value["extent"], [0, 0, 8192, 8192])
        self.assertEqual(value["tileCounts"], {str(zoom): 1 for zoom in range(8)})
        self.assertEqual(value["scope"]["nativeTiles"], 1)
        self.assertEqual(
            value["catalogInputs"],
            [
                "morrowind-esm",
                "tribunal-esm",
                "bloodmoon-esm",
                "tamriel-data-esm",
                "tr-mainland-esm",
            ],
        )
        self.assertEqual(value["regions"], ["vvardenfell", "solstheim", "tr-mainland"])
        self.assertTrue(value["sourcePathsExist"])


if __name__ == "__main__":
    unittest.main()
