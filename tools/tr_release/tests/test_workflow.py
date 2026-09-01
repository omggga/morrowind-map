from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.tr_release import workflow
from tools.tr_release.workflow import (
    ACTIVATION_STEP,
    PRE_ACTIVATION_ARGV,
    PRE_ACTIVATION_COMMANDS,
    TOOLCHAIN_ONLY_ARGV,
    TOOLCHAIN_ONLY_COMMANDS,
    WorkflowCommandError,
    run_workflow,
)


EXPECTED_PRE_ACTIVATION_ARGV = (
    ("pnpm", "data:tr:check"),
    ("pnpm", "data:tr:lock"),
    ("pnpm", "data:tr:plan"),
    ("pnpm", "data:tr:renderer:smoke"),
    ("pnpm", "data:tr:renderer:render"),
    ("pnpm", "data:tr:renderer:finalize"),
    ("pnpm", "data:tr:renderer:stabilize"),
    ("pnpm", "data:tr:renderer:audit"),
    ("pnpm", "data:tr:dataset:validate"),
    ("pnpm", "data:tr:dataset:prepare"),
    ("pnpm", "data:tr:catalog:build"),
    ("pnpm", "data:tr:catalog:validate"),
    ("pnpm", "data:tr:catalog:prepare"),
    ("pnpm", "data:tr:manifest:build"),
    ("pnpm", "data:tr:release:verify"),
    ("pnpm", "test:acceptance:prepared:candidate"),
    ("pnpm", "verify"),
)
EXPECTED_PRE_ACTIVATION_COMMANDS = tuple(
    " ".join(argv) for argv in EXPECTED_PRE_ACTIVATION_ARGV
)


class TrReleaseWorkflowTests(unittest.TestCase):
    def test_package_scripts_expose_orchestrator_and_every_gate_but_no_direct_activation(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        scripts = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))[
            "scripts"
        ]

        self.assertEqual(scripts["data:tr:release"], "python3 -m tools.tr_release.workflow")
        for _, script_name in EXPECTED_PRE_ACTIVATION_ARGV:
            self.assertIn(script_name, scripts)
        self.assertNotIn("data:tr:activate", scripts)
        self.assertNotIn("data:tr:renderer:benchmark", scripts)

    def test_mandatory_pre_activation_contract_has_exact_argv_order(self) -> None:
        self.assertEqual(PRE_ACTIVATION_ARGV, EXPECTED_PRE_ACTIVATION_ARGV)
        self.assertEqual(PRE_ACTIVATION_COMMANDS, EXPECTED_PRE_ACTIVATION_COMMANDS)
        self.assertEqual(ACTIVATION_STEP, "activate_after_gates")
        self.assertNotIn(("pnpm", "data:tr:activate"), PRE_ACTIVATION_ARGV)

    def test_green_run_completes_every_gate_then_calls_activation_callback(self) -> None:
        events: list[tuple[str, object]] = []

        def run_command(argv: tuple[str, ...]) -> int:
            events.append(("gate", argv))
            return 0

        def activate() -> None:
            events.append(("activate", None))

        completed = run_workflow(run_command, activate)

        self.assertEqual(completed, (*EXPECTED_PRE_ACTIVATION_COMMANDS, ACTIVATION_STEP))
        self.assertEqual(
            events,
            [
                *(("gate", argv) for argv in EXPECTED_PRE_ACTIVATION_ARGV),
                ("activate", None),
            ],
        )

    def test_nonzero_status_stops_and_cannot_reach_activation(self) -> None:
        calls: list[tuple[str, ...]] = []
        activation_calls = 0
        failing_argv = EXPECTED_PRE_ACTIVATION_ARGV[5]

        def fail_finalize(argv: tuple[str, ...]) -> int:
            calls.append(argv)
            return 23 if argv == failing_argv else 0

        def activate() -> None:
            nonlocal activation_calls
            activation_calls += 1

        with self.assertRaisesRegex(WorkflowCommandError, "status 23") as raised:
            run_workflow(fail_finalize, activate)

        self.assertEqual(raised.exception.argv, failing_argv)
        self.assertEqual(raised.exception.status, 23)
        self.assertEqual(tuple(calls), EXPECTED_PRE_ACTIVATION_ARGV[:6])
        self.assertEqual(activation_calls, 0)

    def test_gate_exception_propagates_and_cannot_reach_activation(self) -> None:
        calls: list[tuple[str, ...]] = []
        activation_calls = 0
        failing_argv = EXPECTED_PRE_ACTIVATION_ARGV[3]

        class RunnerFailure(RuntimeError):
            pass

        def fail_smoke(argv: tuple[str, ...]) -> int:
            calls.append(argv)
            if argv == failing_argv:
                raise RunnerFailure("smoke failed")
            return 0

        def activate() -> None:
            nonlocal activation_calls
            activation_calls += 1

        with self.assertRaisesRegex(RunnerFailure, "smoke failed"):
            run_workflow(fail_smoke, activate)

        self.assertEqual(tuple(calls), EXPECTED_PRE_ACTIVATION_ARGV[:4])
        self.assertEqual(activation_calls, 0)

    def test_only_renderer_build_is_toolchain_only(self) -> None:
        self.assertEqual(TOOLCHAIN_ONLY_ARGV, (("pnpm", "data:tr:renderer:build"),))
        self.assertEqual(TOOLCHAIN_ONLY_COMMANDS, ("pnpm data:tr:renderer:build",))
        self.assertTrue(set(TOOLCHAIN_ONLY_ARGV).isdisjoint(PRE_ACTIVATION_ARGV))

    def test_main_uses_argv_without_shell_and_internal_activation_last(self) -> None:
        events: list[tuple[str, object]] = []

        def fake_subprocess_run(argv, *, check, shell):
            self.assertFalse(check)
            self.assertFalse(shell)
            events.append(("gate", tuple(argv)))
            return SimpleNamespace(returncode=0)

        def fake_activate_after_gates():
            events.append(("activate", None))
            return 0

        with (
            mock.patch.object(workflow.subprocess, "run", side_effect=fake_subprocess_run),
            mock.patch(
                "tools.tr_release.cli.activate_after_gates",
                side_effect=fake_activate_after_gates,
            ),
        ):
            status = workflow.main()

        self.assertEqual(status, 0)
        self.assertEqual(
            events,
            [
                *(("gate", argv) for argv in EXPECTED_PRE_ACTIVATION_ARGV),
                ("activate", None),
            ],
        )


if __name__ == "__main__":
    unittest.main()
