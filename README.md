# Morrowind Map

An English-only web application with two independent Morrowind maps, available at [morrowindmap.com](https://morrowindmap.com/).

| Map | Coverage | Update policy |
| --- | --- | --- |
| Original GOTY HD | Vvardenfell and Solstheim from the English editions of `Morrowind`, `Tribunal`, and `Bloodmoon` | Stable published snapshot; local rerenders and settings changes use an isolated candidate and reviewed PR |
| Tamriel Rebuilt | Vvardenfell, Solstheim, and TR Mainland; the active release is 26.08 Poison Song | Each release becomes a new versioned dataset, activated only after the complete release gate passes |

Both maps share the same runtime: an OpenLayers tile grid, a place catalog, search and filters, URL deep links, progress, notes, personal markers, and JSON backup/import. User data stays in the browser and is bound to a `datasetId` / `snapshotId` pair.

## Local development

Requires Node.js `^20.19.0` or `>=22.12.0` and pnpm `11.19.0`.
Install Git LFS and download the active tiles to use the prepared maps. Browsing
these maps does not require game files or OpenMW.

```bash
git lfs install
git lfs pull --include='apps/web/public/datasets/generated/**/*.webp' --exclude=''
pnpm install
pnpm exec playwright install chromium
pnpm dev
```

The application is served at `http://127.0.0.1:5173`.

Run the main repository check before committing:

```bash
pnpm verify
```

With the complete catalogs and tiles for both maps available locally, also run:

```bash
pnpm test:acceptance:prepared
```

## Data

Prepared active WebP tiles in `apps/web/public/datasets/generated/**/*.webp` are
stored in Git LFS; generated JSON catalogs/locales and metadata are stored in
regular Git. Game ESM/ESP/BSA/BA2/DDS/NIF files, mod inputs, and intermediate
renderer outputs remain local under the explicitly ignored `local-data/` tree.

Dataset contributions pass publication-plan validation, prepared browser acceptance,
and manual inspection of an HTML/JSON review artifact for the exact PR commit.
`pnpm datasets:stage` stages only the validated active graph and its publication
plan; stale local snapshots stay out of the commit. See
[docs/DATASET_CONTRIBUTING.md](docs/DATASET_CONTRIBUTING.md).
App-only CI does not download tiles. Deployment from `main` checks for the immutable
graph on the VPS and fetches the LFS payload only when that graph is missing. Each
application release pins its own graph, so rollback restores the application and
data together.

Original GOTY HD is built from exactly six pinned files:

- `Morrowind.esm`, `Tribunal.esm`, and `Bloodmoon.esm`;
- `Morrowind.bsa`, `Tribunal.bsa`, and `Bloodmoon.bsa`.

Use the shared local render workflow for either map. Place your own inputs under
`local-data/inputs/bsa`, `local-data/inputs/tamriel-data`, and
`local-data/inputs/tamriel-rebuilt/00 Core/Data Files` as documented in
[docs/RENDERING.md](docs/RENDERING.md). Rendering also needs Python 3.10+, Docker with
Linux AMD64 support, and ImageMagick's `magick` command.

```bash
pnpm render:check all
pnpm render:smoke all
pnpm render:all
# Or rebuild only one map:
pnpm render:original
pnpm render:tamriel-rebuilt
```

A full rebuild can take hours; smoke only tests a small sample. The full commands
render, audit, build catalogs, and browser-test an isolated candidate. They leave
tracked active data unchanged. Preview the `publicRoot` recorded in
`local-data/render/result.json`, then explicitly adopt it with `render:use` before
preparing a dataset PR. See [docs/RENDERING.md](docs/RENDERING.md) for the complete
preview/adoption commands, Original settings, and reproducible input layout;
[docs/TR_UPDATE.md](docs/TR_UPDATE.md) covers future TR profiles and release identities.

## Contributions and publication

The application, repository documentation, code comments, commit messages, and PR
titles/descriptions use English. Create a topic branch from `main`, such as
`feature/place-search`, `fix/tile-retry`, or `docs/deployment-guide`, and submit a PR
back to `main`. The repository remains private. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the complete contribution rules and branch-protection status. Automatic CI runs
for PRs and pushes to `main`; topic-branch pushes do not create a duplicate run.
Manual workflow runs remain available.

GitHub Actions publishes the verified application artifact from `main`, using the
same commit that passed CI. Dataset changes also require trusted review of the PR
head. Deployment verifies the required generated artifacts before switching
`current`, runs health checks afterward, and restores the previous release if those
checks fail. Contributors do not need server access. Before any future public release,
complete the [repository-history and access review](docs/DEPLOYMENT.md#access);
removing infrastructure references from the current tree does not erase older revisions.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — English-language policy, topic branches, and PR requirements;
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — current readiness and project boundaries;
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — runtime, datasets, and data storage;
- [docs/RENDERING.md](docs/RENDERING.md) — shared input layout, local rendering, preview, and adoption;
- [docs/TR_UPDATE.md](docs/TR_UPDATE.md) — inputs and the Tamriel Rebuilt update sequence;
- [docs/DATASET_CONTRIBUTING.md](docs/DATASET_CONTRIBUTING.md) — Git LFS, the active graph, PRs, and trusted review;
- [docs/TESTING.md](docs/TESTING.md) — required checks;
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — CI artifacts and automatic/manual publication from `main`;
- [docs/DEPLOYMENT_RUNBOOK.md](docs/DEPLOYMENT_RUNBOOK.md) — nginx templates, VPS setup, diagnosis, and recovery;
- [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) — visual and interaction contracts;
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — third-party licenses.
