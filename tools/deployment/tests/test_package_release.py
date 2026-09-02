from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.deployment.common import DeploymentError
from tools.deployment.package_release import package_release
from tools.deployment.tests.fixtures import write_dist


class PackageReleaseTests(unittest.TestCase):
    commit_sha = "c" * 40

    def test_packages_only_active_shell_and_metadata_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            paths = write_dist(dist)
            first = package_release(
                repo_root=root,
                dist_root=dist,
                output_dir=root / "one",
                commit_sha=self.commit_sha,
            )
            second = package_release(
                repo_root=root,
                dist_root=dist,
                output_dir=root / "two",
                commit_sha=self.commit_sha,
            )
            first_bytes = Path(str(first["archive"])).read_bytes()
            second_bytes = Path(str(second["archive"])).read_bytes()
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(first["archiveSha256"], hashlib.sha256(first_bytes).hexdigest())

            with tarfile.open(fileobj=io.BytesIO(first_bytes), mode="r:gz") as archive:
                names = set(archive.getnames())
                self.assertIn("index.html", names)
                self.assertIn(paths["mapAssets"].lstrip("/"), names)
                self.assertIn(paths["coverage"].lstrip("/"), names)
                self.assertIn("release-manifest.json", names)
                self.assertNotIn(paths["locations"].lstrip("/"), names)
                self.assertNotIn(paths["tile"].lstrip("/"), names)
                self.assertNotIn(paths["catalogAudit"].lstrip("/"), names)
                self.assertNotIn(paths["quality"].lstrip("/"), names)
                self.assertNotIn(paths["receipt"].lstrip("/"), names)
                self.assertNotIn(
                    "datasets/metadata/test-dataset/stale-snapshot/unused.json", names
                )
                release = json.load(archive.extractfile("release-manifest.json"))
                generated_urls = {item["url"] for item in release["generatedArtifacts"]}
                self.assertIn(paths["locations"], generated_urls)
                self.assertIn(paths["locale"], generated_urls)

    def test_rejects_tampered_referenced_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            paths = write_dist(dist)
            (dist / paths["coverage"].lstrip("/")).write_bytes(b"{}\n")
            with self.assertRaisesRegex(DeploymentError, "coverage.*(bytes|SHA-256)"):
                package_release(
                    repo_root=root,
                    dist_root=dist,
                    output_dir=root / "output",
                    commit_sha=self.commit_sha,
                )

    def test_rejects_unsafe_manifest_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            write_dist(dist)
            index_path = dist / "datasets/index.json"
            index = json.loads(index_path.read_bytes())
            index["datasets"][0]["manifestUrl"] = "//example.com/manifest.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            with self.assertRaisesRegex(DeploymentError, "same-origin"):
                package_release(
                    repo_root=root,
                    dist_root=dist,
                    output_dir=root / "output",
                    commit_sha=self.commit_sha,
                )

    def test_rejects_non_content_addressed_immutable_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            paths = write_dist(dist)
            manifest_path = dist / paths["manifest"].lstrip("/")
            manifest = json.loads(manifest_path.read_bytes())
            source = dist / paths["mapAssets"].lstrip("/")
            unsafe_url = "/datasets/metadata/test-dataset/current/map-assets.json"
            target = dist / unsafe_url.lstrip("/")
            target.parent.mkdir(parents=True)
            target.write_bytes(source.read_bytes())
            manifest["artifacts"]["tiles"]["manifestUrl"] = unsafe_url
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DeploymentError, "immutable SHA-256"):
                package_release(
                    repo_root=root,
                    dist_root=dist,
                    output_dir=root / "output",
                    commit_sha=self.commit_sha,
                )

    def test_rejects_symlinked_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            write_dist(dist)
            linked = dist / "assets/linked.js"
            linked.symlink_to(dist / "assets/app-123.js")
            with self.assertRaisesRegex(DeploymentError, "symlink"):
                package_release(
                    repo_root=root,
                    dist_root=dist,
                    output_dir=root / "output",
                    commit_sha=self.commit_sha,
                )


if __name__ == "__main__":
    unittest.main()
