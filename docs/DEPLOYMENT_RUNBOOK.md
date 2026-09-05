# Deployment and recovery runbook

Reference platform: Ubuntu 22.04, nginx 1.18, Python 3.10 or newer,
and system services `nginx` and `cloudflared`.
See [DEPLOYMENT.md](DEPLOYMENT.md) for CI and access restrictions, and
[CONTRIBUTING.md](../CONTRIBUTING.md) for the topic-branch → PR → `main` policy.
Commands using `ssh deploy-admin` require administrative access; CI runs as `morrowind-map`.
Run local commands from the repository root.

## Serving the site

```text
https://morrowindmap.com
  → Cloudflare Tunnel (cloudflared.service)
  → http://127.0.0.1:9003 (nginx.service)
  → /srv/morrowind-map/current → releases/<full-commit-sha>
  → /datasets/generated/* → current/datasets/generated/*
  → /srv/morrowind-map/data/releases/<graphSha256>/*
```

| Path / setting | Purpose |
| --- | --- |
| `/srv/morrowind-map/releases/<sha>` | Application, index, manifests, compact metadata, and release manifest |
| `/srv/morrowind-map/current` | Atomically replaced symlink to the active application |
| `/srv/morrowind-map/releases/<sha>/datasets/generated` | Application's pinned link to its immutable graph |
| `/srv/morrowind-map/data/releases/<graphSha256>` | Uploaded generated catalog/locale/tile graph |
| `/srv/morrowind-map/data/generated` | Legacy fallback for initial migration only |
| `/srv/morrowind-map/incoming-ci/` | Temporary application packages and installer |
| `/srv/morrowind-map/.app-deploy.lock` | Lock covering application deployment, checks, and rollback |
| `/srv/morrowind-map/data/.dataset-upload.lock` | Dataset-change lock |
| `/etc/nginx/conf.d/morrowind-map.conf` | [Site template](../tools/deployment/nginx/morrowind-map.conf) |
| `/etc/nginx/snippets/morrowind-map-security.conf` | [Shared HTTP headers](../tools/deployment/nginx/morrowind-map-security.conf) |
| `/etc/cloudflared/config.yml` | Tunnel routes; preserve any unrelated entries |
| `/etc/ssh/authorized_keys/morrowind-map` | Root-owned authorized public keys |

Nginx listens only on loopback. TLS terminates at Cloudflare.
Serving the site requires no Node.js,
renderer, or game files on the VPS.

HTML, the dataset index, and manifests require cache revalidation. Assets, versioned
metadata, and generated data use a one-year immutable cache. Missing datasets return
404 with `no-store`, without SPA fallback. Security headers are included again inside
locations because of nginx 1.18 `add_header` inheritance rules.

## Provisioning a new VPS

Configure `deploy-admin` as a local administrative SSH alias in `~/.ssh/config`.
It is an example alias, not a public hostname. Replace the placeholders locally;
never copy connection details or keys into the repository:

```sshconfig
Host deploy-admin
  HostName <YOUR_DEPLOYMENT_HOST>
  User <YOUR_ADMINISTRATOR_ACCOUNT>
  IdentityFile <YOUR_LOCAL_ADMINISTRATOR_KEY_PATH>
  IdentitiesOnly yes
  StrictHostKeyChecking yes
```

Provision and verify the host key through a trusted administrative channel before
connecting. This administrative key is separate from the restricted Actions key.
Run the following commands **as root on the new server**:

```bash
apt-get update
apt-get install -y nginx python3 openssh-server ca-certificates curl rsync
getent passwd morrowind-map || useradd --system --user-group \
  --home-dir /srv/morrowind-map --shell /bin/bash morrowind-map
install -d -o morrowind-map -g morrowind-map -m 750 \
  /srv/morrowind-map /srv/morrowind-map/releases /srv/morrowind-map/data
install -d -o morrowind-map -g morrowind-map -m 700 \
  /srv/morrowind-map/incoming-ci
usermod -a -G morrowind-map www-data
```

Do not grant the site user sudo access. Group membership lets nginx read directories
with mode 750; workers must receive the updated supplementary groups. Tooling creates
`current` and links inside application releases. A new server does not need `data/generated`.

### SSH and GitHub

For a new server or lost key, generate a dedicated Ed25519 key in a temporary local
directory with mode 700. Never write the private key into the repository. GitHub cannot
return a previously stored private key.

Give the public key to the server administrator and install the line
`restrict ssh-ed25519 <PUBLIC_KEY> github-actions:morrowind-map` in
`/etc/ssh/authorized_keys/morrowind-map` (root:root, 644; parent root:root, 755).
Install the [sshd template](../tools/deployment/sshd-morrowind-map.conf) as
`/etc/ssh/sshd_config.d/60-morrowind-map-deploy.conf` (root:root, 644).

```bash
/usr/sbin/sshd -t && systemctl reload ssh
/usr/sbin/sshd -T -C user=morrowind-map,host=localhost,addr=127.0.0.1
sudo -l -U morrowind-map
```

Test login with the new key, SCP, absence of sudo, denied PTY/forwarding, and inability
to modify the root-owned authorized keys. Keep the administrative connection open
until a separate login succeeds.

Read `/etc/ssh/ssh_host_ed25519_key.pub` through a trusted administrative channel and
create a known_hosts entry: `<DEPLOY_HOST> ssh-ed25519 <HOST_PUBLIC_KEY>`. For a new
server, verify its fingerprint through the provider console first. Pin it in
`DEPLOY_KNOWN_HOSTS`; do not disable strict checking to gain access. Client SSH settings
are in [.github/workflows/ci.yml](../.github/workflows/ci.yml).

Update four secrets in GitHub environment `production`: `DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_SSH_KEY`, and `DEPLOY_KNOWN_HOSTS`. For files, use
`gh secret set NAME --repo omggga/morrowind-map --env production < FILE`.
Allow only **branch main**, without tag/PR rules. These secrets must not also exist
at repository level; fork PRs receive neither secrets nor write tokens. After testing
the new key, revoke the old public key and remove the temporary local private key copy.

### Restore data before the application

Restore a prepared graph from the chosen commit: JSON is in Git and WebP is in LFS.
Probe the server first to avoid downloading tiles again. Original game/mod assets
cannot be restored from GitHub.

Configure a local SSH alias `morrowind-map-deploy` for the server with
`User morrowind-map`, a dedicated key, and pinned known_hosts as in CI.
From a checkout of the chosen release:

```bash
python3 -m tools.deployment.upload_datasets \
  --probe-plan config/dataset-upload-plan.json --host morrowind-map-deploy
```

`already-staged` confirms that the existing graph passed server validation.
Only for `missing`, fetch and install the payload:

```bash
git lfs install
git lfs pull --include='apps/web/public/datasets/generated/**/*.webp' --exclude=''
pnpm deploy:datasets:plan
cmp config/dataset-upload-plan.json artifacts/deployment/dataset-upload-plan.json
pnpm deploy:datasets:upload --host morrowind-map-deploy --stage-only
```

The plan validates hashes and the complete local inventory; the uploader transfers
only reachable generated files and verifies them on the server. `--stage-only` neither
switches `data/generated` nor removes previous graphs. Save `graphSha256` from the
committed plan for `install_release --dataset-graph`. CI follows this same
probe/missing/upload sequence automatically. A graph validation failure needs diagnosis,
not an upload over a damaged immutable directory. Do not treat SSH/validation errors as `missing`.

### One-time migration of a legacy VPS

Use this procedure only for legacy installations where nginx still serves
`data/generated` directly: migrate **before enabling the new
deployment workflow**. Pause new deployments and wait for active installers/uploaders.
Check the running site and a valid `current/release-manifest.json`, which the installer
uses to validate its fallback.

```bash
ssh deploy-admin 'readlink -f /srv/morrowind-map/current; readlink -f /srv/morrowind-map/data/generated'
pnpm deploy:health --base-url https://morrowindmap.com/
```

Confirm that the first path is an existing `releases/<appSHA>` and the second is a
real `data/releases/<graphSha256>` matching the current application's manifests.
Validate the previous release manifest before changing its dataset link. If `current/datasets/generated` exists, verify its
target without replacing it. If absent, pin the **actual current graph**:

```bash
ssh deploy-admin 'flock /srv/morrowind-map/.app-deploy.lock sh -eu -c '\''
  graph=$(readlink -f /srv/morrowind-map/data/generated)
  case "$graph" in /srv/morrowind-map/data/releases/*) ;; *) exit 1 ;; esac
  test -d "$graph"
  test -f /srv/morrowind-map/current/release-manifest.json
  test ! -e /srv/morrowind-map/current/datasets/generated
  test ! -L /srv/morrowind-map/current/datasets/generated
  ln -s "$graph" /srv/morrowind-map/current/datasets/generated
'\'''
```

After pinning, install the nginx template as below, run `nginx -t`, reload nginx,
and run both origin/public health checks. The alias now follows
`current/datasets/generated`; the old `current` remains a working fallback.
Keep legacy `data/generated` during migration, but do not use it to switch new graphs.
New deployments always pass `--dataset-graph`.

### Nginx

Copy the templates from the local machine:

```bash
scp tools/deployment/nginx/morrowind-map.conf deploy-admin:/tmp/morrowind-map.conf
scp tools/deployment/nginx/morrowind-map-security.conf deploy-admin:/tmp/morrowind-map-security.conf
```

Install them as root on the VPS:

```bash
install -d -m 755 /etc/nginx/snippets
install -o root -g root -m 644 /tmp/morrowind-map-security.conf /etc/nginx/snippets/morrowind-map-security.conf
install -o root -g root -m 644 /tmp/morrowind-map.conf /etc/nginx/conf.d/morrowind-map.conf
nginx -t && systemctl reload nginx
```

The main `/etc/nginx/nginx.conf` must include `/etc/nginx/mime.types` and
`/etc/nginx/conf.d/*.conf` inside `http`, and workers must run as `www-data`.
If nginx is not running on a new server, use `systemctl enable --now nginx` after
`nginx -t`. Restart nginx after adding its group during initial setup. Subsequent
template changes need only `nginx -t && systemctl reload nginx`; switching the
application needs no reload. Preserve the shared nginx.conf and other sites' configuration.

### Cloudflare Tunnel

Preserve other routes in `/etc/cloudflared/config.yml` on the existing VPS.
Place the map route **before** the final catch-all:

```yaml
ingress:
  # Keep the other sites' routes here.
  - hostname: morrowindmap.com
    service: http://127.0.0.1:9003
  - service: http_status:404
```

On a new VPS, install cloudflared using the [official instructions](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/).
For a locally managed tunnel, restore access through the Cloudflare account and create
a tunnel and DNS route for `morrowindmap.com`, or use a retained tunnel credential.
Set `tunnel` and `credentials-file` in the configuration. Keep credential JSON only
on the server with root:root ownership and mode 600. Neither these credentials nor
the account certificate belongs in the repository. See the
[official tunnel setup guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/).

```bash
cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
cloudflared --config /etc/cloudflared/config.yml tunnel ingress rule https://morrowindmap.com/
```

On a new server, install the systemd service with
`cloudflared --config /etc/cloudflared/config.yml service install` and start it with
`systemctl enable --now cloudflared`. On an existing server, after validation, apply
configuration changes using `systemctl restart cloudflared`. If the tunnel serves other sites, restarting affects those routes too.

### First deployment and repeat runs

Once nginx/tunnel are ready and any legacy migration is complete, follow
review → merge → CI in [DEPLOYMENT.md](DEPLOYMENT.md). The initial workflow bootstrap
is already complete on this repository. When setting up an equivalent repository
from scratch, the initial merge installs the trusted workflow but blocks deployment
until review: run `dataset-review.yml` from `main` for that initial PR, inspect its
head-SHA artifact, then rerun the failed deployment in the original CI run.

To rerun an already reviewed `main`:

```bash
gh workflow run ci.yml --repo omggga/morrowind-map --ref main
```

The workflow must already exist in `main`. It validates the commit, downloads the
artifact from that run, checks review provenance for data/tooling changes, probes
the server graph (fetching LFS only if absent), installs the application, and checks
origin/public URLs. Without a previous release, a failed first deployment removes
`current` and leaves the job failed.

## Diagnosis and recovery

Start with read-only checks:

```bash
ssh deploy-admin 'readlink /srv/morrowind-map/current; readlink -f /srv/morrowind-map/current/datasets/generated'
ssh deploy-admin 'systemctl is-active nginx cloudflared; nginx -t'
ssh deploy-admin 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9003/'
pnpm deploy:health --base-url https://morrowindmap.com/
ssh deploy-admin 'tail -n 60 /var/log/nginx/morrowind-map.error.log'
ssh deploy-admin 'journalctl -u cloudflared -n 60 --no-pager'
```

| Symptom | Action |
| --- | --- |
| CI reports `restored current` | Automatic rollback completed; the job intentionally remains failed. Compare readlink with `previous current` in the job log, check the site, and fix the cause before retrying. |
| Origin healthy, public URL failing | Check `cloudflared`, ingress rules, DNS route, and Cloudflare cache rules. Application rollback cannot fix a network failure. |
| Nginx 403 | Check `id www-data`, mode 750 on parent directories, and readable files. www-data must belong to the morrowind-map group. |
| Dataset 404 or installer reports a missing artifact | Check the specific application's `datasets/generated`, then restore that exact graph through LFS, plan validation, and stage-only upload. Legacy `data/generated` may refer to another version. |
| Deployment requires trusted dataset review | Check the merged PR head SHA and check provenance; run the trusted workflow from main for that PR, inspect the report, and rerun the failed deployment. |
| Host key mismatch | Verify the host fingerprint through administrative access and update the environment secret. |
| Deployment waiting | Check Actions concurrency and active installer/uploader processes. Do not delete lock files: doing so breaks locking. |

### Manually restoring a verified package

Use this procedure after a failed release, lost `current`, or interrupted installer.
Pause new deployments and wait for the active deployment to finish. Choose a CI run
with successful **verify**, applicable dataset gates, and maintainer review for a
known working commit. Normal deployment rejects a stale SHA, so restoring one uses
the installer directly. Artifacts are retained for seven days.

From a local checkout with trusted deployment tools:

```bash
RUN_ID=123456789  # Replace with the actual selected run.
gh run view "$RUN_ID" --repo omggga/morrowind-map --json headSha,headBranch,jobs
COMMIT_SHA=$(gh run view "$RUN_ID" --repo omggga/morrowind-map --json headSha --jq .headSha)
DATASET_GRAPH=$(git show "$COMMIT_SHA:config/dataset-upload-plan.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["graphSha256"])')
PACKAGE_DIR=$(mktemp -d)
gh run download "$RUN_ID" --repo omggga/morrowind-map \
  --name "application-$COMMIT_SHA" --dir "$PACKAGE_DIR"
ARCHIVE="morrowind-map-$(printf '%.12s' "$COMMIT_SHA").tar.gz"
(cd "$PACKAGE_DIR" && shasum -a 256 -c "$ARCHIVE.sha256")
ARCHIVE_SHA=$(shasum -a 256 "$PACKAGE_DIR/$ARCHIVE" | cut -d ' ' -f 1)
tar -czf "$PACKAGE_DIR/deploy-tools.tar.gz" \
  tools/__init__.py tools/deployment/__init__.py tools/deployment/common.py \
  tools/deployment/package_release.py tools/deployment/install_release.py tools/deployment/health_check.py
REMOTE_DIR="/srv/morrowind-map/incoming-ci/recovery-$RUN_ID"
ssh deploy-admin "install -d -o morrowind-map -g morrowind-map -m 750 '$REMOTE_DIR'"
scp "$PACKAGE_DIR/$ARCHIVE" "$PACKAGE_DIR/deploy-tools.tar.gz" "deploy-admin:$REMOTE_DIR/"
ssh deploy-admin "chown morrowind-map:morrowind-map '$REMOTE_DIR/$ARCHIVE' '$REMOTE_DIR/deploy-tools.tar.gz'"
ssh deploy-admin "runuser -u morrowind-map -- sh -c 'cd $REMOTE_DIR && tar -xzf deploy-tools.tar.gz && \
  python3 -m tools.deployment.install_release --archive $ARCHIVE --archive-sha256 $ARCHIVE_SHA \
  --commit-sha $COMMIT_SHA --dataset-graph $DATASET_GRAPH --check-only'"
```

After a successful `validated` result, activate the same package with both health checks:

```bash
ssh deploy-admin "runuser -u morrowind-map -- sh -c 'cd $REMOTE_DIR && \
  python3 -m tools.deployment.install_release --archive $ARCHIVE --archive-sha256 $ARCHIVE_SHA \
  --commit-sha $COMMIT_SHA --dataset-graph $DATASET_GRAPH --health-url http://127.0.0.1:9003/ --health-url https://morrowindmap.com/'"
```

The installer uses the same locking, validation, and automatic rollback as CI.
After checking the result, remove only this operation's temporary directories:
`ssh deploy-admin "rm -rf -- '$REMOTE_DIR'"` and `rm -rf -- "$PACKAGE_DIR"`.

If the old commit predates the committed plan, obtain `DATASET_GRAPH` from the pinned
target of `/srv/morrowind-map/releases/$COMMIT_SHA/datasets/generated`. Verify its
64-character SHA and that the graph matches that release's manifests. If a legacy
release lacks the link, restore its mapping with the migration procedure first;
do not assign a new graph based on the name `data/generated`.

If `current` points to a damaged or missing release, the installer refuses to use it
as fallback. Restore its application files/data first. If that is impossible, with
deployments paused, an administrator may remove **only the current symlink** under
`.app-deploy.lock` and retry as a first installation. Do not delete release/data
directories to bypass validation.

If the artifact has expired, rebuild the chosen commit in a separate clean checkout:
`pnpm install --frozen-lockfile`, `pnpm exec playwright install chromium`, `pnpm verify`,
and `pnpm deploy:package --skip-build --commit-sha "$(git rev-parse HEAD)"`.
This produces a newly verified package, not a byte-for-byte recovery of the former
CI artifact. Use the same installer with the selected commit's graph. Restore missing
generated files from that commit's Git/LFS data using the stage-only uploader.
If an old payload was never published to Git/LFS, recovery needs retained local data
or a fresh renderer/catalog pipeline using your own inputs.

After VPS loss, restore in this order: access and directories → data → nginx and
tunnel → application → health checks. The repository contains active prepared data
(WebP through LFS), but no server backups, game inputs, SSH private keys, or Cloudflare
credentials. No automatic backup is configured. Application and graph releases are
retained without automatic pruning. Future garbage collection must preserve every
graph referenced by a retained application release. Directories on one VPS do not
protect against losing that server.
