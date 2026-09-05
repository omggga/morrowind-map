# Application deployment

Create a topic branch such as `feature/...`, `fix/...`, or `docs/...` from `main`
and submit a pull request back to `main`. The repository remains private.
Use English for documentation, commit messages, and pull request titles and descriptions.
See [CONTRIBUTING.md](../CONTRIBUTING.md) for the repository workflow.

VPS provisioning, nginx, the tunnel, and recovery are covered in
[DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md). The nginx templates are in
[tools/deployment/nginx](../tools/deployment/nginx/).

CI first checks committed Git objects with the source/LFS guard and detects changes
to datasets, the publication plan, TR configuration, deployment tooling, and LFS rules.
It then builds the application once and packages that `dist` with
`pnpm deploy:package --skip-build --commit-sha "$GITHUB_SHA"`.
The package and its SHA-256 checksum become artifacts of that workflow run.

For changes to data or deployment tooling, the separate `datasets` job fetches LFS
objects, validates the complete active graph, compares the rebuilt plan with
`config/dataset-upload-plan.json`, and runs `pnpm test:acceptance:prepared`.
Application-only CI leaves LFS pointers in place and does not download tiles.
Automatic CI runs for pull requests and pushes to `main`; topic-branch pushes do
not start a second workflow. The heavy dataset job runs only when relevant files
change. Manual workflow runs remain available.

After `verify` succeeds and `datasets` succeeds or is skipped, `deploy` runs only
for a push to `main` or a manual `workflow_dispatch` on `main`. Other branches and
pull requests never deploy. The job downloads the artifact from the same run;
the server neither rebuilds the application nor checks out another version.

Manual deployment: **Actions → CI → Run workflow → main**, or:

```bash
gh workflow run ci.yml --repo omggga/morrowind-map --ref main
```

Manual runs pass the same checks before deployment. If `main` has advanced,
a stale deployment fails before connecting to the server. Deployments run
sequentially in concurrency group `morrowind-map-production`: `queue: max`
retains waiting jobs and `cancel-in-progress: false` preserves a running deployment.
A server-side `flock` also protects the `current` switch, health checks, and rollback,
including simultaneous manual installer runs. Changes to generated datasets remain
locked throughout that operation.

## Maintainer workflow

1. Prepare changes on a topic branch. For dataset changes, run
   `pnpm deploy:datasets:plan`, `pnpm test:acceptance:prepared`,
   `pnpm datasets:stage`, and `pnpm verify` locally. The staging helper adds only
   validated active generated files and writes/stages `config/dataset-upload-plan.json`.
   Add contracts explicitly as described in [DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md).
   For application or documentation changes, follow the checks in [CONTRIBUTING.md](../CONTRIBUTING.md).
2. Open a pull request into `main`. For data or deployment tooling changes, run
   **Actions → Dataset review (trusted) → Run workflow → main** with `pr_number`.
   The workflow pins the PR SHA, reads Git objects and LFS data without checking
   out candidate code, and generates an HTML/JSON report using trusted scripts from `main`.
3. When trusted dataset review is required, download `dataset-review-<candidateSHA>`
   and inspect `index.html`, the full
   `summary.json`, and the current PR head SHA. A separate job attaches the
   `Dataset review (trusted)` check to that SHA. Each new commit requires a new
   report and review. A green check confirms report generation; the maintainer
   decides whether the contents are acceptable.
4. After review and successful CI, merge the PR into `main`. For data or deployment
   tooling changes, `require_dataset_review` verifies the successful check and its
   workflow provenance for the merged PR head before any connection to the VPS.

The initial bootstrap is complete: PR #1 installed the trusted review workflow,
its first deployment was blocked until review succeeded, and the same CI artifact
was then deployed by rerunning the failed deployment. New changes use the normal
review-before-merge workflow. An old report cannot approve another commit.

Branch protection was enabled and verified on 2026-09-05 after the account upgraded
to GitHub Pro. The repository remains private. GitHub requires a PR, current CI
checks, an up-to-date branch, and resolved conversations, including for administrators;
force pushes and deletion of `main` are disabled. The conditional dataset-review
provenance gate remains an additional publication control. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for the applied settings and review policy.

## Access

Store environment secrets under **Settings → Environments → production**:

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | Deployment server SSH hostname or IP; never commit the value |
| `DEPLOY_USER` | `morrowind-map` |
| `DEPLOY_SSH_KEY` | Dedicated CI private SSH key without a passphrase |
| `DEPLOY_KNOWN_HOSTS` | Verified server host key in known_hosts format |

The environment uses selected deployment branches, allowing only branch `main`;
there are no tag or `refs/pull/*/merge` rules. These secrets are not stored at the
repository level. Neither `verify`, `datasets`, nor trusted dataset review uses
the deployment environment. `deploy` receives secrets only after CI gates and
only for a push or `workflow_dispatch` on `main`. No `pull_request_target` workflow
is used. Private-repository fork PR settings disable workflow runs, secret/variable
access, and write tokens. Checkout does not persist the GitHub token in Git configuration.

The public key has the `restrict` option and lives in the root-owned
`/etc/ssh/authorized_keys/morrowind-map`. The deployment account has no sudo access
and cannot add another authorized key. Account-level restrictions in
`tools/deployment/sshd-morrowind-map.conf` disable passwords, PTY, user rc,
agent/X11/TCP forwarding, and tunnels. Installation commands and SFTP for SCP
remain available as the site user.

SSH accepts only the pinned Ed25519 host key from `DEPLOY_KNOWN_HOSTS`:
`StrictHostKeyChecking yes`, `HostKeyAlgorithms ssh-ed25519`,
`GlobalKnownHostsFile /dev/null`, and `UpdateHostKeys no`. Deployment does not run
`ssh-keyscan`. After a host key change, verify the replacement through trusted
administrative access before updating the environment secret.

Repository visibility does not grant deployment access. External contributors submit
issues and fork pull requests; only authorized maintainers can merge protected `main`
or administer the production environment. Public PR checks run without deployment
credentials. Review any workflow permission changes before merging them.

Keep private hostnames, origin addresses, private keys, certificate files, and tunnel
credentials out of tracked files and PR descriptions. Host connection details and the
CI SSH key belong only in production environment secrets; tunnel credentials and TLS
private material stay with the hosting provider or administrator. Public site URLs,
loopback addresses, generic account names, and secret variable names are configuration
examples, not credentials.

Before changing repository visibility, inspect all Git history, tags, branches, PR
diffs, and Actions logs/artifacts. Deleting a value from the latest tree does not
remove older copies. If a credential was committed, revoke or rotate it before any
history cleanup. Removing non-secret infrastructure identifiers from old history
also requires a separately coordinated history rewrite or a fresh public history;
normal commits cannot erase earlier revisions.

GitHub does not expose a stored private key. To rotate it, test the new key first,
store it in the production environment, remove the old server authorization,
and delete the temporary local private key copy.

## Installation

Nginx at `127.0.0.1:9003` serves `/srv/morrowind-map/current`; Cloudflare Tunnel
connects the public domain.

Deployment first sends only the committed `config/dataset-upload-plan.json` with
`upload_datasets --probe-plan ... --host production`. The server validates the
plan and immutable graph contents. An `already-staged` result avoids downloading
and transferring roughly 2.3 GB of tiles; this is the normal application-only path.
Only `missing` triggers LFS fetch for the deployment commit, full local validation,
plan comparison, and upload with `--stage-only`. Validation or connection errors
stop deployment instead of being treated as a missing graph.

The uploader installs `/srv/morrowind-map/data/releases/<graphSha256>` and returns
that path. It does not change legacy `data/generated` or delete other graphs;
it cleans up only its own temporary transfer directory.

The job then sends the package and Python tooling from the same commit to
`incoming-ci/<run-id>-<attempt>`. The installer verifies the checksum, full commit
SHA, archive contents, manifests, installed catalog hashes, and the presence and
aggregate size of all expected tiles. The separate dataset uploader/probe validates
all tile hashes on the server; the installer validates the application contracts
against the selected graph.

The installer receives `--dataset-graph` from the committed plan. After validation,
it installs the package in `releases/<full-commit-sha>` and pins that release's
`datasets/generated` to the immutable graph. It switches `current` with an atomic
symlink replacement. Reinstalling the same package is allowed; modifying an existing
immutable release is rejected. Before switching, it also validates the previous
release and its own generated artifacts. Missing or damaged fallback data stops
deployment because a working rollback would be unavailable.

After switching, the installer runs the existing `deploy:health` implementation
(`python3 -m tools.deployment.health_check`) against both local nginx and the public
HTTPS site, with a 120-second limit per check. Any failed check or timeout atomically
restores the previous `current` symlink and leaves the job failed. On an initial
installation without a previous release, it removes the failed `current`. The failed
release directory remains available for diagnosis.

The nginx `/datasets/generated/` alias resolves through `current/datasets/generated`.
Rollback therefore switches both application and dataset graph together. It creates
no backups and cannot repair nginx/tunnel failures or lost datasets. Forced process
termination or server loss can prevent automatic rollback; use the runbook.

The deployment layout uses pinned graphs and the release-relative nginx alias.
The runbook retains a one-time migration procedure for legacy installations. `data/generated` is only a legacy migration or
administration fallback; new deployments always pass `--dataset-graph` explicitly.

Backups, scheduled snapshots, and old-release retention management are outside this
workflow. Application releases and dataset graphs are not automatically removed.
Any future garbage collection must preserve graphs referenced by retained application
releases. Failed application deployment does not delete a staged graph. The job removes
its temporary transfer files and SSH key. CI artifacts are retained for seven days
to pass the verified package between jobs.

Use `--check-only` to validate a package without switching the site:

```bash
python3 -m tools.deployment.install_release \
  --archive <package.tar.gz> --archive-sha256 <sha256> \
  --commit-sha <full-commit-sha> --dataset-graph <graphSha256-from-plan> --check-only
```
