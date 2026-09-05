# Morrowind Map

An English-only web application with two independent Morrowind maps, available at [morrowindmap.com](https://morrowindmap.com/).

| Map | Coverage | Update policy |
| --- | --- | --- |
| Original GOTY HD | Vvardenfell and Solstheim from the English editions of `Morrowind`, `Tribunal`, and `Bloodmoon` | Frozen; excluded from the update cycle |
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
renderer outputs remain local, primarily in `../morr-dev` and `local-data/`.

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

The next Tamriel Rebuilt release uses a separate reproducible workflow. After a
matching official Tamriel Data / TR Core pair is prepared locally, one command
validates and locks the exact inputs, creates a new lock, basemap, catalog, and
manifest, runs every gate, and finally switches the active local TR dataset atomically:

```bash
pnpm data:tr:release
```

The required files, internal sequence, and publication rules are documented in
[docs/TR_UPDATE.md](docs/TR_UPDATE.md). Local activation does not deploy the site:
the prepared result must go through a PR, trusted dataset review, and Actions publication.

## Contributions and publication

The application, repository documentation, code comments, commit messages, and PR
titles/descriptions use English. Create a topic branch from `main`, such as
`feature/place-search`, `fix/tile-retry`, or `docs/deployment-guide`, and submit a PR
back to `main`. The repository remains private. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the complete contribution rules and branch-protection status.

GitHub Actions publishes the verified application artifact from `main`, using the
same commit that passed CI. Dataset changes also require trusted review of the PR
head. Deployment verifies the required generated artifacts before switching
`current`, runs health checks afterward, and restores the previous release if those
checks fail. Contributors do not need server access.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — English-language policy, topic branches, and PR requirements;
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — current readiness and project boundaries;
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — runtime, datasets, and data storage;
- [docs/TR_UPDATE.md](docs/TR_UPDATE.md) — inputs and the Tamriel Rebuilt update sequence;
- [docs/DATASET_CONTRIBUTING.md](docs/DATASET_CONTRIBUTING.md) — Git LFS, the active graph, PRs, and trusted review;
- [docs/TESTING.md](docs/TESTING.md) — required checks;
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — CI artifacts and automatic/manual publication from `main`;
- [docs/DEPLOYMENT_RUNBOOK.md](docs/DEPLOYMENT_RUNBOOK.md) — nginx templates, VPS setup, diagnosis, and recovery;
- [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) — visual and interaction contracts;
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — third-party licenses.
