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

The package tooling and trusted publication support Release transport while the
active contribution, CI and deployment workflow above still uses Git LFS. Packaging is local: it does
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

## Trusted review and publication

The maintainer dispatches `Dataset review (trusted)` from `main`. All jobs use
the same trusted tool commit. Candidate Git objects are exported as data;
candidate scripts and workflows never execute in this review. Both the PR head
and base must match the dispatch inputs, which are also recorded in the run
title. A new head or base requires a fresh review.

For an existing LFS PR, use the current head/base SHAs and the default transport:

```bash
pr=123
head_sha=$(gh api "repos/omggga/morrowind-map/pulls/$pr" --jq .head.sha)
base_sha=$(gh api "repos/omggga/morrowind-map/pulls/$pr" --jq .base.sha)
gh workflow run dataset-review.yml --repo omggga/morrowind-map --ref main \
  -f pr_number="$pr" -f expected_head="$head_sha" -f expected_base="$base_sha"
```

A Release-backed snapshot uses its committed lock automatically. If a package
is not yet canonical, supply `source_mapping`: a JSON array with one object per
new package identity. For example:

```json
[
  {
    "datasetId": "example-dataset",
    "pyramidId": "example-pyramid",
    "inventorySha256": "<64 lowercase hexadecimal characters>",
    "repository": "contributor/source-packages",
    "releaseId": 123456,
    "assetPrefix": "example-"
  }
]
```

Pass the JSON as the `source_mapping` dispatch input, for example
`-f source_mapping="$(cat local-data/source-mapping.json)"`. Use numeric GitHub
release IDs, not URLs or tags. The source release must be published and
readable by the trusted workflow token. It contains `<assetPrefix>tiles-0001.tar`
and every other part in that map's descriptor. The prefix is optional (`""`);
a nonempty prefix starts with a letter or digit and contains only letters,
digits, dots, underscores and hyphens. Several maps may share one source release
with different prefixes. Sources are bounded to 100 identities and 128 KiB.
Unchanged packages are restored from their canonical immutable releases.

The review checks every map, archive and tile, compares the complete graphs,
and retains a small HTML/JSON report and hash-bound receipt for seven days.
The report lists all changes and samples previews. Archive payloads are not
uploaded as Actions artifacts. A separate `dataset-publication` environment job
re-fetches the pinned source assets, checks their hashes, and publishes canonical
releases. Publication is serialized. It reuses an exact immutable release or
resumes an exact matching draft; conflicting assets are never overwritten.
Missing API digests are checked by downloading and hashing the bytes.

Only this publication job has Contents write access. The environment must allow
only `main`, contain no production SSH secrets, and have the nonsecret variable
`IMMUTABLE_RELEASES_CONFIRMED=true` after a maintainer confirms repository release
immutability. The [settings API](https://docs.github.com/en/rest/repos/repos#check-if-immutable-releases-are-enabled-for-a-repository)
requires Administration read access, which the workflow token does not receive.
The variable records that preflight confirmation; publication also verifies that
each resulting release actually reports `immutable: true` before succeeding.

The PR check succeeds only after review and publication. The merge gate verifies
the successful trusted main run, exact head/base run title, current run attempt,
and committed lock/graph binding. Its compact check record remains available
after the downloadable report expires. Historical checks are accepted only for
LFS snapshots. Publishing a package does not activate a map or deploy the site.

For a failed publication, dispatch a fresh review or choose **Re-run all jobs**;
receipts belong to one run attempt. Matching drafts can be resumed on that new
attempt. After successful publication, an explicitly selected failed CI run for
the same PR head can be retried with:

```bash
python3 -m tools.deployment.dataset_review_retry --pr-number 123 --run-id 456789
```

This maintainer command needs Actions write access and rechecks the current PR,
CI run and trusted review immediately before retrying failed jobs. The review
workflow itself has no Actions write permission.

The explicit bootstrap mode uses `pr_number=0`, `bootstrap_sha=<full-main-ancestor-SHA>`
and source mappings. It derives each descriptor from that baseline's own metadata,
inventory and prefixed `package-index.json`, then verifies all bytes. It never
borrows a candidate PR's lock for a historical base. `legacy_transport=releases`
uses the same adapter when reviewing an old LFS base after packages exist; it
does not fetch LFS payloads. Bootstrap has no PR check. These operations require
the publication tools to have been merged into trusted `main` first.
