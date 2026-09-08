from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.deployment.git_datasets import GitDatasetError, check_revision, export_revision


class GitDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        from tools.deployment.common import canonical_json_bytes
        from tools.deployment.dataset_packages import pack_tile_set, read_tile_sets
        from tools.deployment.tests.fixtures import write_dist
        from tools.deployment.upload_datasets import build_dataset_plan

        public = self.repo / "apps/web/public"
        paths = write_dist(public)
        entry = pack_tile_set(read_tile_sets(public_root=public)[0],
                              generated_root=public / "datasets/generated", package_root=self.root / "packages")
        lock = {"schemaVersion": 1, "repository": "omggga/morrowind-map", "tileSets": [entry]}
        self.write("config/dataset-releases.lock.json", canonical_json_bytes(lock))
        self.write("config/dataset-upload-plan.json", canonical_json_bytes(build_dataset_plan(public_root=public)))
        (public / paths["tile"].lstrip("/")).unlink()

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-c", "core.hooksPath=/dev/null", "-C", str(self.repo), *args],
            stderr=subprocess.STDOUT,
        ).decode().strip()

    def write(self, name: str, payload: bytes) -> Path:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def commit(self) -> str:
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def tile(self, payload: bytes = b"RIFF\x04\x00\x00\x00WEBP") -> tuple[str, Path]:
        oid = hashlib.sha256(payload).hexdigest()
        name = "apps/web/public/datasets/generated/world/hash/tiles/0/0/0.webp"
        self.write(name, (f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {len(payload)}\n").encode())
        obj = self.write(f".git/lfs/objects/{oid[:2]}/{oid[2:4]}/{oid}", payload)
        return name, obj

    def test_exports_committed_metadata_only(self) -> None:
        self.write("tools/renderers/renderer.py", b"raise RuntimeError('must not run')\n")
        self.write("apps/web/public/datasets/metadata/worst-seams.webp", b"RIFF\x04\x00\x00\x00WEBP")
        expected_index = (self.repo / "apps/web/public/datasets/index.json").read_bytes()
        revision = self.commit()
        self.write("apps/web/public/datasets/index.json", b"working tree must not escape")
        self.write("apps/web/public/datasets/untracked.json", b"{}")
        output = self.root / "public"
        report = export_revision(repo_root=self.repo, revision=revision, output_public_root=output)
        self.assertEqual(report["snapshotMode"], "releases")
        self.assertFalse(list((output / "datasets/generated").rglob("*.webp")))
        self.assertEqual((output / "datasets/index.json").read_bytes(), expected_index)
        self.assertFalse((output / "datasets/untracked.json").exists())
        self.assertFalse((output / "tools").exists())

    def test_rejects_proprietary_assets_anywhere_and_input_directories(self) -> None:
        for name in ("hidden/Morrowind.EsM", "tools/asset.BSA", "anything/texture.DDS", "local-data/source.json", "a/data-sources/input.txt", "renders/tile.webp", "raw/data.json", "apps/web/public/datasets/generated/source.zip", "Morrowind.zip", "uploads/game.7z", "inputs/game.json", "input/game.json"):
            with self.subTest(name=name):
                path = self.write(name, b"source")
                revision = self.commit()
                with self.assertRaisesRegex(GitDatasetError, "(source|archive)"):
                    check_revision(repo_root=self.repo, revision=revision)
                path.unlink()

    def test_rejects_binary_generated_blob_and_noncanonical_pointer(self) -> None:
        name, _ = self.tile()
        for content in (b"RIFF\x04\x00\x00\x00WEBP", b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 01\n"):
            self.write(name, content)
            with self.assertRaisesRegex(GitDatasetError, "forbid tracked generated WebP"):
                check_revision(repo_root=self.repo, revision=self.commit())
        (self.repo / name).unlink()
        self.write("apps/web/public/datasets/generated/binary.json", b"\x00\xff")
        with self.assertRaisesRegex(GitDatasetError, "JSON"):
            check_revision(repo_root=self.repo, revision=self.commit())

    def test_rejects_dataset_symlink_and_submodule(self) -> None:
        link = self.repo / "apps/web/public/datasets/link.json"
        link.symlink_to("../../../../.git/config")
        with self.assertRaisesRegex(GitDatasetError, "regular file"):
            check_revision(repo_root=self.repo, revision=self.commit())
        link.unlink()
        base = self.commit()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{base},apps/web/public/datasets/submodule")
        self.git("commit", "--quiet", "-m", "submodule")
        with self.assertRaisesRegex(GitDatasetError, "regular file"):
            check_revision(repo_root=self.repo, revision=self.git("rev-parse", "HEAD"))

    def test_existing_local_lfs_objects_cannot_restore_tracked_tiles(self) -> None:
        _, obj = self.tile()
        revision = self.commit()
        for existing in (True, False):
            if not existing:
                obj.unlink()
            output = self.root / str(existing)
            with self.assertRaisesRegex(GitDatasetError, "forbid tracked generated WebP"):
                export_revision(repo_root=self.repo, revision=revision, output_public_root=output)
            self.assertFalse(output.exists())

    def test_rejects_limits_and_unsafe_revision(self) -> None:
        revision = self.commit()
        for kwargs in ({"max_file_bytes": 10}, {"max_total_bytes": 25}, {"max_files": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(GitDatasetError, "limit"):
                check_revision(repo_root=self.repo, revision=revision, **kwargs)
        for unsafe in ("HEAD", "--all", "a" * 39, "a" * 40 + ":tree"):
            with self.subTest(unsafe=unsafe), self.assertRaisesRegex(GitDatasetError, "40"):
                check_revision(repo_root=self.repo, revision=unsafe)

    def test_rejects_candidate_lfs_configuration_and_unsafe_paths(self) -> None:
        for name in (".lfsconfig", "apps/web/public/datasets/bad\\path.json"):
            with self.subTest(name=name):
                path = self.write(name, b"{}")
                with self.assertRaises(GitDatasetError):
                    check_revision(repo_root=self.repo, revision=self.commit())
                path.unlink()

    def test_standalone_cli_does_not_run_hooks_or_filters(self) -> None:
        import sys
        from tools.deployment import git_datasets

        self.write("apps/web/public/datasets/metadata/worst-seams.webp", b"RIFF\x04\x00\x00\x00WEBP")
        revision = self.commit()
        marker = self.root / "executed"
        hook = self.write(".git/hooks/post-checkout", f"#!/bin/sh\ntouch '{marker}'\n".encode())
        hook.chmod(0o755)
        self.git("config", "filter.lfs.smudge", f"touch '{marker}'")
        self.git("config", "filter.lfs.required", "true")
        self.write(".gitattributes", b"*.webp filter=lfs\n")
        result = subprocess.run(
            [sys.executable, str(Path(git_datasets.__file__).resolve()), "export", "--repo-root", str(self.repo), "--revision", revision, "--output-public-root", str(self.root / "public")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["snapshotMode"], "releases")
        self.assertFalse(marker.exists())

    def test_rejects_output_symlink_and_existing_dataset_tree(self) -> None:
        revision = self.commit()
        output = self.root / "public"
        output.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(GitDatasetError, "symlink"):
            export_revision(repo_root=self.repo, revision=revision, output_public_root=output)
        output.unlink()
        (output / "datasets").mkdir(parents=True)
        with self.assertRaisesRegex(GitDatasetError, "already exists"):
            export_revision(repo_root=self.repo, revision=revision, output_public_root=output)


class ReleaseSnapshotTests(unittest.TestCase):
    setUp = GitDatasetTests.setUp
    git = GitDatasetTests.git
    write = GitDatasetTests.write
    commit = GitDatasetTests.commit

    def release_fixture(self) -> str:
        return self.commit()

    def test_exports_exact_committed_release_metadata_lock_and_plan(self) -> None:
        revision = self.release_fixture()
        lock = (self.repo / "config/dataset-releases.lock.json").read_bytes()
        plan = (self.repo / "config/dataset-upload-plan.json").read_bytes()
        self.write("config/dataset-releases.lock.json", b"invalid working tree")
        self.write("config/dataset-upload-plan.json", b"invalid working tree")
        output = self.root / "public"
        report = export_revision(repo_root=self.repo, revision=revision, output_public_root=output)
        self.assertEqual(report["snapshotMode"], "releases")
        self.assertEqual((output / "config/dataset-releases.lock.json").read_bytes(), lock)
        self.assertEqual((output / "config/dataset-upload-plan.json").read_bytes(), plan)
        self.assertFalse(list((output / "datasets/generated").rglob("*.webp")))
        self.assertTrue(list((output / "datasets/generated").rglob("*.json")))

    def test_every_snapshot_requires_its_own_lock(self) -> None:
        (self.repo / "config/dataset-releases.lock.json").unlink()
        # Even a root commit without lock history cannot request old transport.
        revision = self.commit()
        with self.assertRaisesRegex(GitDatasetError, "committed transport lock"):
            check_revision(repo_root=self.repo, revision=revision)
        with self.assertRaisesRegex(GitDatasetError, "committed transport lock"):
            export_revision(repo_root=self.repo, revision=revision, output_public_root=self.root / "public")
        self.assertFalse((self.root / "public").exists())

    def test_lock_deletion_fails_even_with_shallow_history(self) -> None:
        self.release_fixture()
        (self.repo / "config/dataset-releases.lock.json").unlink()
        revision = self.commit()
        self.write(".git/shallow", (revision + "\n").encode())
        with self.assertRaisesRegex(GitDatasetError, "committed transport lock"):
            check_revision(repo_root=self.repo, revision=revision)

    def test_malformed_incomplete_and_wrong_snapshot_locks_fail(self) -> None:
        self.release_fixture()
        original = (self.repo / "config/dataset-releases.lock.json").read_bytes()
        incomplete = json.loads(original)
        incomplete["tileSets"] = []
        wrong = json.loads(original)
        wrong["tileSets"][0]["inventorySha256"] = "a" * 64
        wrong["tileSets"][0]["releaseTag"] = wrong["tileSets"][0]["releaseTag"].rsplit("/", 1)[0] + "/" + "a" * 64
        for payload in (b'{"schemaVersion":1,"schemaVersion":1}', b"not json", json.dumps(incomplete).encode(), json.dumps(wrong).encode()):
            with self.subTest(payload=payload):
                self.write("config/dataset-releases.lock.json", payload)
                with self.assertRaises(GitDatasetError):
                    check_revision(repo_root=self.repo, revision=self.commit())

    def test_missing_or_changed_committed_plan_fails(self) -> None:
        self.release_fixture()
        path = self.repo / "config/dataset-upload-plan.json"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(GitDatasetError, "committed dataset upload plan"):
            check_revision(repo_root=self.repo, revision=self.commit())
        plan = json.loads(original)
        plan["graphSha256"] = "a" * 64
        self.write("config/dataset-upload-plan.json", json.dumps(plan).encode())
        with self.assertRaisesRegex(GitDatasetError, "differs"):
            check_revision(repo_root=self.repo, revision=self.commit())

    def test_release_mode_preserves_generated_tile_and_source_bans(self) -> None:
        self.release_fixture()
        tile = self.write("apps/web/public/datasets/generated/extra/tiles/0/0/0.webp",
                          b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 12\n")
        with self.assertRaisesRegex(GitDatasetError, "forbid tracked generated WebP"):
            check_revision(repo_root=self.repo, revision=self.commit())
        tile.unlink()
        for name in ("game.ESM", "anything/archive.tar", "local-data/secret.json"):
            path = self.write(name, b"forbidden")
            with self.subTest(name=name), self.assertRaisesRegex(GitDatasetError, "forbidden"):
                check_revision(repo_root=self.repo, revision=self.commit())
            path.unlink()

    def test_release_metadata_webp_must_be_inline_and_never_hydrates_lfs(self) -> None:
        self.release_fixture()
        name = "apps/web/public/datasets/metadata/worst-seams.webp"
        payload = b"RIFF\x04\x00\x00\x00WEBP"
        self.write(name, payload)
        inline_revision = self.commit()
        output = self.root / "inline-public"
        export_revision(repo_root=self.repo, revision=inline_revision, output_public_root=output)
        self.assertEqual((output / "datasets/metadata/worst-seams.webp").read_bytes(), payload)
        oid = hashlib.sha256(payload).hexdigest()
        self.write(name, f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {len(payload)}\n".encode())
        self.write(f".git/lfs/objects/{oid[:2]}/{oid[2:4]}/{oid}", payload)
        revision = self.commit()
        with self.assertRaisesRegex(GitDatasetError, "forbid LFS pointers"):
            export_revision(repo_root=self.repo, revision=revision, output_public_root=self.root / "lfs-public")
        self.assertFalse((self.root / "lfs-public").exists())

    def test_config_output_aliases_cannot_overlap_or_overwrite_source(self) -> None:
        revision = self.release_fixture()
        source_config = self.repo / "config/dataset-releases.lock.json"
        original = source_config.read_bytes()
        output = self.root / "public"
        aliases = (output / "datasets" / ".." / "datasets", self.repo / "config" / ".." / "config")
        for config in aliases:
            with self.subTest(config=config), self.assertRaisesRegex(GitDatasetError, "(overlap|already exists)"):
                export_revision(repo_root=self.repo, revision=revision, output_public_root=output,
                                 output_config_root=config)
            self.assertFalse((output / "datasets").exists())
            self.assertEqual(source_config.read_bytes(), original)

    def test_removed_transport_options_are_rejected_by_cli(self) -> None:
        import sys
        from tools.deployment import git_datasets

        revision = self.release_fixture()
        for option in (["--mode", "legacy"], ["--metadata-only"], ["--release-boundary", revision]):
            result = subprocess.run(
                [sys.executable, str(Path(git_datasets.__file__).resolve()), "check",
                 "--repo-root", str(self.repo), "--revision", revision, *option],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("unrecognized arguments", result.stderr)

    def test_release_cli_uses_trusted_imports_from_candidate_cwd(self) -> None:
        import os
        import sys
        from tools.deployment import git_datasets

        revision = self.release_fixture()
        marker = self.root / "candidate-executed"
        self.write("tools/__init__.py", f"from pathlib import Path; Path({str(marker)!r}).touch()\n".encode())
        result = subprocess.run(
            [sys.executable, str(Path(git_datasets.__file__).resolve()), "export", "--repo-root", str(self.repo),
             "--revision", revision, "--output-public-root", str(self.root / "public")],
            capture_output=True, text=True, cwd=self.repo, env={**os.environ, "PYTHONPATH": str(self.repo)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["snapshotMode"], "releases")
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
