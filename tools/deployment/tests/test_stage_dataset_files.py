from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.deployment.common import DeploymentError
from tools.deployment.dataset_packages import pack_datasets
from tools.deployment.stage_dataset_files import stage_datasets
from tools.deployment.tests.fixtures import write_dist


class StageDatasetFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.public = self.root / 'apps/web/public'
        self.paths = write_dist(self.public)
        result = pack_datasets(repo_root=self.root, selector='all', bootstrap=True, release='v1.0.0')
        self.lock = self.root / 'config/dataset-releases.lock.json'
        self.lock.parent.mkdir()
        shutil.copyfile(result['lockPath'], self.lock)
        self.plan = self.root / 'config/dataset-upload-plan.json'
        self.plan.write_text('unchanged until validation\n')
        self.tile = self.public / self.paths['tile'].lstrip('/')
        self.tile_bytes = self.tile.read_bytes()
        self.tile.write_text('version https://git-lfs.github.com/spec/v1\n'
                             f'oid sha256:{hashlib.sha256(self.tile_bytes).hexdigest()}\n'
                             f'size {len(self.tile_bytes)}\n')
        self.stale = self.public / 'datasets/generated/retired/locations.json'
        self.stale.parent.mkdir()
        self.stale.write_text('{}\n')
        self.env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('add', '--', 'apps', 'config/dataset-upload-plan.json')
        self.git('commit', '-qm', 'fixture')
        self.tile.write_bytes(self.tile_bytes)
        (self.root / '.gitignore').write_text('apps/web/public/datasets/generated/\nlocal-data/\n')
        (self.root / 'unrelated.txt').write_text('already staged\n')
        self.git('add', 'unrelated.txt')

    def git(self, *args: str) -> bytes:
        return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', *args],
                                       cwd=self.root, env=self.env)

    def test_stages_only_active_json_and_transport_preserving_local_tiles(self) -> None:
        stage_datasets(repo_root=self.root)
        tracked = set(self.git('ls-files', '-z').decode().split('\0'))
        self.assertNotIn(str(self.tile.relative_to(self.root)), tracked)
        self.assertNotIn(str(self.stale.relative_to(self.root)), tracked)
        self.assertEqual(self.tile.read_bytes(), self.tile_bytes)
        self.assertEqual(self.stale.read_text(), '{}\n')
        for name in ('locations', 'locale'):
            self.assertIn('apps/web/public' + self.paths[name], tracked)
        self.assertEqual(self.git('show', ':config/dataset-releases.lock.json'), self.lock.read_bytes())
        self.assertEqual(self.git('show', ':config/dataset-upload-plan.json'), self.plan.read_bytes())
        self.assertIn('unrelated.txt', tracked)
        self.assertFalse(any(path.startswith('local-data/') for path in tracked))

    def test_missing_or_incomplete_lock_does_not_mutate_index_or_plan(self) -> None:
        for payload in (None, b'{"schemaVersion":1,"repository":"omggga/morrowind-map","tileSets":[]}\n'):
            with self.subTest(payload=payload):
                self.lock.unlink(missing_ok=True)
                if payload is not None:
                    self.lock.write_bytes(payload)
                index_before = self.git('ls-files', '--stage', '-z')
                plan_before = self.plan.read_bytes()
                with self.assertRaises((DeploymentError, OSError)):
                    stage_datasets(repo_root=self.root)
                self.assertEqual(self.git('ls-files', '--stage', '-z'), index_before)
                self.assertEqual(self.plan.read_bytes(), plan_before)
                self.assertEqual(self.tile.read_bytes(), self.tile_bytes)


if __name__ == '__main__':
    unittest.main()
