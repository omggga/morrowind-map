# Testing

## Main gate

Run this command before committing:

```bash
pnpm verify
```

It runs the following checks in sequence:

- TypeScript type checking;
- ESLint with no warnings;
- Vitest unit/component suites;
- Python tests for the catalog, LAND, TR renderer/release, Original renderer, and deployment tooling;
- Playwright functional acceptance;
- Playwright visual/responsive/interaction tests;
- the production build.

Success means the entire command exits with code `0`. Fixing an individual failing test does not replace rerunning the complete gate. Use a topic branch and PR into `main` for changes; see [CONTRIBUTING.md](../CONTRIBUTING.md) for the English-language policy, branch conventions, and current protection status.

## Complete prepared datasets

Active prepared WebP pyramids are stored in Git LFS; generated JSON catalogs/locales are stored in regular Git. After preparing the data locally or downloading the actual LFS payload bytes, run the separate gate:

```bash
pnpm test:acceptance:prepared
```

It opens both current maps with their real data, loads complete catalogs and tiles, and repeats the main workflows and recovery paths. For newly rendered isolated candidates, use the rendered-candidate gate below.

Before the browser gate, validate the entire active graph:

```bash
pnpm deploy:datasets:plan
```

This checks the active index, manifests, metadata, and the size/hash of every reachable generated file. Git LFS pointers in place of WebP bytes do not pass prepared-graph validation. For a committed revision, also run the source/LFS guard:

```bash
python3 -m tools.deployment.git_datasets check --repo-root . --revision <fullSHA>
```

CI validates dataset payloads when data, the committed plan, TR config, deployment tooling, or LFS rules change: it regenerates the plan, compares it with `config/dataset-upload-plan.json`, and runs prepared acceptance. Automatic CI runs for PRs and `main` pushes; topic-branch pushes do not start another workflow. Manual runs remain available. App-only CI leaves the LFS pointers in place and does not download tiles. Rendering stays local and requires the contributor's own game inputs, but browsing prepared data and running prepared acceptance do not require OpenMW.

A dataset PR also requires visual inspection of the `dataset-review-<candidateSHA>` artifact from `dataset-review.yml`, manually dispatched on `main` with the `pr_number` input. It uses trusted scripts, does not execute candidate code, and has no deployment environment. A maintainer checks the HTML preview, complete `summary.json`, and SHA against the current PR head; a new commit requires a new review. See [DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md) for the workflow and local report command.

The deployment gate independently checks that the merged dataset PR has a successful trusted review bound to its exact head and an authentic completed Actions run. This check runs before deployment SSH is configured. Branch protection and the production environment's main-only policy are separate enforced controls; their settings and the conditional review requirement are recorded in [CONTRIBUTING.md](../CONTRIBUTING.md) and [DEPLOYMENT.md](DEPLOYMENT.md).

## Local rendering and candidate checks

Use the shared [render workflow](RENDERING.md) to validate real inputs and exercise
the local renderer:

```bash
pnpm render:check all
pnpm render:smoke all
```

A successful smoke run covers only sample tiles. It is not proof that a complete new
map passes full rendering, quality/coverage audits, or browser checks. Full commands
`render:original`, `render:tamriel-rebuilt`, and `render:all` produce isolated candidates,
validate their complete publication plans, and run `test:acceptance:rendered` against
the result. They do not replace the tracked active dataset.

The rendered browser gate reads actual dataset identities and records from its
candidate, so it also covers a new Original snapshot or a newly versioned TR release.
To rerun it directly, use the candidate's recorded `publicRoot`:

```bash
MORROWIND_RENDER_PUBLIC_ROOT=/absolute/path/to/candidate/apps/web/public pnpm test:acceptance:rendered
```

`render:preview` validates the graph before serving the candidate. `render:use` repeats
full graph and rendered-browser validation before adopting prepared files locally.
After adoption, run `pnpm verify` and the normal dataset contribution checks. Generated
locks, source inputs, and renderer intermediates remain ignored; synthetic adapter tests
run in ordinary CI without any game files.

## Legacy release-specific gate

The lower-level release workflow remains compatible with its existing default paths.
The following commands apply to a profile/lock prepared through that workflow, not
automatically to the isolated facade candidate.

Before activating a new TR dataset, run:

```bash
pnpm data:tr:release:verify
```

It verifies that the config, lock, plan, renderer audit, catalog audit, publication metadata, and candidate manifest share one release identity. This gate supplements rather than replaces `pnpm verify` and prepared acceptance.

Before internal activation of a new TR release, the prepared gate reads the inactive candidate index/manifest:

```bash
pnpm test:acceptance:prepared:candidate
```

The command uses `local-data/tr-release/candidate`, while still reading Original and content-addressed payloads from the normal `apps/web/public` root.

`pnpm data:tr:release` runs both release-specific browser/full gates before its internal
production activation. The separate `activate-local` CLI stage requires isolated work/public
roots and cannot activate the tracked public tree. Passing local release gates does not deploy production: the prepared dataset must still pass the PR/Actions publication workflow.

## Browser matrix

Functional acceptance runs in pinned Chromium, blocks non-loopback traffic, and checks:

- both dataset choices and direct URL loading;
- a painted WebP canvas, pan, zoom, and sparse coverage;
- search, filters, labels, and place selection;
- progress, notes, personal markers, and persistence after reload;
- Back/Forward and URL canonicalization;
- missing, invalid, loading, partial-failure, retry, and recovery states;
- JSON export/import and local-storage failures.

The visual suite fixes DPR, fonts, reduced motion, and separate platform baselines. Required viewports are `1280×720`, `390×844`, `320×568`, `844×390`, and `667×375`; the desktop suite also checks 200% reflow.

Keyboard tests cover focus order, visible focus rings, Escape/close behavior, focus restoration, map controls, and the absence of unreachable actions. The automated accessibility gate uses axe for WCAG 2.2 AA, checks ARIA names/states, landmark structure, and alerts/status, and rejects serious/critical violations.

Touch tests use trusted pointer/touch events for zoom, pan, marker selection, and the editor flow without relying on hover.

## Snapshot policy

A normal test run never updates baselines. For an intentional UI change, regenerate snapshots separately:

```bash
pnpm test:ui:update
```

Accept new images only after inspecting layout, text, focus, loading/error states, and both maps. Then rerun `pnpm verify`.

## Data pipeline tests

Pipeline tests use synthetic inputs and do not require proprietary game files. They must verify:

- strict release-config parsing and rejection of unknown/unsafe paths;
- file/tree hashes, case-fold collisions, and source identity;
- the exact workflow order and stopping at the first failure;
- generation of a new release without version-specific Python changes;
- manifest and content-addressed artifact schema/identity validation;
- atomic activation and preservation of the active index on failure.

Deployment tests also cover the Git source/LFS boundary, trusted-review provenance, dataset staging and validation, and application activation/health rollback with the correct pinned graph.

A full render does not run in ordinary CI: it requires local game inputs, Docker/OpenMW, and substantial time.
