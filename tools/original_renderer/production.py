from __future__ import annotations

from collections.abc import Sequence

from tools.original_renderer.bootstrap import activate


def main(argv: Sequence[str] | None = None) -> int:
    production, _, _, _ = activate()
    return int(production.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
