# Repository working rules

## Language

- Keep application copy, documentation, comments, contributor templates, and other repository-authored prose in English.
- Write commit subjects and bodies, branch names, pull request titles and descriptions, and release notes in English. Use concise Conventional Commit subjects such as `fix: preserve the selected place after retry` or `docs: clarify dataset review`.
- Preserve upstream names, licenses, identifiers, and deliberate multilingual test fixtures. English-only product copy does not mean stripping Unicode support or translating source data.
- Conversation with the maintainer may use their preferred language; repository content remains English.

## Branches and pull requests

- Start every change from the latest `origin/main` on a short-lived topic branch: `feature/<description>`, `fix/<description>`, `docs/<description>`, `refactor/<description>`, `test/<description>`, or `chore/<description>`.
- Open a pull request directly into `main`, including for documentation and maintenance changes. The old `dev` branch is no longer an integration or release branch.
- Do not commit or push directly to `main`, force-push `main`, or bypass required checks. Keep unrelated work out of the branch.
- Review the final diff and run `pnpm verify` before committing. Follow [CONTRIBUTING.md](CONTRIBUTING.md) for additional dataset checks and trusted review.
- Create the PR and report its checks. Merge only when the maintainer has authorized that PR or an explicitly scoped merge operation and all applicable gates pass. A previous PR's merge authorization does not automatically authorize later PRs.
- Use a GitHub merge commit for the PR. Production publication runs through Actions from `main` using its verified artifact.
- Branch protection is enabled for `main`, including administrators. Verify any settings changes through GitHub; see the applied configuration in [CONTRIBUTING.md](CONTRIBUTING.md).

## Data and product boundaries

- Keep the repository private until the maintainer explicitly authorizes a visibility change.
- Keep private host aliases, origin IP addresses, credentials, and local account paths out of repository content. Deployment uses GitHub environment secrets; local rerender inputs belong in ignored `local-data/inputs/`.
- Never add game source files or archives to Git or LFS: ESM/ESP, BSA/BA2, DDS/NIF, related original assets, local inputs, renderer checkpoints, and intermediate renders stay local.
- Publish only the validated active dataset graph. Ready generated WebP tiles use Git LFS; runtime JSON and metadata use regular Git. Use `pnpm datasets:stage` instead of broadly force-adding ignored directories.
- Dataset and deployment changes must follow [docs/DATASET_CONTRIBUTING.md](docs/DATASET_CONTRIBUTING.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Never expose production secrets to PR code.
- Preserve the current interface and interaction design unless the requested change calls for a product change. Update relevant documentation when behavior or workflows change.
