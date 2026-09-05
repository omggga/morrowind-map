# Implementation status

This document records the state of the current product. Technical contracts live in the topic-specific documents linked from [README.md](README.md).

## Readiness

| Area | Status |
| --- | --- |
| Web runtime | Complete: landing page, two maps, search, filters, labels, deep links, Back/Forward, and loading/error/empty/retry handling |
| Original GOTY HD | Complete and frozen; renderer inputs, tile pyramid, catalog, and manifest are excluded from future update cycles |
| Tamriel Rebuilt | The active release, 26.08 Poison Song, is ready; subsequent releases use the shared profile/lock workflow with a new dataset identity |
| Local user data | Complete: independent progress, notes, personal markers, snapshot binding, and JSON backup/import |
| UI | Complete: desktop, narrow portrait, landscape, touch, keyboard, focus, ARIA semantics, and an automated axe gate |
| Verification | `pnpm verify` covers types, lint, unit/Python suites, browser acceptance, visual tests, and the production build |
| Prepared datasets | Active WebP tiles are in Git LFS; generated JSON and metadata are in Git. Dataset changes receive complete plan validation and prepared browser acceptance in CI |
| TR release tooling | Reusable: one orchestrator performs input checks, locking, rendering, auditing, catalog generation, manifest generation, verification, and internal atomic activation |
| Dataset contributions | PRs carry prepared files and a publication plan; a trusted Actions workflow produces HTML/JSON review artifacts without executing candidate code or exposing deployment credentials |
| Deployment | Actions publishes the verified `main` artifact to vpsdo, checks the dataset graph before activation, runs health checks, and restores the previous application/data pair on health failure |
| Repository workflow | English documentation and change metadata; topic branches and PRs into `main`. See [CONTRIBUTING.md](CONTRIBUTING.md) for enforcement details |

## Routine work

The existing dataset release workflow handles new Tamriel Rebuilt releases:

1. Prepare matching Tamriel Data and TR Core inputs locally.
2. Assign a new `datasetId` and a new `snapshotId`.
3. Run `pnpm data:tr:release` using the [TR update runbook](docs/TR_UPDATE.md).
4. Allow the orchestrator to switch the active local dataset only after every check passes.
5. Stage the validated active graph with `pnpm datasets:stage` on a topic branch and open a PR.
6. Complete CI and the trusted dataset review for the current PR head, then merge the reviewed change into `main`.
7. Let Actions publish that commit and verify the resulting site.

Each published payload remains content-addressed and immutable. An update creates a new package and changes the active reference rather than overwriting existing files. Ordinary application changes follow the same branch/PR workflow without rerendering or downloading unchanged datasets.

## Boundaries and remaining work

- Original GOTY HD is not updated and is not used as a release-identity template for TR.
- The canonical TR dataset must not include undeclared plugins or partial asset trees.
- Game source files and intermediate renderer outputs must never be committed. Prepared active WebP renders belong in Git LFS; runtime JSON and metadata belong in regular Git.
- A renderer image or quality-setting change requires a separate toolchain review; an ordinary TR content update does not rebuild the renderer image.
- An incomplete release or a failed gate must not change the active dataset.
- Project Cyrodiil, Home of the Nords, and Azurian Islands remain future additions. The current runtime index and verification contract expose two maps; adding another requires its own source profile, identity, prepared artifacts, and coverage of the expanded map list.
- The repository remains private. A public/open-source release is a separate future decision, including a review of licensing and redistribution terms.
- Deployment retains previous immutable releases for rollback; there is no separate automated backup process.

## Repository readiness criterion

The repository is ready when `pnpm verify` passes, manifests reference only existing content-addressed packages, and the dataset index contains Original GOTY HD plus one active Tamriel Rebuilt release. With the prepared dataset bytes available, `pnpm test:acceptance:prepared` must also pass. Dataset changes must match the committed publication plan and pass trusted PR review before Actions can deploy them.
