# Contributing prepared datasets

You can contribute a new render through a PR without server access. Build it from your own matching game inputs with the [render workflow](RENDERING.md); see [TR_UPDATE.md](TR_UPDATE.md) for a new Tamriel Rebuilt version and [Rendering](RENDERING.md#project-cyrodiil-and-future-releases) for Cyrodiil releases. [Home of the Nords](RENDERING.md#home-of-the-nords-and-future-releases) and [Lyithdonea](RENDERING.md#lyithdonea-the-azurian-isles) use the same contribution process.

## Files to include

- Ready active WebP tiles under `apps/web/public/datasets/generated/` stay local and are distributed as Release archives; do not add them to Git or LFS.
- Runtime JSON catalogs/locales, the index, manifests, metadata, audit reports, tile inventories, `config/dataset-releases.lock.json` and the upload plan use regular Git.
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
pnpm exec playwright install chromium
pnpm datasets:pack all --release v1.0.1
pnpm datasets:verify --package-root local-data/packages/releases/v1.0.1 --lock config/dataset-releases.lock.json
pnpm deploy:datasets:plan
pnpm test:acceptance:prepared
MORROWIND_RENDER_PUBLIC_ROOT="$PWD/apps/web/public" pnpm test:acceptance:rendered
pnpm datasets:stage
```

Choose the next unused product release version instead of reusing an existing release. Packing includes all active maps, reuses unchanged archives and updates the transport lock only after complete validation. The plan validates each active file's size and hash, plus the index, manifests, catalogs, locales, and audit metadata. The lock must describe that same complete graph.

`datasets:stage` stages only validated active generated JSON, `config/dataset-releases.lock.json` and `config/dataset-upload-plan.json`. It removes generated WebP and obsolete generated paths from the Git index while preserving local copies. Invalid metadata or an incomplete lock leaves staging unchanged. It does not stage other contracts: explicitly add changed index, manifest, metadata, and release profile files with `git add -- <paths>`. Get the metadata paths from the manifest, including every referenced inventory, coverage, and audit file.

Review `git diff --cached --stat` and `git diff --cached --name-only` before committing. Do not force-add the whole generated directory: it may contain unrelated snapshots. Publish the candidate bundle to a readable source release as described below, push the metadata/lock commit, and open a PR into `main`. A maintainer runs trusted review and canonical publication before the PR can merge.

## What to describe

Include the game/mod release, relevant rendering settings, the affected area, and the checks you ran. Include before/after images for visible changes. Explain intended changes to coverage, names, or locations so a reviewer can distinguish them from regressions.

CI validates the source-file boundary, the complete prepared graph, and browser behavior. A maintainer also generates a trusted HTML/JSON comparison report for the exact PR commit. It shows changed tiles, places, and names; a new commit requires a new report. Contributors do not need to configure production credentials or run a deployment.

## Local tile packages

The active contribution, CI and deployment paths use the committed transport
lock and immutable product releases. Packaging is local: it does not upload
assets, activate a map, or deploy the site. The initial five-map `v1.0.0` bundle
is already published and selected by `config/dataset-releases.lock.json`.

With ready tiles already present, build the next complete bundle:

```bash
pnpm datasets:pack all --release v1.0.1
pnpm datasets:verify --package-root local-data/packages/releases/v1.0.1 --lock config/dataset-releases.lock.json
```

Python 3.10+ is required. No renderer runs during packaging. The directory
`local-data/packages/releases/v1.0.1/` contains one shared `package-index.json`
and these five archives:

- `morrowind.tar`
- `tamriel-rebuilt.tar`
- `project-cyrodiil.tar`
- `home-of-nords.tar`
- `azurian-isles.tar`

Each archive contains only its map inventory's generated WebP tiles. It uses
deterministic, uncompressed USTAR; the WebP payloads are already compressed.
A future larger map uses independent parts such as `tamriel-rebuilt-0001.tar`
and `tamriel-rebuilt-0002.tar`. Each finished archive is at most 2,137,483,648
bytes, including headers and padding. A release can contain at most 999 archive
assets plus its shared index. Source inputs and runtime metadata are never
packed into the tile archives.

The schema-version-2 index describes the complete active map selection: every
entry shares one exact product release tag, and archive names are unique across
the release. Full hashes stay in the index and transport lock rather than
release titles or filenames. The published release is named **Morrowind
Interactive Map v1.0.0**; future versions use the same title format and stable
version tag and become **Latest**.
It is one product release with all five maps in Assets.

`datasets:verify` checks archive hashes, canonical headers and every expected
tile against the snapshot metadata. It does not extract or install anything.
The packer writes the complete active transport lock atomically after successful
verification. Stage it with `pnpm datasets:stage` alongside the validated JSON
and upload plan; package archives remain under ignored `local-data/packages/`.

`--release` is required, and the CLI accepts only `all`: a product release always
contains every active map. A changed bundle needs a new `vMAJOR.MINOR.PATCH` tag;
leading zeroes, prerelease suffixes and build suffixes are not accepted. An
existing version is reusable only when its complete package selection matches.
The lock is replaced only after that complete selection validates. Unchanged
maps reuse verified local TAR bytes and hashes, including for catalog-only
updates, while every lock entry moves to the new shared release tag. The
downloader also reuses unchanged archives from its SHA-256 cache.

Keep published versions needed by committed locks, historical snapshots and
rollbacks. Replacing the initial, unadopted migration artifacts is a one-time
cleanup; future releases do not authorize deleting their predecessors.

## Restoring a Release-backed snapshot

After `pnpm install --frozen-lockfile`, restore every active map selected by
the committed `config/dataset-releases.lock.json` with:

```bash
pnpm datasets:download
```

Python 3.10+ on macOS or Linux is sufficient; the downloader uses the standard
library. It also works from a source ZIP without Git, Docker, or game inputs.
The repository is currently private. The downloader reads `GH_TOKEN` /
`GITHUB_TOKEN` from the environment or an existing `gh auth login` session. A fine-grained token needs only
repository Contents read access. Public releases support `--anonymous`, which
does not read credentials or require `gh`. Never put tokens in command arguments.
GitHub's [Release asset API](https://docs.github.com/en/rest/releases/assets#get-a-release-asset)
supports API delivery and redirects; credentials are sent only to the initial
canonical GitHub API request, never to redirected storage hosts.

The committed lock selects an exact immutable product release and archive
hashes; remote metadata cannot replace it. Downloads never resolve `Latest`.
Historical schema-version-1 locks still use their original inventory-bound
release tags. Downloads use a SHA-256 cache under ignored
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
Every exported snapshot must contain its own valid transport lock and upload
plan. Tracked generated WebP and LFS pointers are rejected. Snapshot tools read
Git objects directly as data; they never execute candidate code, run checkout
filters, or restore LFS objects. Commits from before the Release migration are
outside the current tooling's supported snapshots.

## Trusted review and publication

The maintainer dispatches `Dataset review (trusted)` from `main`. All jobs use
the same trusted tool commit. Candidate Git objects are exported as data;
candidate scripts and workflows never execute in this review. Both the PR head
and base must match the dispatch inputs, which are also recorded in the run
title. A new head or base requires a fresh review.

Run this review before merging changes to datasets, deployment tools or their
workflows, even when the active map graph is unchanged. Ordinary CI and prepared
map checks do not replace `Dataset review (trusted)`; wait for that check on the
exact PR head before merging.

For a PR, use its current head/base SHAs. Both snapshots use their own committed
Release lock:

```bash
pr=123
head_sha=$(gh api "repos/omggga/morrowind-map/pulls/$pr" --jq .head.sha)
base_sha=$(gh api "repos/omggga/morrowind-map/pulls/$pr" --jq .base.sha)
gh workflow run dataset-review.yml --repo omggga/morrowind-map --ref main \
  -f pr_number="$pr" -f expected_head="$head_sha" -f expected_base="$base_sha"
```

A Release-backed snapshot uses its committed lock automatically. If a package
is not yet canonical, supply `source_mapping`: a JSON array with one object per
map package identity that needs a source. For example:

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
release IDs, not URLs or tags. A published source release may belong to a
contributor repository, provided the trusted workflow token can read it. It
contains `<assetPrefix>package-index.json` and the indexed archive names with
the same prefix. For a product bundle these are the short map names above;
historical version-1 sources retain names such as `tiles-0001.tar`. The prefix
is optional (`""`); a nonempty prefix starts with a letter or digit and contains
only letters, digits, dots, underscores and hyphens. Several maps may share one
source release. Sources are bounded to 100 identities and 128 KiB.

Source releases must be **published**. The read-only Actions review token cannot
read drafts; do not use an unpublished draft as a workflow source. The initial
complete `v1.0.0` bundle was verified and published by the maintainer, then
independently restored and validated through trusted Actions. Future candidates
can use published external source releases; the separate publication job creates
or resumes the canonical destination draft after review succeeds. All source
IDs and archive hashes are frozen in the review receipt.

The review checks every map, archive and tile, compares the complete graphs,
and retains a small HTML/JSON report and hash-bound receipt for seven days.
The report lists all changes and samples previews. Archive payloads are not
uploaded as Actions artifacts. A separate `dataset-publication` environment job
re-fetches the pinned source assets, checks their hashes, and publishes one
canonical product release containing the complete bundle and its shared index.
Publication is serialized. It reuses an exact immutable release or resumes an
exact matching draft; conflicting assets are never overwritten. Every map
entry, archive and the full shared index must match the reviewed snapshot.
Missing API digests are checked by downloading and hashing the bytes.
The stable product release becomes Latest for people browsing GitHub; trusted
review, downloads and publication still use only exact tags, numeric source IDs
and the hashes bound to the receipt.

Within Actions, only the publication job has Contents write access. The environment must allow
only `main`, contain no production SSH secrets, and have the nonsecret variable
`IMMUTABLE_RELEASES_CONFIRMED=true` after a maintainer confirms repository release
immutability. The [settings API](https://docs.github.com/en/rest/repos/repos#check-if-immutable-releases-are-enabled-for-a-repository)
requires Administration read access, which the workflow token does not receive.
The variable records that preflight confirmation; publication also verifies that
each resulting release actually reports `immutable: true` before succeeding.

The PR check succeeds only after review and publication. The merge gate verifies
the successful trusted main run, exact head/base run title, current run attempt,
and committed lock/graph binding. Its compact check record remains available
after the downloadable report expires. Checks without this durable binding are
rejected. Publishing a package does not activate a map or deploy the site.

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

If a PR was merged before its trusted review ran, the same workflow can review
the merged PR. Use its original head and the merge commit's first parent as the
base, rather than the current tip of `main`:

```bash
pr=123
head_sha=$(gh api "repos/omggga/morrowind-map/pulls/$pr" --jq .head.sha)
merge_sha=$(gh api --paginate "repos/omggga/morrowind-map/issues/$pr/timeline" --jq '.[] | select(.event == "merged") | .commit_id')
base_sha=$(gh api "repos/omggga/morrowind-map/git/commits/$merge_sha" --jq '.parents[0].sha')
gh workflow run dataset-review.yml --repo omggga/morrowind-map --ref main \
  -f pr_number="$pr" -f expected_head="$head_sha" -f expected_base="$base_sha"
```

Recovery requires a PR merged into canonical `main` with a two-parent merge
commit whose second parent is the exact PR head. A closed, unmerged PR, squash
merge, or mismatching head/base is rejected. The normal archive, graph, receipt
and publication checks still run; the deployment gate also checks the actual
merged snapshot. After the trusted check succeeds, rerun the failed deployment
job for that main commit only if it is still the intended production revision.
Use Actions for that retry; `dataset_review_retry` targets open PR CI runs only.

To review and publish a Release-backed baseline without a PR, use
`pr_number=0`, `bootstrap_sha=<full-main-ancestor-SHA>` and `source_mapping=[]`.
That commit must be an ancestor of the trusted tools and contain its own lock
and upload plan. This mode has no PR check and cannot restore snapshots from
before the Release migration. Publishing a bundle does not change repository
visibility or noncommercial licensing, and does not activate or deploy a map.
