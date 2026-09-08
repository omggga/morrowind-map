# Contributing prepared datasets

You can contribute a new render through a PR without server access. Build it from your own matching game inputs with the [render workflow](RENDERING.md); see [TR_UPDATE.md](TR_UPDATE.md) for a new Tamriel Rebuilt version and [Rendering](RENDERING.md#project-cyrodiil-and-future-releases) for Cyrodiil releases. [Home of the Nords](RENDERING.md#home-of-the-nords-and-future-releases) and [Lyithdonea](RENDERING.md#lyithdonea-the-azurian-isles) use the same contribution process.

## Files to include

- Ready active WebP tiles under `apps/web/public/datasets/generated/` use Git LFS.
- Runtime JSON catalogs/locales, the index, manifests, metadata, audit reports, and tile inventories use regular Git.
- Game plugins, archives, meshes, textures, checkpoints, intermediate renders, and local candidate trees must never enter Git or LFS.

Only publish files referenced by the active dataset index. Old snapshots may remain on disk but should not be added to your PR.

## Prepare the result

The renderer prints an isolated candidate's `publicRoot`. Preview it, inspect representative areas and seams, then adopt it locally:

```bash
pnpm render:preview --public-root <candidate-public-directory>
pnpm render:use --public-root <candidate-public-directory>
```

`render:use` checks the complete graph and browser behavior before adopting the files. It does not stage or publish them. After adoption:

```bash
git lfs install
pnpm exec playwright install chromium
pnpm deploy:datasets:plan
pnpm test:acceptance:prepared
MORROWIND_RENDER_PUBLIC_ROOT="$PWD/apps/web/public" pnpm test:acceptance:rendered
pnpm datasets:stage
```

The plan validates each active file's size and hash, plus the index, manifests, catalogs, locales, and audit metadata. LFS pointer files are not valid WebP payloads.

`datasets:stage` stages only the validated generated files and `config/dataset-upload-plan.json`. It removes obsolete generated paths from the Git index while preserving local copies. It does not stage other contracts: explicitly add changed index, manifest, metadata, and release profile files with `git add -- <paths>`. Get the metadata paths from the manifest, including every referenced inventory, coverage, and audit file.

Review `git diff --cached --stat` and `git diff --cached --name-only` before committing. Do not force-add the whole generated directory: it may contain unrelated snapshots. Push the commit and its LFS objects, then open a PR into `main`.

## What to describe

Include the game/mod release, relevant rendering settings, the affected area, and the checks you ran. Include before/after images for visible changes. Explain intended changes to coverage, names, or locations so a reviewer can distinguish them from regressions.

CI validates the source-file boundary, the complete prepared graph, and browser behavior. A maintainer also generates a trusted HTML/JSON comparison report for the exact PR commit. It shows changed tiles, places, and names; a new commit requires a new report. Contributors do not need to configure production credentials or run a deployment.

## Local tile packages

The package tooling prepares a future Release transport while the contribution,
CI and deployment workflow above still uses Git LFS. Packaging is local: it does
not upload assets, change the active dataset, or remove LFS tracking.

With ready tiles already present, build one independent package for each active
map and write descriptors only under ignored `local-data/packages/`:

```bash
pnpm datasets:pack all --bootstrap
pnpm datasets:verify --lock local-data/packages/dataset-releases.lock.json
```

Python 3.10+ is required. No renderer runs during packaging. Each map package
contains only the inventory's generated WebP tiles, under
`local-data/packages/<datasetId>/<pyramidId>/<inventorySha256>/`. The directory
contains `tiles-0001.tar` and a small `package-index.json`. A future larger map
can have independent numbered parts; each finished USTAR archive is at most
2,137,483,648 bytes, including headers and padding. Source inputs and metadata
are never packed into the tile archive.

`datasets:verify` checks archive hashes, canonical headers and every expected
tile against the snapshot metadata. It does not extract or install anything.
Do not commit these bootstrap descriptors as an active transport lock yet.

Once an active `config/dataset-releases.lock.json` has been adopted by the future
transport workflow, `pnpm datasets:pack azurian-isles` (or another active map key
or dataset ID) updates only that map's changed tile entries. An unchanged
inventory reuses its pinned package, including for catalog-only updates.
`pnpm datasets:pack all` handles several changed maps. The lock is replaced only
after the complete resulting package selection validates; other map entries
must already match their current inventories.

## Restoring a Release-backed snapshot

The current snapshot still uses the LFS workflow above. Once a snapshot includes
the complete `config/dataset-releases.lock.json`, restore every active map with:

```bash
pnpm datasets:download
```

Python 3.10+ on macOS or Linux is sufficient; the downloader uses the standard
library. It also works from a source ZIP without Git, Docker, or game inputs.
It reads `GH_TOKEN` / `GITHUB_TOKEN` from the environment or an existing
`gh auth login` session for private releases. A fine-grained token needs only
repository Contents read access. Public releases support `--anonymous`, which
does not read credentials or require `gh`. Never put tokens in command arguments.
GitHub's [Release asset API](https://docs.github.com/en/rest/releases/assets#get-a-release-asset)
supports API delivery and redirects; credentials are sent only to the initial
canonical GitHub API request, never to redirected storage hosts.

The committed lock selects exact immutable releases and archive hashes; remote
metadata cannot replace it. Downloads use a SHA-256 cache under ignored
`local-data/cache/dataset-releases/`. Interrupted or corrupt transfers are safe
to retry. Existing complete maps are verified and reused; a map is installed
only after every expected tile in all its parts passes verification. Other
installed maps and older content-addressed versions remain available if a later
download fails. There is no automatic download from `pnpm dev` and no partial-map
developer mode. `--discard-cache` removes each verified archive after extraction
when disk space matters.

For trusted snapshot tooling, `git_datasets.py export` also exports the selected
commit's upload plan and transport lock to `<output-public-root>/config/` (or
`--output-config-root`). Use `datasets:download --public-root <exported-public>
--lock <exported-config>/dataset-releases.lock.json` to hydrate that metadata.
Release snapshots forbid tracked generated WebP and cannot fall back to LFS
when the lock is invalid. At cutover, trusted callers must use
`--require-releases` or pin `--release-boundary <first-release-backed-commit>`;
available lock history also prevents downgrade by lock deletion. Historical
LFS export remains explicit via `--mode legacy` and uses only locally available
objects fetched separately from the trusted endpoint. Snapshot tools never run
candidate code or fetch LFS themselves.
