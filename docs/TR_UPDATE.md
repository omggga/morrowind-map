# Updating Tamriel Rebuilt

This runbook covers a new Tamriel Rebuilt release. It does not update Original GOTY HD.
Work on a topic branch and submit the prepared result through a pull request into `main`.
Use English for release text, documentation, commit messages, and PR titles/descriptions;
see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Required inputs

### Pinned base

Use the same six base files as the current profile:

- `Morrowind.esm`
- `Tribunal.esm`
- `Bloodmoon.esm`
- `Morrowind.bsa`
- `Tribunal.bsa`
- `Bloodmoon.bsa`

Their hashes must match the release configuration. Replacing a base file is a separate
renderer-profile change, not a routine TR update.

### Tamriel Data

Provide the complete set from one release:

- `Tamriel_Data.esm`
- `Tamriel_Data.omwscripts`
- The complete extracted Tamriel Data `Data Files` tree, including all meshes,
  textures, and other assets.

### Tamriel Rebuilt Core

Provide the complete matching set from one release:

- `TR_Mainland.esm`
- `tamrielrebuilt.omwscripts`
- The complete extracted TR Core `Data Files` tree, including all assets.

Do not mix ESM files, scripts, or asset trees from different releases, or copy only
files needed by an individual smoke test. Optional plugins are outside the canonical profile.

Release compatibility is an operator check: tooling does not infer a release number
from ESM or asset contents. Use the officially documented matching Tamriel Data/TR Core
pair. The pipeline then hashes every file in the complete mounted trees, rejects
unexpected ESM/ESP/OMW/BSA/scripts in those trees, and binds all outputs to one lock.
Inputs cannot be mixed after `lock`.

## Load order

OpenMW data directories apply in this order: base assets → Tamriel Data → TR Core.
Later trees therefore have the expected override priority. Register BSAs in this order:
`Morrowind.bsa` → `Tribunal.bsa` → `Bloodmoon.bsa`.

Content load order is fixed:

1. `Morrowind.esm`
2. `Tribunal.esm`
3. `Bloodmoon.esm`
4. `Tamriel_Data.esm`
5. `TR_Mainland.esm`

Both `.omwscripts` files are included in inventory and provenance, but not added as `content=`.

## Release configuration and lock

`config/tr-release.json` is the single human-authored profile for the active build.
Before a new release:

1. Choose a unique versioned `datasetId`, English title/summary, and release name/version/build.
2. Update Tamriel Data and TR Core paths relative to `--source-root`.
3. Remove `adoptedSnapshotId`; it is permitted only for the exact published 26.08 seed.
4. Preserve the immutable hashes of the six base inputs.
5. Remove old `sha256` values for the four Tamriel Data/TR inputs. `check` reports
   actual hashes and `lock` pins them.
6. Remove the previous MAST exception. Add a new one only if parsing the new matching
   release reveals a specific advertised/actual byte-size discrepancy.
7. Check regions and shard-aligned smoke controls for the new LAND topology.

Do not reuse the old `datasetId` while changing only `snapshotId`: existing user records
for that dataset intentionally trigger a snapshot conflict. Each release gets both new identities.

A new `snapshotId` is always derived from the profile/source fingerprint. Future releases
cannot specify an arbitrary adopted snapshot.

`local-data/tr-release/release.lock.json` is generated from configuration and actual inputs.
It contains normalized paths, hashes, tree fingerprints, the derived snapshot, LAND
extent/plan/topology, catalog counts, and renderer/catalog producer fingerprints. Do not
edit the lock manually. All subsequent commands read the same lock and fail closed
if inputs differ.

## Required sequence

Extract matching Tamriel Data and TR Core releases and update `config/tr-release.json`.
Then run the supported orchestrator:

```bash
pnpm data:tr:release
```

It runs these public stages in strict order:

```bash
pnpm data:tr:check
pnpm data:tr:lock
pnpm data:tr:plan
pnpm data:tr:renderer:smoke
pnpm data:tr:renderer:render
pnpm data:tr:renderer:finalize
pnpm data:tr:renderer:stabilize
pnpm data:tr:renderer:audit
pnpm data:tr:dataset:validate
pnpm data:tr:dataset:prepare
pnpm data:tr:catalog:build
pnpm data:tr:catalog:validate
pnpm data:tr:catalog:prepare
pnpm data:tr:manifest:build
pnpm data:tr:release:verify
pnpm test:acceptance:prepared:candidate
pnpm verify
```

After the last successful gate, the orchestrator invokes internal atomic activation.
There is no separate public activation command.

The stages perform the following work:

1. `check` validates configuration, layout, identities, exact files, and the absence
   of unexpected inputs.
2. `lock` hashes files and complete trees to create one immutable input contract.
3. `plan` derives LAND extent, render cells, shards, and output identity from the lock.
4. `smoke` checks the renderer and representative cells before a full render.
5. `render` produces native tiles with checkpoint/resume; `finalize` builds lower zoom levels.
6. `stabilize` corrects only render-shard boundaries; `audit` checks the entire release
   and independent probes.
7. `dataset:*` validates and publishes a content-addressed basemap package.
8. `catalog:*` merges five ESMs, validates the audit, and publishes a content-addressed
   catalog package.
9. `manifest:build` creates an inactive candidate manifest from the metadata actually published.
10. `release:verify`, candidate prepared browser acceptance, and the repository gate
    validate the candidate end to end.
11. Internal activation rechecks every published WebP against `tiles.ndjson`, verifies
    candidate bytes, and atomically switches the manifest/index as the final filesystem operations.

If a stage fails, the orchestrator stops before activation. Correct the input,
configuration, or producer and rerun `pnpm data:tr:release`. Completed immutable outputs
are reused; rendering resumes from a checkpoint only when lock and producer identities
are unchanged.

## Toolchain-only commands

A routine content update does not rebuild the renderer image. Build it separately
only after changes to the OpenMW version, container recipe, rendering parameters, or encoder:

```bash
pnpm data:tr:renderer:build
```

A toolchain change requires another smoke test and the complete release gate, even
when game inputs are unchanged.

## What enters Git

After local activation, validate and commit the current contracts and prepared active payload:

- `config/tr-release.json`
- `apps/web/public/datasets/index.json`
- The new `apps/web/public/datasets/manifests/<datasetId>.json`
- Compact integrity/audit metadata under `apps/web/public/datasets/metadata/<datasetId>/`
- Generated JSON catalogs and locales in regular Git
- Active `apps/web/public/datasets/generated/**/*.webp` files in Git LFS

`local-data/tr-release/release.lock.json`, candidate trees, renderer checkpoints,
intermediate renders, and original game files remain local artifacts. ESM/ESP/BSA/BA2/DDS/NIF
and other game inputs must never enter Git or LFS. The Original manifest, metadata,
and generated package remain unchanged.

Before committing, run:

```bash
git lfs install
pnpm deploy:datasets:plan
pnpm test:acceptance:prepared
pnpm datasets:stage
pnpm verify
```

`datasets:stage` validates and stages only generated files in the complete active plan
for both maps, using a restricted `git add -f`. It writes/stages
`config/dataset-upload-plan.json` and removes obsolete generated paths only from the
Git index. Stage changed TR configuration/index/manifests/metadata separately with
`git add -- <exact-paths>`. Do not stage the entire local generated tree: old snapshots
may remain there. After committing, validate the full commit SHA:

```bash
python3 -m tools.deployment.git_datasets check --repo-root . --revision <fullSHA>
```

Open a pull request from your topic branch into `main`. The maintainer runs trusted
`dataset-review.yml` from `main` with `pr_number`, then reviews
`dataset-review-<candidateSHA>` and the complete JSON change list. Every new candidate
SHA requires a new review. Branch protection now requires PRs and successful CI
for `main`, including for administrators; the repository remains private on GitHub Pro.
The maintainer also inspects the conditional dataset report before merge. See
[DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md) for the full process and
[CONTRIBUTING.md](../CONTRIBUTING.md) for branch policy.

## Activation result

After successful internal activation:

- The dataset index still contains exactly Original GOTY HD and one active TR dataset.
- The new manifest references only validated content-addressed basemap and catalog packages.
- `datasetId` and `snapshotId` match the lock and all artifacts.
- The previous package is unchanged.
- User data for the new dataset starts in a separate namespace.

This activates prepared files locally. Production deployment from `main` first probes
the committed plan on the server; only a missing graph requires LFS download and
`--stage-only` upload. The installer pins the new application release to a specific
graph. Nginx reads `current/datasets/generated`; rollback restores the application
and its graph together. Previous releases/graphs remain until a separate future
garbage-collection procedure. No automatic backup is configured. See [DEPLOYMENT.md](DEPLOYMENT.md).
