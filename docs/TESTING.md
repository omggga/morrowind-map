# Testing

Choose checks that match your change. You do not need to run every tool locally for every PR.

| Change | Local check |
| --- | --- |
| Application code | `pnpm check` |
| Documentation | Review text and links; `git diff --check` |
| UI layout or interaction | `pnpm check`, then `pnpm test:ui` |
| Catalog or renderer | Relevant `pnpm test:catalog`, `test:renderer`, `test:openmw-renderer`, `test:original-renderer`, `test:tr-release`, or `test:rendering`; smoke-render affected maps when renderer behavior changes |
| Ready datasets | `pnpm deploy:datasets:plan`, `pnpm test:acceptance:prepared`, and the all-map browser check below |

`pnpm check` runs type checking, lint, application/contract unit tests, and the production build. After the README setup and `pnpm datasets:download` have restored the maps, this command needs no OpenMW, game inputs, or browser-test installation. The initial downloader requires Python 3.10+; it does not require Git LFS. Individual application tests can be run with `pnpm test:unit <test-file>`.

CI runs the full checks automatically. To reproduce them locally:

```bash
pnpm datasets:download
pnpm exec playwright install chromium
pnpm verify
```

The full suite includes Python pipeline tests, browser workflows, responsive/accessibility checks, and a build. Screenshot comparisons are opt-in and do not run in the default CI checks. Pipeline tests use synthetic fixtures; checks requiring actual game inputs skip when those inputs are absent. CI does not render the game.

## Visual changes

The default `pnpm test:ui` browser suite protects the map, search, notes, retry behavior, keyboard and touch interaction, accessibility, and viewport overflow. Keyboard checks verify that controls can be reached and used without fixing their exact Tab order, so adding a button does not break the workflow test.

Optional screenshot comparisons cover desktop and narrow portrait/landscape layouts with pinned fonts and reduced motion. Run them explicitly with `pnpm test:ui:visual`; normal UI development does not require updating baselines.

When updating visual baselines intentionally, inspect the resulting images before accepting them:

```bash
pnpm test:ui:update
pnpm test:ui:visual
```

Baselines are platform-specific; run the optional visual commands on Linux to compare or update Linux baselines. Do not regenerate unrelated screenshots to silence a failure.

## Prepared map checks

Exercise real tiles, search and navigation for every active map after adopting a candidate:

```bash
MORROWIND_RENDER_PUBLIC_ROOT="$PWD/apps/web/public" pnpm test:acceptance:rendered
```

CI restores the complete map selection from the committed transport lock before running prepared and rendered checks when datasets change. It compares the reconstructed upload plan with `config/dataset-upload-plan.json`; a missing or invalid lock cannot trigger an LFS fallback. Application-only CI remains lightweight and does not download tiles.

## Map quality

A smoke render proves that a sample renders, not that a complete map is correct. Full [render commands](RENDERING.md) also check coverage, seams, catalogs, release identity, file hashes, and the candidate in a browser. For prepared map changes, follow [DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md).

Add tests for meaningful behavior and regressions. Prefer stable inputs and observable results over copies of constants, CSS values, private method sequences, or broad snapshots unrelated to the change. A failing check needs investigation; retries alone do not establish correctness.
