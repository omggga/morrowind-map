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


if __name__ == "__main__":
    unittest.main()
