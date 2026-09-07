# Morrowind Map

An English-language interactive map of Morrowind, available at [morrowindmap.com](https://morrowindmap.com/).

| Map | Coverage |
| --- | --- |
| Original GOTY HD | Vvardenfell and Solstheim from Morrowind, Tribunal, and Bloodmoon |
| Tamriel Rebuilt | The base game and TR Mainland; currently 26.08 Poison Song |
| Project Cyrodiil | Abecean Shores; the local render workflow is prepared, initial tiles pending |

Search places, filter locations, share map links, and keep progress, notes, and personal markers. Personal data stays in your browser; use JSON export/import to transfer it or keep a backup. Records are associated with a specific map version.

## Run locally

Install Node.js `^20.19.0` or `>=22.12.0`, pnpm `11.19.0`, and Git LFS. From your clone:

```bash
git lfs install
git lfs pull --include='apps/web/public/datasets/generated/**/*.webp' --exclude=''
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://127.0.0.1:5173`. The prepared maps need no game installation, Docker, or OpenMW. Git LFS downloads approximately 2.3 GB of ready map tiles.

## Build

```bash
pnpm build
pnpm preview
```

The static application is written to `apps/web/dist`. Keep its `datasets/` directory and assets together when serving the build. Download the LFS payload before building to include real tiles rather than pointer files. Hosting configuration is up to you.

## Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for a short guide. Use English and submit focused pull requests into `main`.

```bash
pnpm check
```

This checks types, lint, application tests, and the build. CI runs the broader integration and visual checks. You do not need to run a renderer for an application change.

## Rebuild a map

Ready WebP tiles use Git LFS; runtime JSON and metadata use regular Git. Game files, textures, meshes, and intermediate renders must never be committed.

Supply your own matching inputs in ignored `local-data/inputs/`, then use:

```bash
pnpm render:check all
pnpm render:smoke all
pnpm render:all
# Or: pnpm render:original / pnpm render:tamriel-rebuilt / pnpm render:project-cyrodiil
```

Rendering needs Python 3.10+, Docker with Linux AMD64 support, and ImageMagick. Full renders can take hours. The workflow produces a candidate for local preview before you adopt or contribute it.

- [Rendering](docs/RENDERING.md): input layout, commands, settings, and preview.
- [TR release profiles](docs/TR_UPDATE.md): preparing a new Tamriel Rebuilt version.
- [Dataset contributions](docs/DATASET_CONTRIBUTING.md): contributing ready maps through Git/LFS.
- [Architecture](docs/ARCHITECTURE.md): runtime, data formats, and browser storage.
- [Testing](docs/TESTING.md): choosing checks for your change.
- [Third-party notices](THIRD_PARTY_NOTICES.md).

## License

Original project code and documentation are source-available under the
[PolyForm Noncommercial License 1.0.0](LICENSE). You may use, modify and
redistribute them for purposes permitted by that license. Commercial products
and services based on this code require separate permission from the relevant
rights holders; the license is not an OSI-approved open-source license.

Required Notice: Copyright (c) 2026 Morrowind Map contributors.

This license does not cover third-party components or underlying game and mod
content, including content depicted in generated maps. Their respective rights
and licenses remain in effect; see [Third-party notices](THIRD_PARTY_NOTICES.md).
