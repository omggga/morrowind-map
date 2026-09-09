from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.land_renderer.spike import CONTROL_SITES
from tools.openmw_renderer.images import PixelDifference
from tools.openmw_renderer.profile import (
    DOCKER_BASE_IMAGE,
    OPENMW_COMMIT,
    PROFILE_ID,
    UBUNTU_SNAPSHOT,
    render_console_script,
    render_openmw_cfg,
    render_settings_cfg,
)
from tools.openmw_renderer.spike import (
    RENDERER_CODE_PATHS,
    VISUAL_FEATURES,
    DockerImageInfo,
    RenderTarget,
    _reproducibility_difference_passes,
    _seam_difference_passes,
    coordinate_alignment,
    docker_image_info,
    docker_run_command,
    prepare_run_profile,
    primary_targets,
    renderer_fingerprint,
    repeat_targets,
    resource_resolution_report,
    runtime_capture_evidence,
    runtime_environment_report,
    seam_evidence_fingerprint,
    visual_receipt_report,
    write_visual_receipt_template,
)


class RenderTargetTests(unittest.TestCase):
    def test_primary_targets_are_the_exact_five_centres_and_cell_offsets(self) -> None:
        expected = (
            RenderTarget("balmora", "balmora", "primary", (-3, -2)),
            RenderTarget("balmora-east", "balmora", "primary", (-2, -2)),
            RenderTarget("balmora-north", "balmora", "primary", (-3, -1)),
            RenderTarget("old-ebonheart", "old-ebonheart", "primary", (7, -19)),
            RenderTarget("old-ebonheart-east", "old-ebonheart", "primary", (8, -19)),
            RenderTarget("old-ebonheart-north", "old-ebonheart", "primary", (7, -18)),
            RenderTarget("othrenis", "othrenis", "primary", (16, -29)),
            RenderTarget("othrenis-east", "othrenis", "primary", (17, -29)),
            RenderTarget("othrenis-north", "othrenis", "primary", (16, -28)),
            RenderTarget("gorne", "gorne", "primary", (19, -14)),
            RenderTarget("gorne-east", "gorne", "primary", (20, -14)),
            RenderTarget("gorne-north", "gorne", "primary", (19, -13)),
            RenderTarget("nan-iban", "nan-iban", "primary", (41, -30)),
            RenderTarget("nan-iban-east", "nan-iban", "primary", (42, -30)),
            RenderTarget("nan-iban-north", "nan-iban", "primary", (41, -29)),
        )

        self.assertEqual(primary_targets(), expected)
        self.assertEqual(len(primary_targets()), 15)

    def test_repeat_targets_are_the_exact_five_centre_cells(self) -> None:
        expected = (
            RenderTarget("balmora", "balmora", "repeat", (-3, -2)),
            RenderTarget("old-ebonheart", "old-ebonheart", "repeat", (7, -19)),
            RenderTarget("othrenis", "othrenis", "repeat", (16, -29)),
            RenderTarget("gorne", "gorne", "repeat", (19, -14)),
            RenderTarget("nan-iban", "nan-iban", "repeat", (41, -30)),
        )

        self.assertEqual(repeat_targets(), expected)
        self.assertEqual(len(repeat_targets()), 5)


class DockerCommandTests(unittest.TestCase):
    def test_command_is_isolated_and_exposes_only_the_expected_paths_and_env(self) -> None:
        target = RenderTarget(
            "old-ebonheart-east",
            "old-ebonheart",
            "primary",
            (8, -19),
        )

        with (
            patch(
                "tools.openmw_renderer.spike._container_name",
                return_value="mwm45-fixture-primary-old-ebonheart-east",
            ),
            patch("tools.openmw_renderer.spike.os.getuid", return_value=501),
            patch("tools.openmw_renderer.spike.os.getgid", return_value=20),
        ):
            command = docker_run_command(
                image="morrowind-map-openmw:test",
                source_root=Path("/host/game"),
                profile_root=Path("/host/run/profile"),
                output_root=Path("/host/output"),
                target=target,
            )

        self.assertEqual(
            command,
            [
                "docker",
                "run",
                "--rm",
                "--name",
                "mwm45-fixture-primary-old-ebonheart-east",
                "--platform",
                "linux/amd64",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--pids-limit",
                "512",
                "--memory",
                "4g",
                "--tmpfs",
                "/tmp:rw,nosuid,size=1g",
                "--user",
                "501:20",
                "--security-opt",
                "no-new-privileges",
                "--mount",
                "type=bind,src=/host/game/bsa,dst=/game/bsa,readonly",
                "--mount",
                "type=bind,src=/host/game/tamriel-data,dst=/game/tamriel-data,readonly",
                "--mount",
                "type=bind,src=/host/game/tamriel-rebuilt/00 Core/Data Files,"
                "dst=/game/tamriel-rebuilt/00 Core/Data Files,readonly",
                "--mount",
                "type=bind,src=/host/run/profile,dst=/profile",
                "--mount",
                "type=bind,src=/host/output,dst=/out",
                "--env",
                "MWMAP_EXPORT_CELL=8,-19",
                "--env",
                "MWMAP_EXPORT_PATH=/out/raw/primary/old-ebonheart-east.png",
                "--env",
                "MWMAP_EXPORT_GUTTER_PIXELS=16",
                "--env",
                "LIBGL_ALWAYS_SOFTWARE=1",
                "--env",
                "GALLIUM_DRIVER=llvmpipe",
                "--env",
                "OPENMW_DONT_PRECOMPILE=1",
                "--env",
                "OSG_THREADING=SingleThreaded",
                "morrowind-map-openmw:test",
            ],
        )
        self.assertNotIn("--privileged", command)
        self.assertNotIn("host", command)
        self.assertNotIn(
            "type=bind,src=/host/game,dst=/game,readonly",
            command,
        )
        self.assertEqual(command.count("--name"), 1)
        self.assertEqual(command.count("--read-only"), 1)


class EntrypointRegressionTests(unittest.TestCase):
    def test_entrypoint_starts_xvfb_run_without_replacing_pid_one_shell(self) -> None:
        entrypoint = Path(__file__).resolve().parents[1] / "entrypoint.sh"
        executable_lines = "\n".join(
            line
            for line in entrypoint.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )

        self.assertRegex(executable_lines, r"(?m)^\s*xvfb-run(?:\s|$)")
        self.assertNotRegex(executable_lines, r"(?m)^\s*exec\s+xvfb-run(?:\s|$)")


class PatchContractTests(unittest.TestCase):
    def test_export_camera_excludes_openmw_dynamic_object_mask(self) -> None:
        patch = (
            Path(__file__).resolve().parents[1]
            / "patches/openmw-0.51.0-map-export-once.patch"
        ).read_text(encoding="utf-8")
        added_lines = [
            line[1:]
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        static_capture_mask = (
            "Mask_Scene | Mask_SimpleWater | Mask_Terrain | Mask_Static"
        )

        self.assertEqual(
            sum(static_capture_mask in line for line in added_lines),
            3,
        )
        self.assertNotIn("Mask_Object", "\n".join(added_lines))


class RunProfileTests(unittest.TestCase):
    def test_each_run_gets_an_exact_self_contained_profile_layout(self) -> None:
        primary = RenderTarget("balmora-east", "balmora", "primary", (-2, -2))
        repeated = RenderTarget("balmora", "balmora", "repeat", (-3, -2))

        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            primary_root = prepare_run_profile(output_root, primary)
            repeat_root = prepare_run_profile(output_root, repeated)

            self.assertEqual(
                primary_root,
                output_root / "runs/primary/balmora-east/profile",
            )
            self.assertEqual(
                repeat_root,
                output_root / "runs/repeat/balmora/profile",
            )
            self.assertNotEqual(primary_root, repeat_root)

            for profile_root, target in (
                (primary_root, primary),
                (repeat_root, repeated),
            ):
                with self.subTest(target=target.key, pass_name=target.pass_name):
                    entries = {
                        str(path.relative_to(profile_root))
                        for path in profile_root.rglob("*")
                    }
                    self.assertEqual(
                        entries,
                        {
                            "commands.txt",
                            "config",
                            "config/openmw.cfg",
                            "config/settings.cfg",
                            "user-data",
                        },
                    )
                    self.assertTrue((profile_root / "user-data").is_dir())
                    self.assertEqual(
                        (profile_root / "config/openmw.cfg").read_text(
                            encoding="utf-8"
                        ),
                        render_openmw_cfg(),
                    )
                    self.assertEqual(
                        (profile_root / "config/settings.cfg").read_text(
                            encoding="utf-8"
                        ),
                        render_settings_cfg(),
                    )
                    self.assertEqual(
                        (profile_root / "commands.txt").read_text(encoding="utf-8"),
                        render_console_script(target.cell),
                    )


class RendererFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_sensitive_to_every_renderer_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            original_payloads: dict[str, bytes] = {}
            for index, relative in enumerate(RENDERER_CODE_PATHS):
                payload = f"fixture-{index}-{relative}\n".encode()
                original_payloads[relative] = payload
                path = repo_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)

            baseline = renderer_fingerprint(repo_root)
            self.assertEqual(renderer_fingerprint(repo_root), baseline)

            for relative, payload in original_payloads.items():
                with self.subTest(relative=relative):
                    path = repo_root / relative
                    path.write_bytes(payload + b"changed\n")
                    self.assertNotEqual(renderer_fingerprint(repo_root), baseline)
                    path.write_bytes(payload)

            (repo_root / "untracked.txt").write_text("ignored", encoding="utf-8")
            self.assertEqual(renderer_fingerprint(repo_root), baseline)


class CoordinateAlignmentTests(unittest.TestCase):
    def test_all_control_cells_roundtrip_within_one_native_pixel(self) -> None:
        for site in CONTROL_SITES:
            with self.subTest(site=site.slug, cell=site.cell):
                report = coordinate_alignment(site)

                self.assertLessEqual(report["maxRoundtripPixelError"], 1.0)
                self.assertTrue(report["passesOnePixelGate"])
                self.assertEqual(
                    [sample["pixelEdge"] for sample in report["samples"]],
                    [[0.0, 0.0], [256.0, 256.0], [512.0, 512.0]],
                )


class DifferenceToleranceBoundaryTests(unittest.TestCase):
    def test_reproducibility_tolerance_accepts_limits_and_rejects_each_excess(self) -> None:
        at_limits = PixelDifference(
            pixels=10_000,
            differing_pixels=1,
            mean_absolute_channel_delta=0.0001,
            maximum_channel_delta=4,
        )
        self.assertTrue(_reproducibility_difference_passes(at_limits))

        beyond_limits = (
            PixelDifference(10_000, 2, 0.0001, 4),
            PixelDifference(10_000, 1, 0.0001001, 4),
            PixelDifference(10_000, 1, 0.0001, 5),
        )
        for difference in beyond_limits:
            with self.subTest(difference=difference):
                self.assertFalse(_reproducibility_difference_passes(difference))

    def test_seam_tolerance_accepts_limits_and_rejects_each_excess(self) -> None:
        at_limits = PixelDifference(
            pixels=20,
            differing_pixels=7,
            mean_absolute_channel_delta=0.3,
            maximum_channel_delta=32,
        )
        self.assertTrue(_seam_difference_passes(at_limits))

        beyond_limits = (
            PixelDifference(20, 8, 0.3, 32),
            PixelDifference(20, 7, 0.3001, 32),
            PixelDifference(20, 7, 0.3, 33),
        )
        for difference in beyond_limits:
            with self.subTest(difference=difference):
                self.assertFalse(_seam_difference_passes(difference))


class ResourceResolutionReportTests(unittest.TestCase):
    def test_absent_logs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            self.assertEqual(
                resource_resolution_report(output_root),
                {
                    "logsInspected": 0,
                    "missingExpectedLogs": [],
                    "missingResourceMessages": [],
                    "passes": False,
                },
            )

    def test_clean_discovered_log_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            clean_log = output_root / "logs/primary/balmora.log"
            clean_log.parent.mkdir(parents=True)
            clean_log.write_text(
                "Loading cell Balmora\nAll requested resources resolved\n",
                encoding="utf-8",
            )
            self.assertEqual(
                resource_resolution_report(output_root),
                {
                    "logsInspected": 1,
                    "missingExpectedLogs": [],
                    "missingResourceMessages": [],
                    "passes": True,
                },
            )

    def test_only_exact_expected_logs_are_inspected_and_missing_log_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            expected_log = output_root / "logs/primary/balmora.log"
            unrelated_log = output_root / "logs/repeat/unrelated.log"
            expected_log.parent.mkdir(parents=True)
            unrelated_log.parent.mkdir(parents=True)
            expected_log.write_text("MWMAP export completed\n", encoding="utf-8")
            unrelated_log.write_text(
                "Failed to load mesh meshes/not-part-of-this-run.nif\n",
                encoding="utf-8",
            )

            self.assertEqual(
                resource_resolution_report(
                    output_root,
                    expected_logs=(
                        "logs/primary/balmora.log",
                        "logs/primary/missing.log",
                    ),
                ),
                {
                    "logsInspected": 1,
                    "missingExpectedLogs": ["logs/primary/missing.log"],
                    "missingResourceMessages": [],
                    "passes": False,
                },
            )

            self.assertEqual(
                resource_resolution_report(
                    output_root,
                    expected_logs=("logs/primary/balmora.log",),
                ),
                {
                    "logsInspected": 1,
                    "missingExpectedLogs": [],
                    "missingResourceMessages": [],
                    "passes": True,
                },
            )

    def test_missing_resources_are_detected_with_log_and_trimmed_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            primary_log = output_root / "logs/primary/z-last.log"
            repeat_log = output_root / "logs/repeat/a-first.log"
            primary_log.parent.mkdir(parents=True)
            repeat_log.parent.mkdir(parents=True)
            primary_log.write_text(
                "normal startup\n  Failed to load mesh meshes/missing.nif  \n",
                encoding="utf-8",
            )
            repeat_log.write_text(
                "Texture textures/missing.dds NOT FOUND\nCould not find sound.wav\n",
                encoding="utf-8",
            )

            self.assertEqual(
                resource_resolution_report(output_root),
                {
                    "logsInspected": 2,
                    "missingExpectedLogs": [],
                    "missingResourceMessages": [
                        {
                            "log": "logs/primary/z-last.log",
                            "line": "Failed to load mesh meshes/missing.nif",
                        },
                        {
                            "log": "logs/repeat/a-first.log",
                            "line": "Texture textures/missing.dds NOT FOUND",
                        },
                        {
                            "log": "logs/repeat/a-first.log",
                            "line": "Could not find sound.wav",
                        },
                    ],
                    "passes": False,
                },
            )


class RuntimeCaptureEvidenceTests(unittest.TestCase):
    EXACT_CAMERA_LOG = (
        "MWMAP export target -3,-2: 544px over 8704 world units; "
        "center=(-20480,-12288); "
        "bounds=[-24832,-16128]x[-16640,-7936]; "
        "raster=top-left,+x,-y,flipVertical=false\n"
    )

    @staticmethod
    def _run_result(
        *,
        key: str = "balmora",
        pass_name: str = "primary",
        cell: tuple[int, int] = (-3, -2),
    ) -> dict[str, object]:
        return {
            "key": key,
            "pass": pass_name,
            "cell": list(cell),
            "logPath": f"logs/{pass_name}/{key}.log",
        }

    def test_exact_runtime_camera_evidence_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            run = self._run_result()
            log_path = output_root / str(run["logPath"])
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "startup\n" + self.EXACT_CAMERA_LOG + "shutdown\n",
                encoding="utf-8",
            )

            report = runtime_capture_evidence(output_root, (run,))

            self.assertTrue(report["passes"])
            self.assertEqual(len(report["captures"]), 1)  # type: ignore[arg-type]
            capture = report["captures"][0]  # type: ignore[index]
            self.assertEqual(capture["run"], "primary/balmora")
            self.assertEqual(capture["cell"], [-3, -2])
            self.assertEqual(capture["maxPixelError"], 0.0)
            self.assertTrue(capture["passes"])
            self.assertEqual(
                capture["cameraLogMatches"],
                [
                    {
                        "actualCell": [-3, -2],
                        "actualPixels": 544,
                        "actualWorldExtent": 8704.0,
                        "actualCenter": [-20480.0, -12288.0],
                        "actualBounds": [-24832.0, -16128.0, -16640.0, -7936.0],
                        "expectedBounds": [-24832.0, -16128.0, -16640.0, -7936.0],
                        "maxPixelError": 0.0,
                        "passes": True,
                    }
                ],
            )

    def test_wrong_bounds_orientation_or_duplicate_camera_evidence_fails(self) -> None:
        fixtures = {
            "wrong-bounds": self.EXACT_CAMERA_LOG.replace("-16128", "-16096"),
            "wrong-orientation": self.EXACT_CAMERA_LOG.replace(
                "raster=top-left,+x,-y,flipVertical=false",
                "raster=bottom-left,+x,+y,flipVertical=true",
            ),
            "duplicate": self.EXACT_CAMERA_LOG * 2,
        }
        for name, contents in fixtures.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output_root = Path(directory)
                run = self._run_result()
                log_path = output_root / str(run["logPath"])
                log_path.parent.mkdir(parents=True)
                log_path.write_text(contents, encoding="utf-8")

                report = runtime_capture_evidence(output_root, (run,))

                capture = report["captures"][0]  # type: ignore[index]
                self.assertFalse(capture["passes"])
                self.assertFalse(report["passes"])
                if name == "wrong-bounds":
                    self.assertEqual(capture["maxPixelError"], 2.0)
                    self.assertEqual(len(capture["cameraLogMatches"]), 1)
                elif name == "wrong-orientation":
                    self.assertIsNone(capture["maxPixelError"])
                    self.assertEqual(capture["cameraLogMatches"], [])
                else:
                    self.assertEqual(capture["maxPixelError"], 0.0)
                    self.assertEqual(len(capture["cameraLogMatches"]), 2)


class VisualReceiptTests(unittest.TestCase):
    PROFILE_HASH = "profile-fixture"
    EXECUTION_HASH = "execution-fixture"
    REQUIRED_FEATURES = (
        "roofs",
        "buildings",
        "bridges",
        "trees",
        "walls",
        "water",
        "alphaGeometry",
    )

    @staticmethod
    def _controls() -> dict[str, object]:
        return {
            site.slug: {
                "sha256": f"{index + 1:064x}",
                "nativeRgbaSha256": f"{index + 101:064x}",
            }
            for index, site in enumerate(CONTROL_SITES)
        }

    @staticmethod
    def _seams() -> dict[str, object]:
        return {
            "controls": {
                site.slug: {
                    direction: {
                        "differingFraction": 0.1,
                        "meanAbsoluteChannelDelta": 0.2,
                        "maximumChannelDelta": 16,
                        "passes": True,
                    }
                    for direction in ("east", "north")
                }
                for site in CONTROL_SITES
            },
            "passes": True,
        }

    def _valid_receipt(
        self,
        controls: dict[str, object],
        seams: dict[str, object] | None = None,
    ) -> dict[str, object]:
        seams = seams if seams is not None else self._seams()
        return {
            "schemaVersion": 1,
            "profileId": PROFILE_ID,
            "profileFingerprint": self.PROFILE_HASH,
            "executionFingerprint": self.EXECUTION_HASH,
            "reviewer": "visual-reviewer",
            "reviewedAt": "2026-08-27T12:00:00Z",
            "seamEvidenceFingerprint": seam_evidence_fingerprint(seams),
            "seamsApproved": True,
            "seamNotes": "Reviewed east and north overlaps for all controls.",
            "controls": {
                site.slug: {
                    "webpSha256": controls[site.slug]["sha256"],  # type: ignore[index]
                    "nativeRgbaSha256": controls[site.slug][  # type: ignore[index]
                        "nativeRgbaSha256"
                    ],
                    "observedFeatures": list(self.REQUIRED_FEATURES),
                    "referencesCompared": (
                        ["LAND", "UESP", "MIM"]
                        if site.slug == "balmora"
                        else ["LAND", "UESP"]
                    ),
                    "approved": True,
                    "notes": f"Reviewed {site.slug} against required references.",
                }
                for site in CONTROL_SITES
            },
        }

    @staticmethod
    def _write_receipt(output_root: Path, receipt: dict[str, object]) -> None:
        (output_root / "visual-receipt.json").write_text(
            json.dumps(receipt),
            encoding="utf-8",
        )

    def _report(
        self,
        output_root: Path,
        controls: dict[str, object],
        seams: dict[str, object] | None = None,
    ) -> dict[str, object]:
        seams = seams if seams is not None else self._seams()
        return visual_receipt_report(
            output_root,
            controls,
            seams,
            profile_hash=self.PROFILE_HASH,
            execution_hash=self.EXECUTION_HASH,
        )

    def test_missing_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                self._report(Path(directory), self._controls()),
                {
                    "path": "visual-receipt.json",
                    "present": False,
                    "controls": {},
                    "featureCoverage": [],
                    "referenceCoverage": [],
                    "seamsApproved": False,
                    "passes": False,
                },
            )

    def test_exact_five_control_receipt_with_full_evidence_passes(self) -> None:
        self.assertEqual(set(self.REQUIRED_FEATURES), VISUAL_FEATURES)
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            controls = self._controls()
            self._write_receipt(output_root, self._valid_receipt(controls))

            report = self._report(output_root, controls)

            expected_sites = {site.slug for site in CONTROL_SITES}
            self.assertTrue(report["present"])
            self.assertTrue(report["passes"])
            self.assertEqual(set(report["controls"]), expected_sites)  # type: ignore[arg-type]
            self.assertEqual(len(report["controls"]), 5)  # type: ignore[arg-type]
            self.assertTrue(all(report["checks"].values()))  # type: ignore[union-attr]
            self.assertEqual(
                set(report["featureCoverage"]),  # type: ignore[arg-type]
                set(self.REQUIRED_FEATURES),
            )
            self.assertEqual(report["referenceCoverage"], ["land", "mim", "uesp"])
            self.assertTrue(report["seamsApproved"])
            for site in CONTROL_SITES:
                control_report = report["controls"][site.slug]  # type: ignore[index]
                self.assertTrue(control_report["passes"])
                self.assertTrue(all(control_report["checks"].values()))

    def test_stale_control_hashes_fail(self) -> None:
        for field, check in (
            ("webpSha256", "webpHash"),
            ("nativeRgbaSha256", "nativeRgbaHash"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                output_root = Path(directory)
                controls = self._controls()
                receipt = self._valid_receipt(controls)
                receipt["controls"]["balmora"][field] = "0" * 64  # type: ignore[index]
                self._write_receipt(output_root, receipt)

                report = self._report(output_root, controls)

                self.assertFalse(report["passes"])
                balmora = report["controls"]["balmora"]  # type: ignore[index]
                self.assertFalse(balmora["checks"][check])

    def test_missing_unknown_or_unapproved_feature_evidence_fails(self) -> None:
        scenarios = ("missing-feature", "unknown-feature", "unapproved")
        for scenario in scenarios:
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory() as directory,
            ):
                output_root = Path(directory)
                controls = self._controls()
                receipt = self._valid_receipt(controls)
                receipt_controls = receipt["controls"]  # type: ignore[assignment]
                if scenario == "missing-feature":
                    for item in receipt_controls.values():  # type: ignore[union-attr]
                        item["observedFeatures"].remove("alphaGeometry")
                elif scenario == "unknown-feature":
                    receipt_controls["balmora"]["observedFeatures"].append("actors")  # type: ignore[index]
                else:
                    receipt_controls["balmora"]["approved"] = False  # type: ignore[index]
                self._write_receipt(output_root, receipt)

                report = self._report(output_root, controls)

                self.assertFalse(report["passes"])
                if scenario == "missing-feature":
                    self.assertFalse(report["checks"]["allRequiredFeaturesObserved"])  # type: ignore[index]
                elif scenario == "unknown-feature":
                    self.assertFalse(
                        report["controls"]["balmora"]["checks"]["knownFeatures"]  # type: ignore[index]
                    )
                else:
                    self.assertFalse(
                        report["controls"]["balmora"]["checks"]["approved"]  # type: ignore[index]
                    )

    def test_wrong_profile_or_execution_fingerprint_fails(self) -> None:
        for field, check in (
            ("profileFingerprint", "profileFingerprint"),
            ("executionFingerprint", "executionFingerprint"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                output_root = Path(directory)
                controls = self._controls()
                receipt = self._valid_receipt(controls)
                receipt[field] = "stale-fingerprint"
                self._write_receipt(output_root, receipt)

                report = self._report(output_root, controls)

                self.assertFalse(report["passes"])
                self.assertFalse(report["checks"][check])  # type: ignore[index]

    def test_stale_or_unapproved_seam_evidence_fails_closed(self) -> None:
        for scenario in ("stale-fingerprint", "unapproved"):
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory() as directory,
            ):
                output_root = Path(directory)
                controls = self._controls()
                seams = self._seams()
                receipt = self._valid_receipt(controls, seams)
                if scenario == "stale-fingerprint":
                    receipt["seamEvidenceFingerprint"] = "stale-seam-fingerprint"
                else:
                    receipt["seamsApproved"] = False
                self._write_receipt(output_root, receipt)

                report = self._report(output_root, controls, seams)

                self.assertFalse(report["passes"])
                check = (
                    "seamEvidenceFingerprint"
                    if scenario == "stale-fingerprint"
                    else "seamsApproved"
                )
                self.assertFalse(report["checks"][check])  # type: ignore[index]

    def test_template_contains_current_binding_and_fail_closed_control_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            controls = self._controls()
            seams = self._seams()

            write_visual_receipt_template(
                output_root,
                controls,
                seams,
                profile_hash=self.PROFILE_HASH,
                execution_hash=self.EXECUTION_HASH,
            )

            template = json.loads(
                (output_root / "visual-receipt.template.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(template["schemaVersion"], 1)
            self.assertEqual(template["profileId"], PROFILE_ID)
            self.assertEqual(template["profileFingerprint"], self.PROFILE_HASH)
            self.assertEqual(template["executionFingerprint"], self.EXECUTION_HASH)
            self.assertEqual(template["reviewer"], "")
            self.assertEqual(template["reviewedAt"], "")
            self.assertEqual(
                template["seamEvidenceFingerprint"],
                seam_evidence_fingerprint(seams),
            )
            self.assertIs(template["seamsApproved"], False)
            self.assertEqual(template["seamNotes"], "")
            self.assertEqual(
                set(template["controls"]),
                {site.slug for site in CONTROL_SITES},
            )
            for site in CONTROL_SITES:
                entry = template["controls"][site.slug]
                self.assertEqual(entry["webpSha256"], controls[site.slug]["sha256"])  # type: ignore[index]
                self.assertEqual(
                    entry["nativeRgbaSha256"],
                    controls[site.slug]["nativeRgbaSha256"],  # type: ignore[index]
                )
                self.assertEqual(entry["observedFeatures"], [])
                self.assertEqual(entry["referencesCompared"], [])
                self.assertIs(entry["approved"], False)
                self.assertEqual(entry["notes"], "")


class RuntimeEnvironmentTests(unittest.TestCase):
    def test_docker_image_info_requires_pinned_linux_amd64_metadata(self) -> None:
        payload = [
            {
                "Id": "sha256:fixture",
                "RepoDigests": ["morrowind-map-openmw@sha256:fixture"],
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.revision": OPENMW_COMMIT,
                        "io.morrowind-map.stage": "4.5",
                        "io.morrowind-map.renderer-fingerprint": "renderer-fixture",
                        "io.morrowind-map.base-image": DOCKER_BASE_IMAGE,
                        "io.morrowind-map.ubuntu-snapshot": UBUNTU_SNAPSHOT,
                    }
                },
            }
        ]
        with patch(
            "tools.openmw_renderer.spike.subprocess.run",
            return_value=Mock(stdout=json.dumps(payload)),
        ) as run:
            info = docker_image_info(
                "morrowind-map-openmw:test",
                expected_renderer_hash="renderer-fixture",
            )

        run.assert_called_once()
        self.assertEqual(info.image_id, "sha256:fixture")
        self.assertEqual(
            info.repo_digests,
            ("morrowind-map-openmw@sha256:fixture",),
        )
        self.assertTrue(info.contract_passes)
        self.assertEqual(info.contract_errors, ())

    def test_runtime_environment_requires_image_platform_software_gl_and_commit(self) -> None:
        image_info = DockerImageInfo(
            image="morrowind-map-openmw:test",
            image_id="sha256:fixture",
            repo_digests=(),
            os="linux",
            architecture="amd64",
            labels={
                "org.opencontainers.image.revision": OPENMW_COMMIT,
                "io.morrowind-map.stage": "4.5",
            },
            contract_errors=(),
        )

        report = runtime_environment_report(
            image_info,
            build_manifest=f"openmw_commit={OPENMW_COMMIT}\n",
            glxinfo="OpenGL renderer string: llvmpipe (LLVM 18.1.3, 256 bits)\n",
        )

        self.assertEqual(report["openGlRenderer"], "llvmpipe (LLVM 18.1.3, 256 bits)")
        self.assertEqual(
            report["checks"],
            {
                "dockerImageIdentity": True,
                "linuxAmd64": True,
                "softwareRenderer": True,
                "buildManifestCommit": True,
            },
        )
        self.assertTrue(report["passes"])

        invalid = runtime_environment_report(
            DockerImageInfo(
                image=image_info.image,
                image_id=image_info.image_id,
                repo_digests=(),
                os="darwin",
                architecture="arm64",
                labels={},
                contract_errors=("invalid fixture image",),
            ),
            build_manifest="openmw_commit=wrong\n",
            glxinfo="OpenGL renderer string: Apple M4\n",
        )
        self.assertEqual(
            invalid["checks"],
            {
                "dockerImageIdentity": False,
                "linuxAmd64": False,
                "softwareRenderer": False,
                "buildManifestCommit": False,
            },
        )
        self.assertFalse(invalid["passes"])


if __name__ == "__main__":
    unittest.main()
