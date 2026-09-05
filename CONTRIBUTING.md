# Contributing

Morrowind Map is currently a private repository. All changes reach `main` through a pull request, including changes made by the maintainer. Production publication runs through GitHub Actions after a successful `main` build.

## English repository content

Use English for application copy, documentation, code comments, commit messages, branch names, pull requests, and release notes. Preserve upstream names, license text, data identifiers, and intentional Unicode test fixtures. This policy applies to new work and current documentation; it does not rewrite existing Git history.

Use a Conventional Commit subject with a clear English description:

- `feat: add a dataset selector`
- `fix: preserve search after a failed request`
- `docs: explain dataset publication`
- `chore: update development dependencies`

PR titles follow the same convention. Explain the problem, the resulting behavior, and the checks performed in the PR body. Use the repository's pull request template.

## Start a topic branch

Start with a clean working tree and fetch the current default branch:

```bash
git fetch origin
git switch -c feature/short-description origin/main
```

Choose a prefix that describes the work: `feature/`, `fix/`, `docs/`, `refactor/`, `test/`, or `chore/`. For example, use `fix/search-retry` for a fix or `docs/deployment-guide` for documentation. Use lowercase English words separated by hyphens.

The previous `dev` branch is no longer an integration branch. Create each new branch from `origin/main` and target `main` directly. Do not push directly to `main` or combine unrelated changes in one PR.

## Verify and open a PR

Follow [README.md](README.md) for setup and [docs/TESTING.md](docs/TESTING.md) for the test boundaries. Review the diff and stage only the intended files:

```bash
git diff --check
pnpm verify
git add -- <changed-paths>
git diff --cached --stat
git diff --cached
git commit -m "fix: describe the resulting behavior"
git push -u origin HEAD
gh pr create --base main --title "fix: describe the resulting behavior" --body-file /absolute/path/to/pr-body.md
```

The placeholders must be replaced with the actual paths and description. Keep PR body files outside the repository or leave them untracked. The initial push sets the topic branch's upstream explicitly.

For local game inputs and rerender commands, follow [docs/RENDERING.md](docs/RENDERING.md). Keep inputs in ignored `local-data/inputs/` and review candidates before applying them with `pnpm render:use`. CI runs on pull requests and pushes to `main`; topic branch pushes do not start a second CI run.

Ready dataset changes also require plan validation, prepared browser acceptance, and a trusted report for the current PR head. Follow [docs/DATASET_CONTRIBUTING.md](docs/DATASET_CONTRIBUTING.md). Never commit game source inputs or intermediate renders. Contributors supply the reviewable result through Git/LFS and do not need access to the production host.

## Review, merge, and publish

Review the exact final diff and the PR CI results before merging. If `main` has advanced, merge `origin/main` into the topic branch, push it, and wait for fresh checks. A new PR head requires a new trusted dataset report when that gate applies.

The maintainer authorizes the merge after reviewing the result. Agents may prepare and open a PR within the requested work; they must not treat approval of an earlier PR as approval to merge a later one. Use GitHub's **Create a merge commit** option so the release remains linked to the reviewed PR. Do not bypass failed checks or publish directly from a topic branch.

After merge, CI packages that exact `main` commit and Actions publishes its verified artifact. Dataset changes must have a successful SHA-bound trusted review. Publication validates the selected dataset graph, switches `current` atomically, checks origin and public health, and restores the previous release if the health check fails. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Main branch protection

Branch protection for `main` was enabled and verified through the GitHub API on 2026-09-05 after the account upgraded to GitHub Pro. The repository remains private. GitHub now enforces the PR and required-check rules for administrators as well as other contributors. See [GitHub's protected branch documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

The applied settings are recorded in [.github/main-branch-protection.json](.github/main-branch-protection.json):

- Require a PR, including for administrators; disable force pushes and branch deletion.
- Require the branch to be up to date and both CI jobs to pass: `Install, typecheck, lint, unit, browser acceptance, UI, build` and `Validate prepared datasets`. A dataset job skipped for a change that does not affect datasets is acceptable.
- Require review conversations to be resolved.
- Require zero additional approving reviewers while the maintainer is the only reviewer and contributions are created through the same account. The maintainer still reviews the PR and authorizes the merge. Requiring self-approval would prevent that workflow; increase this setting when an independent reviewer joins.

The manually dispatched `Dataset review (trusted)` check is conditional, so it is not a global required check for documentation-only or application-only PRs. Maintainers review its report before merging applicable changes, and the deployment gate independently verifies its provenance.

A repository administrator can restore these settings and read back the configuration:

```bash
gh api --method PUT repos/omggga/morrowind-map/branches/main/protection \
  --input .github/main-branch-protection.json
gh api repos/omggga/morrowind-map/branches/main/protection
```

Confirm the returned rules after any settings change. If required-check names change, update both this configuration and the live protection settings. Never disable protection or change repository visibility to bypass a failed check.
