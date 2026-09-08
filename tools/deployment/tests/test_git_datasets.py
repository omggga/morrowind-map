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
        self.write("apps/web/public/datasets/index.json", b'{"schemaVersion":1}\n')

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

    def test_exports_committed_data_only_and_hydrates_verified_lfs(self) -> None:
        name, _ = self.tile()
        self.write("apps/web/public/datasets/generated/world/catalogs/locations.json", b"[]\n")
        self.write("tools/renderers/renderer.py", b"raise RuntimeError('must not run')\n")
        self.write("apps/web/public/datasets/metadata/worst-seams.webp", b"RIFF\x04\x00\x00\x00WEBP")
        revision = self.commit()
        self.write("apps/web/public/datasets/index.json", b"working tree must not escape")
        self.write("apps/web/public/datasets/untracked.json", b"{}")
        output = self.root / "public"
        report = export_revision(repo_root=self.repo, revision=revision, output_public_root=output)
        self.assertEqual(report["lfsFileCount"], 1)
        self.assertEqual(report["generatedFileCount"], 2)
        self.assertEqual((output / name.removeprefix("apps/web/public/")).read_bytes(), b"RIFF\x04\x00\x00\x00WEBP")
        self.assertEqual(json.loads((output / "datasets/index.json").read_bytes()), {"schemaVersion": 1})
        self.assertFalse((output / "datasets/untracked.json").exists())
        self.assertFalse((output / "tools").exists())

    def test_metadata_only_baseline_is_identifiable(self) -> None:
        report = check_revision(repo_root=self.repo, revision=self.commit())
        self.assertEqual(report["generatedFileCount"], 0)
        self.assertEqual(report["lfsFileCount"], 0)

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
            with self.assertRaisesRegex(GitDatasetError, "canonical Git LFS pointer"):
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

    def test_rejects_missing_corrupt_and_symlinked_lfs_object(self) -> None:
        _, obj = self.tile()
        revision = self.commit()
        for fault in ("corrupt", "missing", "symlink"):
            with self.subTest(fault=fault):
                if obj.exists() or obj.is_symlink():
                    obj.unlink()
                if fault == "corrupt":
                    obj.write_bytes(b"RIFF\x04\x00\x00\x00FAIL")
                elif fault == "symlink":
                    target = self.root / "elsewhere"
                    target.write_bytes(b"RIFF\x04\x00\x00\x00WEBP")
                    obj.symlink_to(target)
                with self.assertRaises(GitDatasetError):
                    export_revision(repo_root=self.repo, revision=revision, output_public_root=self.root / fault)
                self.assertFalse((self.root / fault).exists())

    def test_rejects_limits_and_unsafe_revision(self) -> None:
        self.tile()
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

        self.tile()
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
        self.assertEqual(json.loads(result.stdout)["lfsFileCount"], 1)
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

    def release_fixture(self) -> tuple[str, str]:
        from tools.deployment.common import canonical_json_bytes
        from tools.deployment.dataset_packages import pack_tile_set, read_tile_sets
        from tools.deployment.tests.fixtures import write_dist
        from tools.deployment.upload_datasets import build_dataset_plan

        legacy = self.commit()
        public = self.repo / "apps/web/public"
        paths = write_dist(public)
        plan = build_dataset_plan(public_root=public)
        entry = pack_tile_set(read_tile_sets(public_root=public)[0], generated_root=public / "datasets/generated",
                              package_root=self.root / "packages")
        lock = {"schemaVersion": 1, "repository": "omggga/morrowind-map", "tileSets": [entry]}
        self.write("config/dataset-releases.lock.json", canonical_json_bytes(lock))
        self.write("config/dataset-upload-plan.json", canonical_json_bytes(plan))
        (public / paths["tile"].lstrip("/")).unlink()
        return legacy, self.commit()

    def test_exports_exact_committed_release_metadata_lock_and_plan(self) -> None:
        _, revision = self.release_fixture()
        lock = (self.repo / "config/dataset-releases.lock.json").read_bytes()
        plan = (self.repo / "config/dataset-upload-plan.json").read_bytes()
        self.write("config/dataset-releases.lock.json", b"invalid working tree")
        self.write("config/dataset-upload-plan.json", b"invalid working tree")
        output = self.root / "public"
        report = export_revision(repo_root=self.repo, revision=revision, output_public_root=output)
        self.assertEqual(report["snapshotMode"], "releases")
        self.assertEqual(report["lfsFileCount"], 0)
        self.assertEqual((output / "config/dataset-releases.lock.json").read_bytes(), lock)
        self.assertEqual((output / "config/dataset-upload-plan.json").read_bytes(), plan)
        self.assertFalse(list((output / "datasets/generated").rglob("*.webp")))
        self.assertTrue(list((output / "datasets/generated").rglob("*.json")))

    def test_explicit_historical_mode_and_trusted_boundary(self) -> None:
        legacy, boundary = self.release_fixture()
        report = check_revision(repo_root=self.repo, revision=legacy, mode="legacy", release_boundary=boundary)
        self.assertEqual(report["snapshotMode"], "legacy")
        with self.assertRaisesRegex(GitDatasetError, "downgrade"):
            check_revision(repo_root=self.repo, revision=boundary, mode="legacy")
        with self.assertRaisesRegex(GitDatasetError, "committed transport lock"):
            check_revision(repo_root=self.repo, revision=legacy, mode="releases")
        with self.assertRaisesRegex(GitDatasetError, "40-character"):
            check_revision(repo_root=self.repo, revision=legacy, release_boundary="HEAD")

    def test_lock_deletion_cannot_downgrade(self) -> None:
        _, boundary = self.release_fixture()
        (self.repo / "config/dataset-releases.lock.json").unlink()
        revision = self.commit()
        for options in ({}, {"mode": "legacy"}, {"release_boundary": boundary}):
            with self.subTest(options=options), self.assertRaisesRegex(GitDatasetError, "(downgrade|transport lock)"):
                check_revision(repo_root=self.repo, revision=revision, **options)

    def test_trusted_boundary_fails_closed_with_shallow_or_unrelated_history(self) -> None:
        _, boundary = self.release_fixture()
        (self.repo / "config/dataset-releases.lock.json").unlink()
        revision = self.commit()
        self.write(".git/shallow", (revision + "\n").encode())
        # The trusted SHA still exists locally, but this shallow root hides ancestry.
        with self.assertRaisesRegex(GitDatasetError, "Cannot prove"):
            check_revision(repo_root=self.repo, revision=revision, release_boundary=boundary)
        with self.assertRaisesRegex(GitDatasetError, "committed transport lock"):
            check_revision(repo_root=self.repo, revision=revision, mode="releases")

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
        _, revision = self.release_fixture()
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

    def test_legacy_export_includes_its_own_optional_plan(self) -> None:
        payload = b'{"historical":"plan"}\n'
        self.write("config/dataset-upload-plan.json", payload)
        revision = self.commit()
        output = self.root / "public"
        config = self.root / "export-config"
        report = export_revision(repo_root=self.repo, revision=revision, output_public_root=output,
                                 output_config_root=config, mode="legacy")
        self.assertEqual(report["snapshotMode"], "legacy")
        self.assertEqual((config / "dataset-upload-plan.json").read_bytes(), payload)
        self.assertFalse((config / "dataset-releases.lock.json").exists())

    def test_release_cli_uses_trusted_imports_from_candidate_cwd(self) -> None:
        import os
        import sys
        from tools.deployment import git_datasets

        _, revision = self.release_fixture()
        marker = self.root / "candidate-executed"
        self.write("tools/__init__.py", f"from pathlib import Path; Path({str(marker)!r}).touch()\n".encode())
        result = subprocess.run(
            [sys.executable, str(Path(git_datasets.__file__).resolve()), "export", "--repo-root", str(self.repo),
             "--revision", revision, "--output-public-root", str(self.root / "public"), "--require-releases"],
            capture_output=True, text=True, cwd=self.repo, env={**os.environ, "PYTHONPATH": str(self.repo)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["snapshotMode"], "releases")
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
