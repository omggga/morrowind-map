# Testing

Choose checks that match your change. You do not need to run every tool locally for every PR.

| Change | Local check |
| --- | --- |
| Application code | `pnpm check` |
| Documentation | Review text and links; `git diff --check` |
| UI layout or interaction | `pnpm check`, then `pnpm test:ui` |
| Catalog or renderer | Relevant `pnpm test:catalog`, `test:renderer`, `test:openmw-renderer`, `test:original-renderer`, `test:tr-release`, or `test:rendering`; smoke-render affected maps when renderer behavior changes |
| Ready datasets | `pnpm deploy:datasets:plan`, `pnpm test:acceptance:prepared`, and the all-map browser check below |

`pnpm check` runs type checking, lint, application/contract unit tests, and the production build. It needs no Python, OpenMW, game inputs, or browser-test installation. Individual application tests can be run with `pnpm test:unit <test-file>`.

CI runs the full checks automatically. To reproduce them locally:

```bash
pnpm exec playwright install chromium
pnpm verify
```

The full suite includes Python pipeline tests, browser workflows, visual/responsive/accessibility checks, and a build. Pipeline tests use synthetic fixtures; checks requiring actual game inputs skip when those inputs are absent. CI does not render the game.

## Visual changes

The browser suite protects the map, search, notes, retry behavior, keyboard and touch interaction, and accessibility. Visual baselines cover desktop and narrow portrait/landscape layouts with pinned fonts and reduced motion.

For an intentional design change, inspect the images before accepting new baselines:

```bash
pnpm test:ui:update
pnpm test:ui
```

Baselines are platform-specific; CI supplies the Linux result. Do not regenerate unrelated screenshots to silence a failure.

## Prepared map checks

Exercise real tiles, search and navigation for every active map after adopting a candidate:

```bash
MORROWIND_RENDER_PUBLIC_ROOT="$PWD/apps/web/public" pnpm test:acceptance:rendered
```

CI also runs this check when datasets change.

## Map quality

A smoke render proves that a sample renders, not that a complete map is correct. Full [render commands](RENDERING.md) also check coverage, seams, catalogs, release identity, file hashes, and the candidate in a browser. For prepared map changes, follow [DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md).

Add tests for meaningful behavior and regressions. Prefer stable inputs and observable results over copies of constants, CSS values, private method sequences, or broad snapshots unrelated to the change. A failing check needs investigation; retries alone do not establish correctness.
