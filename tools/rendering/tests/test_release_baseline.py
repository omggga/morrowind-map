from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from tools.deployment.tests import test_dataset_packages as package_fixtures
from tools.deployment.upload_datasets import build_dataset_plan
from tools.rendering import cli, common


class ReleaseBaselineTests(unittest.TestCase):
    def test_ready_five_map_baseline_preserves_other_maps_after_single_map_adoption(self) -> None:
        fixture = package_fixtures.DatasetPackageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root, public = fixture.root, fixture.public
        for dataset_id in ('second-map', 'third-map', 'fourth-map', 'fifth-map'):
            fixture.add_map(dataset_id, [fixture.webp(24)])
        before = build_dataset_plan(public_root=public)
        self.assertEqual(len(before['datasets']), 5)
        original_bytes = {
            entry['path']: (public / 'datasets/generated' / entry['path']).read_bytes()
            for entry in before['files']
        }
        stale = public / 'datasets/generated/stale-map/unused.webp'
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b'unreferenced local output')

        candidate = root / 'local-data/render/candidate/public'
        common.copy_public_tree(public, candidate)
        self.assertEqual(build_dataset_plan(public_root=candidate), before)
        self.assertFalse((candidate / stale.relative_to(public)).exists())
        for relative in original_bytes:
            self.assertNotEqual(
                (public / 'datasets/generated' / relative).stat().st_ino,
                (candidate / 'datasets/generated' / relative).stat().st_ino,
            )

        fixture.public = candidate
        fixture.add_map('second-map', [fixture.webp(24, b'y')])
        after = build_dataset_plan(public_root=candidate)
        self.assertNotEqual(after['graphSha256'], before['graphSha256'])
        self.assertEqual(build_dataset_plan(public_root=public), before)
        unchanged = lambda plan: {
            entry['datasetId']: entry for entry in plan['datasets']
            if entry['datasetId'] != 'second-map'
        }
        self.assertEqual(unchanged(after), unchanged(before))

        with mock.patch.object(cli, 'REPO_ROOT', root), \
             mock.patch.object(cli.subprocess, 'run') as browser_check, \
             redirect_stdout(StringIO()):
            cli.use_candidate(candidate)
        browser_check.assert_called_once()
        self.assertEqual(browser_check.call_args.args[0], ['pnpm', 'test:acceptance:rendered'])
        self.assertEqual(
            browser_check.call_args.kwargs['env']['MORROWIND_RENDER_PUBLIC_ROOT'], str(candidate),
        )
        self.assertEqual(build_dataset_plan(public_root=public), after)
        self.assertEqual(json.loads((root / 'config/dataset-upload-plan.json').read_bytes()), after)
        for relative, payload in original_bytes.items():
            self.assertEqual((public / 'datasets/generated' / relative).read_bytes(), payload)


if __name__ == '__main__':
    unittest.main()
