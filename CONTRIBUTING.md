# Contributing

Issues, bug reports, map corrections, and focused pull requests are welcome. Describe what you expected, what happened, and how to reproduce it. For a visual problem, include a screenshot and the map URL. Discuss large changes before doing substantial work.

## Make a change

1. Follow the setup in [README.md](README.md).
2. Create a branch from current `main`, for example `fix/search-retry` or `feature/place-filter`.
3. Make a focused change. Use English for application copy, documentation, commit messages, and PR text. Preserve upstream names and intentional Unicode data.
4. Run checks relevant to the change, then open a PR into `main`. Explain the result and how you checked it.

For ordinary application changes:

```bash
pnpm check
```

For documentation-only changes, review the text, links, and `git diff --check`. CI runs the full repository checks on PRs. You can reproduce them locally with `pnpm verify`; [docs/TESTING.md](docs/TESTING.md) lists focused commands.

Add a regression test when fixing behavior that could break again. Prefer a user-visible result or a stable data contract. Small copy, style, and documentation changes do not need a new test for every detail. Do not add tests just to assert an implementation constant or reach a coverage percentage.

Keep map coordinates, data integrity, personal-data persistence, accessibility, and the established visual experience intact. Include screenshots for intentional UI changes; update visual baselines only after inspecting them.

## Contribute a map

Use [docs/RENDERING.md](docs/RENDERING.md) to build locally and [docs/DATASET_CONTRIBUTING.md](docs/DATASET_CONTRIBUTING.md) to submit prepared files. You need no access to the hosted site's server.

Never commit game source files, archives, meshes, textures, credentials, intermediate renders, or generated WebP tiles. A dataset PR contains runtime JSON, relevant metadata, `config/dataset-releases.lock.json` and the validated upload plan. Publish prepared TAR packages to a source release readable by trusted review; a maintainer promotes the verified complete bundle into the canonical product release. Use `pnpm datasets:stage` after packaging to stage only the active JSON, lock and plan while preserving local tiles.

Maintainers review the final diff and CI results before merging. Dataset changes also receive a review report for the exact PR commit. Keep unrelated changes out of the PR and resolve review feedback before merge.

For changes to datasets, deployment tools or their workflows, maintainers must
dispatch `Dataset review (trusted)` from `main` and wait for its successful result
on the exact PR head and base before merging. Ordinary CI does not replace this
review. A changed head or base needs a fresh review. Contributors provide prepared
packages through their own published source releases; they do not need server
credentials or permission to publish canonical releases.

## Licensing contributions

Submit original code and documentation under the same
[PolyForm Noncommercial License 1.0.0](LICENSE), and only contribute material you
have the right to submit. Preserve existing third-party notices and licenses.
Dataset contributions must respect the rights in their underlying game and mod
content; the project license does not relicense that content.
