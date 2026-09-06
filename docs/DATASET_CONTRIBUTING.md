# Contributing prepared datasets

You can contribute a new render through a PR without server access. Build it from your own matching game inputs with the [render workflow](RENDERING.md); see [TR_UPDATE.md](TR_UPDATE.md) for a new Tamriel Rebuilt version.

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
pnpm datasets:stage
```

The plan validates each active file's size and hash, plus the index, manifests, catalogs, locales, and audit metadata. LFS pointer files are not valid WebP payloads.

`datasets:stage` stages only the validated generated files and `config/dataset-upload-plan.json`. It removes obsolete generated paths from the Git index while preserving local copies. It does not stage other contracts: explicitly add changed index, manifest, metadata, and TR profile files with `git add -- <paths>`. Get the metadata paths from the manifest, including every referenced inventory, coverage, and audit file.

Review `git diff --cached --stat` and `git diff --cached --name-only` before committing. Do not force-add the whole generated directory: it may contain unrelated snapshots. Push the commit and its LFS objects, then open a PR into `main`.

## What to describe

Include the game/mod release, relevant rendering settings, the affected area, and the checks you ran. Include before/after images for visible changes. Explain intended changes to coverage, names, or locations so a reviewer can distinguish them from regressions.

CI validates the source-file boundary, the complete prepared graph, and browser behavior. A maintainer also generates a trusted HTML/JSON comparison report for the exact PR commit. It shows changed tiles, places, and names; a new commit requires a new report. Contributors do not need to configure production credentials or run a deployment.
