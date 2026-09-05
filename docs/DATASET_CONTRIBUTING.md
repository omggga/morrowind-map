# Contributing prepared datasets

The repository publishes the complete active graph, ready to open in a browser without
OpenMW or game files. Generate new renders locally using your own game inputs with
the shared [render workflow](RENDERING.md); [TR_UPDATE.md](TR_UPDATE.md) covers future
TR release profiles. CI validates prepared outputs and does not render
the game. Follow [CONTRIBUTING.md](../CONTRIBUTING.md): use a topic branch and a pull request
into `main`, and write documentation, commit messages, and PR titles/descriptions in English.

## Repository contents

- Git LFS applies only to `apps/web/public/datasets/generated/**/*.webp`.
- Generated JSON catalogs and locales, the index, manifests, metadata, audit reports,
  and `tiles.ndjson` are regular Git blobs.
- Game inputs (`ESM`, `ESP`, `BSA`, `BA2`, `DDS`, `NIF`, and other original assets), local
  source trees, renderer checkpoints, intermediate renders, and candidate trees must
  never enter Git or LFS.

Old generated snapshots may remain on your disk. Publish only files reachable from the
current `datasets/index.json`; do not stage the entire `generated` tree or working directory.
Do not broaden the LFS rule to all binary files or JSON.

## Preparing a pull request

First generate an isolated candidate with `render:original`, `render:tamriel-rebuilt`,
or `render:all`. Preview its recorded `publicRoot`, then adopt it with
`pnpm render:use --public-root <candidate-public-directory>`. Adoption validates the
full graph and rendered browser acceptance, updates only local prepared files and
associated configuration, and stages or deploys nothing. See [RENDERING.md](RENDERING.md)
for the complete commands and input layout.

After adoption, run these commands from the repository root:

```bash
git lfs install
pnpm deploy:datasets:plan
pnpm test:acceptance:prepared
pnpm datasets:stage
```

`deploy:datasets:plan` validates the active index, manifests, catalogs, locales,
audit/inventory metadata, and each active WebP's size and hash. It writes
`artifacts/deployment/dataset-upload-plan.json`, describing the complete active graph
of both maps rather than only the PR diff. `datasets:stage` validates the graph again,
uses `git add -f` only for generated paths listed in `plan.files`, and writes/stages
`config/dataset-upload-plan.json`. General generated-file ignore rules stay enabled.
Previously tracked generated files outside the active graph are removed only from
the Git index; their local copies remain. The helper does not stage other configuration,
manifests, or metadata.

Add changed contracts explicitly. Replace `<datasetId>` with the new dataset ID and
get the metadata paths from its manifest:

```bash
git add -- apps/web/public/datasets/index.json
# For a changed TR profile:
git add -- config/tr-release.json
git add -- apps/web/public/datasets/manifests/<datasetId>.json
git add -- apps/web/public/datasets/metadata/<datasetId>/<inventorySha>/map-assets.json
```

The last line is one metadata example: also stage every current audit, coverage,
inventory, and catalog metadata file referenced by the package. For manual staging,
use `git add -f -- <exact-generated-path>` only for files in the validated plan,
prefixing `files[].path` with `apps/web/public/datasets/generated/`. Save that same
plan as `config/dataset-upload-plan.json` and stage it with regular `git add`.
Prefer the helper because it also removes obsolete generated paths from the index.
Do not use wildcards that capture old snapshots.

Inspect `git diff --cached --stat` and `git diff --cached --name-only`, run `pnpm verify`,
and then commit with an English message. Check the committed tree using its full SHA:

```bash
python3 -m tools.deployment.git_datasets check --repo-root . --revision <fullSHA>
```

This guard checks the source/generated boundary and LFS representation at that revision.
The source-tree check complements validation of downloaded payload bytes. After pushing,
confirm that the required LFS objects are available: an unresolved LFS pointer is not
a prepared WebP dataset. Open the PR from your topic branch into `main`.

## Review tied to a commit

A maintainer manually runs `.github/workflows/dataset-review.yml` through
**Actions → Run workflow**, selects `main`, and supplies `pr_number`. The workflow
uses trusted code from `main` to extract data at the specific candidate SHA. It does
not run candidate scripts or use the deployment environment.

Download and extract the `dataset-review-<candidateSHA>` Actions artifact. Open
`index.html` to inspect before/after tiles and changes to places and names. The full
change list is in `summary.json`; HTML image and row counts are limited, so an item
missing from the preview can still be present in the diff. When there is no prepared
base graph, the report shows bootstrap additions.

Before merging, the maintainer checks that the report's candidate SHA matches the
current PR head and reviews the report, full JSON, and CI results. A separate job
attaches `Dataset review (trusted)` to that SHA. For data or deployment tooling changes,
deployment verifies the check's provenance for the merged PR. Every new candidate
commit requires another report and review. A green check means the report was generated
successfully; acceptance of its contents remains the maintainer's decision. After
review, merging into `main` triggers CI and deployment. The initial workflow bootstrap
has already completed; new PRs use review before merge.

Branch protection was enabled and verified on 2026-09-05 after the account upgraded
to GitHub Pro. Required PRs and CI checks are enforced for `main`, including for
administrators. The repository remains private. The conditional trusted dataset
report still requires maintainer inspection, and deployment verifies its provenance.
See [CONTRIBUTING.md](../CONTRIBUTING.md) for the applied protection and review policy.

## Local report

Using trusted tooling and two prepared public trees, run:

```bash
python3 -m tools.deployment.review_datasets \
  --base-public-root /absolute/path/to/base/apps/web/public \
  --base-sha <fullBaseSHA> \
  --candidate-public-root /absolute/path/to/candidate/apps/web/public \
  --candidate-sha <fullCandidateSHA> \
  --output-dir /absolute/path/to/new-review-output \
  --preview-limit 100
```

The output directory must be new and outside both input trees. For bootstrap, omit
`--base-public-root` and `--base-sha`. Keep `index.html` beside its images and
`summary.json`; viewing the report does not require OpenMW. Local reports support
investigation, while maintainer review uses the trusted workflow artifact for the exact SHA.

## CI, deployment, and rollback

Regular CI always checks the source/LFS boundary. When data, the committed plan,
TR configuration, deployment tooling, or LFS rules change, the dataset job fetches the
payload, rebuilds the complete plan, compares it with `config/dataset-upload-plan.json`,
and runs prepared browser acceptance tests for relevant PRs and `main` runs.
Automatic CI runs for pull requests and pushes to `main`; topic-branch pushes do
not trigger a second workflow. Manual runs remain available. Application-only CI
leaves LFS pointers in place without downloading the large tiles.

Deployment from `main` first sends the committed plan to the server with `--probe-plan`.
If the graph is already present and validates, LFS download/upload is skipped. Only
`missing` triggers fetching LFS objects for the deployment commit and uploading with
`--stage-only`. The uploader installs a verified immutable graph at
`/srv/morrowind-map/data/releases/<graphSha256>`, preserving previous graphs and legacy
`data/generated`. The installer pins each application release's `datasets/generated`
to that graph. Nginx serves data through `current/datasets/generated`, so switching
`current` or rolling back switches the application and its data together. See
[DEPLOYMENT.md](DEPLOYMENT.md) and [DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md).

Application releases and dataset graphs remain until a separate future garbage-collection
procedure is introduced. Failed application deployment does not remove staged graphs.
No automatic backup is configured: retaining releases on the same server supports
rollback but does not protect against server loss.

Git LFS has separate storage and bandwidth quotas. Repeated Actions downloads consume
the repository owner's bandwidth allowance, and new file versions add storage. Before
a large dataset update, check account usage and budget. Current terms are documented
in [Git LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs).
