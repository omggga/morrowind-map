# Updating Tamriel Rebuilt

This guide describes the TR input contract and preparing a new map version. Start with
[RENDERING.md](RENDERING.md) for the shared input layout, commands, and isolated preview
workflow. A TR-only render preserves Original, Cyrodiil and Home of the Nords; `render:all`
composes all four newly rendered maps.
Work on a topic branch and submit the prepared result through a pull request into `main`.
Use English for release text, documentation, commit messages, and PR titles/descriptions;
see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Required inputs

Use `local-data/inputs/bsa`, `local-data/inputs/tamriel-data`, and
`local-data/inputs/tamriel-rebuilt/00 Core/Data Files`. Extract complete directories
as shown in [RENDERING.md](RENDERING.md#input-directory); no external machine-specific
source path is required. These inputs and all work products stay in ignored `local-data/`.

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

`config/tr-release.json` records the active build. For a new release, copy it to
`local-data/profiles/next-tr.json` and edit that separate profile before rendering.
The adapter writes a normalized derived profile under its work root; only explicit
`render:use` adopts the candidate profile into the active configuration.

Before a new release:

1. Choose a unique versioned `datasetId`, English title/summary, and release name/version/build.
2. Use the standard extracted input layout. The shared adapter normalizes profile
   directory paths while retaining their IDs and load order.
3. Remove `adoptedSnapshotId`; it is permitted only for the exact published 26.08 seed.
4. Preserve the immutable hashes of the six base inputs.
5. Remove old `sha256` values for the four Tamriel Data/TR inputs. `check` reports
   actual hashes and `lock` pins them.
6. Reassess the previous MAST exception for the new release. Remove an obsolete one;
   add a replacement only if parsing the new matching release reveals a specific
   advertised/actual byte-size discrepancy. A rerender of the current release retains
   its documented exception unchanged.
7. Check regions and shard-aligned smoke controls for the new LAND topology.

Do not reuse the old `datasetId` while changing only `snapshotId`: existing user records
for that dataset intentionally trigger a snapshot conflict. Each release gets both new identities.

A new `snapshotId` is always derived from the profile/source fingerprint. Future releases
cannot specify an arbitrary adopted snapshot.

`local-data/render/tamriel-rebuilt/release.lock.json` is generated from the derived
profile and actual inputs by the shared adapter.
It contains normalized paths, hashes, tree fingerprints, the derived snapshot, LAND
extent/plan/topology, catalog counts, and renderer/catalog producer fingerprints. Do not
edit the lock manually. All subsequent commands read the same lock and fail closed
if inputs differ.

## Supported sequence

With matching files and the separate future-release profile prepared:

```bash
pnpm render:check tamriel-rebuilt --profile local-data/profiles/next-tr.json
pnpm render:smoke tamriel-rebuilt --profile local-data/profiles/next-tr.json
pnpm render:tamriel-rebuilt --profile local-data/profiles/next-tr.json
```

For a rerender of the current release, omit `--profile`: the adapter keeps current
hashes and exceptions but generates `<active-datasetId>-local` and a fresh snapshot,
without `adoptedSnapshotId`. `--dataset-id <new-id>` can select another unused ID.
An explicitly supplied future profile keeps its new identity. Do not change the
identity between check, smoke, and full-render commands.

The facade checks inputs before expensive work, builds or reuses the required renderer
images, and invokes the existing TR stages in separate Python processes. The full
render then runs these stages in strict order:

| Stage | Responsibility |
| --- | --- |
| `check`, `lock` | Validate exact inputs and hash every file in complete mounted trees |
| `plan` | Derive LAND extent, render cells, shards, and identity from the lock |
| `renderer-smoke` | Check all representative controls before the full render |
| `renderer-render`, `renderer-finalize` | Produce native tiles with checkpoint/resume and build lower zoom levels |
| `renderer-stabilize`, `renderer-audit` | Correct render-shard boundaries and audit the full release and independent probes |
| `dataset-validate`, `dataset-prepare` | Validate and prepare the content-addressed basemap in the isolated public root |
| `catalog-build`, `catalog-validate`, `catalog-prepare` | Merge the five ESMs, validate the catalog, and prepare it in the same isolated root |
| `manifest-build`, `release-verify` | Assemble a candidate from actual metadata and verify one identity throughout |
| `activate-local` | Recheck candidate artifacts and switch only the isolated candidate manifest/index |
| Full-plan and rendered browser gates | Validate the complete candidate, preserving every other active map and exercise its actual catalogs/tiles |

No stage changes tracked active public files. After success, read `publicRoot` from
`local-data/render/result.json`, preview it, and explicitly adopt it with `render:use`
as described in [RENDERING.md](RENDERING.md#preview-adopt-locally-and-contribute).
Local adoption reruns full graph and browser checks, then updates the active local
contracts/profile. It still does not stage files or publish the website.

If a stage fails, the workflow stops without adoption. Fix the input, configuration,
or producer and rerun the same full-render command. Compatible immutable outputs and
renderer checkpoints can be reused only while lock, producer, and baseline identities
remain unchanged. Use a separate `--work-root local-data/render/next-attempt` when
changing those inputs; never edit an old lock or output to force compatibility.

## What enters Git

After explicit `render:use`, validate and commit the current contracts and prepared active payload:

- `config/tr-release.json`
- `apps/web/public/datasets/index.json`
- The new `apps/web/public/datasets/manifests/<datasetId>.json`
- Compact integrity/audit metadata under `apps/web/public/datasets/metadata/<datasetId>/`
- Generated JSON catalogs and locales in regular Git
- Active `apps/web/public/datasets/generated/**/*.webp` files in Git LFS

Generated locks under `local-data/render/` (or the legacy `local-data/tr-release/`),
candidate trees, renderer checkpoints,
intermediate renders, and original game files remain local artifacts. ESM/ESP/BSA/BA2/DDS/NIF
and other game inputs must never enter Git or LFS. A TR-only contribution leaves
Original unchanged; a deliberate `render:all` contribution includes both new candidates.

Follow [DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md) to validate and stage the prepared graph and open a PR. Include the release metadata and any deliberate settings or coverage changes. The dataset index, manifests, catalogs, and tiles must agree on their respective dataset and snapshot identities. User data remains bound to its original map version.
