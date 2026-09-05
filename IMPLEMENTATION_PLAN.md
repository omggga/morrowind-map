# Implementation status

This document records the state of the current product. Technical contracts live in the topic-specific documents linked from [README.md](README.md).

## Readiness

| Area | Status |
| --- | --- |
| Web runtime | Complete: landing page, two maps, search, filters, labels, deep links, Back/Forward, and loading/error/empty/retry handling |
| Original GOTY HD | Stable published snapshot; local rerenders use the six pinned inputs, optional visual settings, and a new snapshot, with adoption only after review |
| Tamriel Rebuilt | The active release, 26.08 Poison Song, is ready; subsequent releases use the shared profile/lock workflow with a new dataset identity |
| Local user data | Complete: independent progress, notes, personal markers, snapshot binding, and JSON backup/import |
| UI | Complete: desktop, narrow portrait, landscape, touch, keyboard, focus, ARIA semantics, and an automated axe gate |
| Verification | `pnpm verify` covers types, lint, unit/Python suites, browser acceptance, visual tests, and the production build |
| Prepared datasets | Active WebP tiles are in Git LFS; generated JSON and metadata are in Git. Dataset changes receive complete plan validation and prepared browser acceptance in CI |
| Local render tooling | Shared input layout and check/build/smoke/full commands reuse both pipelines; full renders create isolated, browser-validated candidates with explicit local adoption |
| TR release tooling | Profile/lock workflow retains source hashes and dependency checks, derives a new identity, and validates every render/catalog stage before candidate assembly |
| Dataset contributions | PRs carry prepared files and a publication plan; a trusted Actions workflow produces HTML/JSON review artifacts without executing candidate code or exposing deployment credentials |
| Deployment | Actions publishes the verified `main` artifact to the production server, checks the dataset graph before activation, runs health checks, and restores the previous application/data pair on health failure |
| Repository workflow | English documentation and change metadata; topic branches and PRs into `main`. See [CONTRIBUTING.md](CONTRIBUTING.md) for enforcement details |

## Routine work

The shared workflow supports a current-map rerender or a new TR release:

1. Prepare complete inputs in ignored `local-data/inputs` using [the render guide](docs/RENDERING.md).
2. For a new TR release, create a separate profile with a new dataset ID and updated input contract; the snapshot is derived automatically.
3. Run `render:check`, smoke checks, and `render:original`, `render:tamriel-rebuilt`, or `render:all`.
4. Inspect the isolated candidate using `render:preview`; explicitly adopt a validated result with `render:use`.
5. Run `pnpm verify`, stage only the validated active graph plus explicit contracts, and open a topic-branch PR.
6. Complete CI and trusted dataset review for the current PR head, then merge the reviewed change into protected `main`.
7. Let Actions publish that verified commit and check the resulting site.

Each published payload remains content-addressed and immutable. An update creates a new package and changes the active reference rather than overwriting existing files. Ordinary application changes follow the same branch/PR workflow without rerendering or downloading unchanged datasets.

## Boundaries and remaining work

- Original rerenders retain pinned base hashes and tile geometry. Visual/producer changes derive a new snapshot; they never silently overwrite the published identity.
- The canonical TR dataset must not include undeclared plugins or partial asset trees.
- Game source files and intermediate renderer outputs must never be committed. Prepared active WebP renders belong in Git LFS; runtime JSON and metadata belong in regular Git.
- A renderer or quality-setting change requires fresh smoke and complete release checks. The shared facade builds/reuses matching images automatically.
- An incomplete render or a failed candidate gate must not change the active dataset. Smoke success alone does not establish full-render readiness.
- Project Cyrodiil, Home of the Nords, and Azurian Islands remain future additions. The current runtime index and verification contract expose two maps; adding another requires its own source profile, identity, prepared artifacts, and coverage of the expanded map list.
- The repository remains private. A public/open-source release requires an explicit decision, licensing/redistribution review, and the [history and access review](docs/DEPLOYMENT.md#access). Current-tree cleanup does not remove infrastructure references from earlier Git/PR revisions.
- Deployment retains previous immutable releases for rollback; there is no separate automated backup process.

## Repository readiness criterion

The repository is ready when `pnpm verify` passes, manifests reference only existing content-addressed packages, and the dataset index contains Original GOTY HD plus one active Tamriel Rebuilt release. With the prepared dataset bytes available, `pnpm test:acceptance:prepared` must also pass. Dataset changes must match the committed publication plan and pass trusted PR review before Actions can deploy them.
