# Rendering maps locally

Use this workflow to rebuild Original GOTY HD, prepare a new Tamriel Rebuilt or Project Cyrodiil release,
or review different rendering settings. It reuses the existing renderer, catalog,
quality-audit, and dataset tools. Rendering produces an isolated candidate first;
it does not modify the website or the tracked active dataset.

## Prerequisites

Follow [README.md](../README.md) to install dependencies and download the complete active Git LFS payload. Candidates preserve all active maps, so a single-map rerender also needs the other map's prepared baseline. Install Chromium for candidate browser checks:

```bash
pnpm exec playwright install chromium
```

Rendering additionally requires Python 3.10 or newer, a running Docker engine that can
run Linux AMD64 containers, and ImageMagick with the `magick` executable on `PATH`.
Keep `python3`, `docker`, `magick`, and `pnpm` available in the same shell. The workflow
builds or reuses the pinned OpenMW base image and the map-specific renderer image;
you do not need to install OpenMW on the host.

The first image build needs network access and can take substantial time. A smoke test
renders a small sample. A complete rebuild renders and audits the whole map and can take
hours, with additional disk space for container images, checkpoints, raw/intermediate
renders, and candidate datasets. Source inputs and active prepared tiles alone are not
a sufficient estimate of the required free space.

## Input directory

Obtain the English GOTY base files from your own game installation and matching Tamriel
Data / Tamriel Rebuilt / Project Cyrodiil releases from their authors. Extract the contents into this layout:

```text
local-data/
  inputs/
    bsa/
      Morrowind.esm
      Tribunal.esm
      Bloodmoon.esm
      Morrowind.bsa
      Tribunal.bsa
      Bloodmoon.bsa
    tamriel-data/
      Tamriel_Data.esm
      Tamriel_Data.omwscripts
      meshes/
      textures/
      ...all other files from the release's 00 Data Files directory...
    tamriel-rebuilt/
      00 Core/
        Data Files/
          TR_Mainland.esm
          tamrielrebuilt.omwscripts
          ...all other files from the release's Core Data Files directory...
    project-cyrodiil/
      00 Core/
        Cyr_Main.esm
        Cyr_Main-metadata.toml
        Docs/
  render/
    ...generated profiles, locks, logs, checkpoints, and candidates...
```

Copy the **contents** of Tamriel Data's `00 Data Files` into `tamriel-data`, without an
extra nested `00 Data Files` directory. Preserve the full TR `00 Core/Data Files` tree.
Do not mix different mod releases or add optional plugins to the canonical load order.
Original needs only the six files in `bsa`; TR additionally needs Tamriel Data and
TR Core. Cyrodiil needs GOTY, Tamriel Data and its own Core; it does not load TR.
Preserve the complete Core package when extracting future releases.
For `.7z` packages on macOS, `bsdtar` can extract directly into the input directory:

```bash
mkdir -p local-data/inputs/project-cyrodiil
bsdtar -xf /path/to/Cyr_Main.7z -C local-data/inputs/project-cyrodiil
```

Treat a nonzero extraction exit code as a failure; do not render partially extracted
files. `render:check` validates the plugin structure as well as the input hashes.

The base files are pinned by SHA-256. A new mod release needs an updated TR profile as
explained in [TR_UPDATE.md](TR_UPDATE.md). The checks hash every file in each declared
source tree, validate master dependencies and known exceptions, and reject unexpected
plugins or archives. Supplying only ESM files or assets visible in one sample is insufficient.

`local-data/` is explicitly ignored. Game inputs, asset archives, meshes, textures,
renderer checkpoints, and intermediate outputs never belong in Git or Git LFS.
Only validated ready WebP renders and runtime JSON/metadata may be contributed.

## Commands

Run commands from the repository root. The target is `original`, `tamriel-rebuilt`,
`project-cyrodiil`, or `all`; check/build/smoke default to `all`.

| Command | Result |
| --- | --- |
| `pnpm render:check all` | Validate all three input sets and report identities without building or rendering |
| `pnpm render:build all` | Check inputs and build/reuse the renderer images |
| `pnpm render:smoke original` | Render and validate the Original sample |
| `pnpm render:smoke tamriel-rebuilt` | Render every configured TR smoke control |
| `pnpm render:smoke tamriel-rebuilt --control old-ebonheart` | Render only the named TR smoke control |
| `pnpm render:original` | Fully rebuild Original into an isolated candidate preserving the other active maps |
| `pnpm render:tamriel-rebuilt` | Fully rebuild TR into an isolated candidate preserving the other active maps |
| `pnpm render:check project-cyrodiil` | Check PC files, binary structure and master dependencies |
| `pnpm render:smoke project-cyrodiil --control anvil` | Render the Anvil 3×3-cell control |
| `pnpm render:smoke project-cyrodiil` | Render every configured Cyrodiil control |
| `pnpm render:project-cyrodiil` | Render, audit and prepare Cyrodiil; preserve Original and TR |
| `pnpm render:all` | Rebuild Original, TR and Cyrodiil in order, composing one candidate |

`build`, `smoke`, and full render commands ensure the required images are available.
Verified renderer images are reused when their source and base-image identities match.
Release smoke samples live under `smoke/<datasetId>/<producer-fingerprint>/<control>`;
changing the image, encoder, profile or renderer starts a separate set of samples and
preserves earlier ones. Compatible reruns reuse the same sample directory. Full-render
checkpoints still require an exact producer match; use a fresh work root after changing
render inputs or tools once a full render has started.

A successful smoke result proves the sample rendered; it does not replace the complete
render, seam/coverage audits, catalog checks, or browser acceptance.

Full render commands stop at the first failed stage. They verify the complete candidate
publication graph and run `pnpm test:acceptance:rendered` against the candidate itself.
The final `publicRoot` is printed and saved in `local-data/render/result.json`;
map-specific receipts and detailed logs stay below `local-data/render/`.
The active tree in `apps/web/public` stays unchanged until explicit local adoption.

Use `--workers 2 --render-workers 2` to control the existing render/audit worker pools.
`--source-root /absolute/path/to/inputs` supports the same layout elsewhere.
`--work-root local-data/render/experiment-name` keeps separate experiment outputs;
choose a fresh work root when changing the baseline, source profile, or settings.
Compatible renderer checkpoints can be reused after a failed stage; do not edit locks
or immutable output files to force reuse.

## Original settings and identity

The published Original dataset remains stable until a reviewed contribution replaces
its active snapshot. Local rerenders retain `datasetId: original-goty-hd` and derive a
new snapshot from the renderer profile and producer source. Settings changes therefore
cannot silently masquerade as the published snapshot. Existing browser records remain
bound to their original snapshot and can report a conflict after adoption.

The six English GOTY input hashes, coverage, and 512-pixel tile geometry remain fixed.
Optional INI settings merge into the existing renderer settings. For example, create
`config/original-render-settings.cfg` with the specific visual change you want to test:

```ini
[Video]
antialiasing = 4
```

Then use the same file for the smoke and complete rebuild:

```bash
pnpm render:smoke original --settings config/original-render-settings.cfg
pnpm render:original --settings config/original-render-settings.cfg
```

The file is an example you create, not a required bundled configuration. Settings
that change local-map resolution, widget size, or viewing distance are rejected.
Review the actual rendered result and include relevant settings in a PR so another
contributor can reproduce the change. Do not put game assets or connection details
in configuration files.

## Project Cyrodiil and future releases

`config/pc-release.json` describes Abecean Shores 25.05a with the shared Tamriel Data
input tree. The canonical load order is Morrowind, Tribunal, Bloodmoon,
Tamriel_Data, then Cyr_Main. Only Cyr_Main LAND cells become basemap tiles; catalog
entries outside Cyrodiil are excluded. Rendering uses the exact TR settings,
512×512 native tiles, z0–z7 pyramid, 3×3-cell batches and the same baked grade,
stabilization and quality audits.

For the first render, run these separately and stop on any failure:

```bash
pnpm render:check project-cyrodiil
pnpm render:smoke project-cyrodiil
pnpm render:project-cyrodiil --workers 2 --render-workers 2
```

If a run stops after rendering, keep its work directory and rerun the same
command with the same inputs and profile. Compatible native checkpoints are
verified and reused; a completed stabilization output is also validated and
reused. Do not delete `production/` or edit provenance receipts to bypass a
mismatch. Changing renderer code, inputs or settings can require a new render.

The complete command prepares tiles, catalog, English names, metadata and a
three-map candidate. It runs browser acceptance against that candidate, without
building the application or updating `apps/web/public`. Inspect it with:

```bash
pnpm render:preview --public-root local-data/render/project-cyrodiil/candidate/apps/web/public
```

The repository includes Cyrodiil as the third landing choice. It opens one zoom
level closer than the other maps and has no redundant map-section filter.
For future releases, review the candidate before `render:use` adopts it locally;
see the adoption section below.
Uploading generated files to Git LFS and opening a PR are separate contributor steps.

For a new mod release, copy `config/pc-release.json` into an ignored profile such as
`local-data/profiles/next-pc.json`. Update `datasetId`, release metadata, mod hashes
and smoke controls, then replace the complete Core tree and use matching Tamriel Data.
Optional mod SHA-256 pins may be omitted while preparing a release; the generated
lock still records exact hashes and fingerprints of every input and asset tree.
Pin the reviewed hashes before contributing the profile. Base-game hashes remain immutable.
Master-size exceptions must describe the exact dependency pair and byte counts;
an exception never makes a corrupt plugin or missing asset acceptable.

```bash
pnpm render:check project-cyrodiil --profile local-data/profiles/next-pc.json
pnpm render:smoke project-cyrodiil --profile local-data/profiles/next-pc.json
pnpm render:project-cyrodiil --profile local-data/profiles/next-pc.json --work-root local-data/render/next-pc
```

Use the same profile and dataset ID throughout. An update replaces the existing
Cyrodiil index entry while retaining both other maps and their exact manifests.
`--profile` and `--dataset-id` apply only to a single release target, not `all`.

## TR identity and future releases

With the current profile, a local rebuild uses `<active-datasetId>-local` and a newly
derived snapshot. Its generated profile removes the published `adoptedSnapshotId`,
normalizes source paths, and retains all pinned hashes and master-size exceptions.
It does not edit `config/tr-release.json` during rendering.

For the next release, create a separate profile with the new release metadata and
input contract, then run:

```bash
pnpm render:check tamriel-rebuilt --profile local-data/profiles/next-tr.json
pnpm render:tamriel-rebuilt --profile local-data/profiles/next-tr.json
```

A future profile's new dataset ID is preserved. `--dataset-id <new-id>` can explicitly
choose a different unused identity. Keep the same profile and ID across related
check/smoke/render commands. See [TR_UPDATE.md](TR_UPDATE.md) for the exact release
fields, load order, hash policy, and complete internal stage sequence.

## Preview, adopt locally, and contribute

After a successful full render, read the public directory from the result receipt:

```bash
CANDIDATE_PUBLIC=$(python3 -c 'import json; print(json.load(open("local-data/render/result.json"))["publicRoot"])')
pnpm render:preview --public-root "$CANDIDATE_PUBLIC"
```

Preview validates the graph and starts the app with that candidate's public files.
Inspect all prepared maps, tiles, names, and coverage; stop the preview server before continuing.
For custom work roots, read their `result.json` instead. Pass the `publicRoot` directory,
not the JSON receipt filename, to both preview and adoption commands.

When satisfied, explicitly adopt the candidate into your local checkout:

```bash
pnpm render:use --public-root "$CANDIDATE_PUBLIC"
pnpm test:acceptance:prepared
pnpm datasets:stage
```

`render:use` requires a candidate inside this repository's ignored `local-data/`.
It validates the full plan and candidate browser acceptance before copying prepared
artifacts, updating local manifests/index and the publication plan, and adopting the
TR profile associated with a TR candidate. It does not stage, commit, push, or deploy.
Add changed manifests, referenced metadata, reproducibility settings, and TR configuration
explicitly; inspect the staged diff and follow [DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md).
The helper stages only the validated active generated graph and its publication plan.

Open a topic-branch PR into protected `main`. A maintainer reviews the exact prepared
files and trusted HTML/JSON dataset report. Contributors need no server access.
