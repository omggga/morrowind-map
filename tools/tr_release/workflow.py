from __future__ import annotations

import subprocess
from collections.abc import Callable


PRE_ACTIVATION_ARGV = (
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

PRE_ACTIVATION_COMMANDS = tuple(" ".join(argv) for argv in PRE_ACTIVATION_ARGV)
ACTIVATION_STEP = "activate_after_gates"
WORKFLOW_STEPS = (*PRE_ACTIVATION_COMMANDS, ACTIVATION_STEP)

TOOLCHAIN_ONLY_ARGV = (("pnpm", "data:tr:renderer:build"),)
TOOLCHAIN_ONLY_COMMANDS = tuple(" ".join(argv) for argv in TOOLCHAIN_ONLY_ARGV)

CommandArgv = tuple[str, ...]
CommandRunner = Callable[[CommandArgv], int | None]
ActivationCallback = Callable[[], int | None]


class WorkflowCommandError(RuntimeError):
    """A mandatory pre-activation command returned a nonzero status."""

    def __init__(self, argv: CommandArgv, status: int) -> None:
        self.argv = argv
        self.command = " ".join(argv)
        self.status = status
        super().__init__(f"{self.command!r} failed with status {status}")


class WorkflowActivationError(RuntimeError):
    """The internal activation callback returned a nonzero status."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"TR activation failed with status {status}")


def run_workflow(
    run_command: CommandRunner,
    activate: ActivationCallback,
) -> tuple[str, ...]:
    """Run every release gate, then and only then invoke internal activation.

    Gate commands are passed to the injected runner as argv tuples. Renderer image
    construction is deliberately absent because it is toolchain maintenance, not
    part of a routine Tamriel Rebuilt content release.
    """

    completed: list[str] = []
    for argv in PRE_ACTIVATION_ARGV:
        status = run_command(argv)
        if status is not None and status != 0:
            raise WorkflowCommandError(argv, status)
        completed.append(" ".join(argv))

    activation_status = activate()
    if activation_status is not None and activation_status != 0:
        raise WorkflowActivationError(activation_status)
    completed.append(ACTIVATION_STEP)
    return tuple(completed)


def _run_argv(argv: CommandArgv) -> int:
    return int(subprocess.run(argv, check=False, shell=False).returncode)


def _activate_after_gates() -> int:
    from tools.tr_release.cli import activate_after_gates

    return int(activate_after_gates())


def main(
    *,
    run_command: CommandRunner | None = None,
    activate: ActivationCallback | None = None,
) -> int:
    """Production entry point for the complete, fail-closed TR release workflow."""

    run_workflow(
        _run_argv if run_command is None else run_command,
        _activate_after_gates if activate is None else activate,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
