# Morrowind Map

Five interactive maps for The Elder Scrolls III: Morrowind, available at [morrowindmap.com](https://morrowindmap.com/).

| Map | Coverage |
| --- | --- |
| Original GOTY HD | Vvardenfell and Solstheim from Morrowind, Tribunal, and Bloodmoon |
| Tamriel Rebuilt | The base game and TR Mainland; currently 26.08 Poison Song |
| Project Cyrodiil | Abecean Shores 25.05a |
| Skyrim: Home of the Nords | Dragonstar 25.05; the Reach, including Dragonstar, Karthwasten and Karthgad |
| Lyithdonea | The Azurian Isles 0.3.1 |

Search places, filter locations, share map links, and keep progress, notes, and personal markers. Mod titles in the map header link to their Nexus Mods pages in a new tab. Personal data stays in your browser; use JSON export/import to transfer it or keep a backup. Records are associated with a specific map version.

## Requirements

Local development, dataset preparation, and builds currently require a Unix-like
environment: Linux or macOS with a POSIX-compatible shell. CI runs on Linux.

- Node.js `^20.19.0` or `>=22.12.0` (CI uses Node.js 24).
- pnpm `11.19.0`.
- Python 3.10+ available as `python3` in the same shell as `node` and `pnpm`.
- Network access for dependencies and map archives, plus disk space for about
  2.8 GB of extracted maps, downloaded archives, and a separate production build.

**Native Windows build support is in development and is not currently available.**
The commands below assume a Unix environment; the dataset tools use Unix-only
Python file locking (`fcntl`). Installing Git Bash alone does not provide this
Python support. These restrictions apply to local tooling; the hosted website
can be used from a Windows browser.

## Run locally

After installing the requirements above, run these commands from your clone or
extracted source ZIP:

```bash
pnpm install --frozen-lockfile
pnpm datasets:download
pnpm dev
```

Open `http://127.0.0.1:5173`. The downloader restores all five maps, approximately 2.8 GB of ready tiles, from the immutable product release selected by `config/dataset-releases.lock.json`. It uses the Python standard library; no Git LFS, game installation, Docker, or OpenMW is needed. `pnpm dev` does not download missing maps.

Public releases can be downloaded without a GitHub account, token, or `gh`: use `pnpm datasets:download --anonymous` to explicitly disable credential lookup. Downloads verify hashes, reuse complete maps and cached archives, and can safely be retried; `--discard-cache` removes verified archives after extraction to save disk space.

For a private repository or private source release, authenticate with an existing `gh auth login` session or provide `GH_TOKEN` / `GITHUB_TOKEN` in the environment with repository Contents read access. Anonymous access works only when the source repository and release are public. Do not put tokens in commands or files.

## Build

```bash
pnpm build
pnpm preview
```

The static application is written to `apps/web/dist`. Keep its `datasets/` directory and assets together when serving the build. Run `pnpm datasets:download` before building to include the complete prepared maps. Hosting configuration is up to you.

## Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for a short guide. Use English and submit focused pull requests into `main`.

```bash
pnpm check
```

This checks types, lint, application tests, and the build. CI runs the broader integration and visual checks. You do not need to run a renderer for an application change.

## Rebuild a map

Ready WebP tiles are distributed as map archives in GitHub Releases; runtime JSON, metadata, the transport lock and upload plan use regular Git. Game files, textures, meshes, and intermediate renders must never be committed.

Supply your own matching inputs in ignored `local-data/inputs/`, then use:

```bash
pnpm render:check all
pnpm render:smoke all
pnpm render:all
# Or: pnpm render:original / pnpm render:tamriel-rebuilt
#     pnpm render:project-cyrodiil / pnpm render:home-of-nords
#     pnpm render:azurian-isles
```

Lyithdonea requires OAAB Data in addition to GOTY and Tamriel Data.

Rendering needs Python 3.10+, Docker with Linux AMD64 support, and ImageMagick. Full renders can take hours. The workflow produces a candidate for local preview before you adopt or contribute it.

- [Rendering](docs/RENDERING.md): input layout, commands, settings, and preview.
- [TR release profiles](docs/TR_UPDATE.md): preparing a new Tamriel Rebuilt version.
- [Dataset contributions](docs/DATASET_CONTRIBUTING.md): contributing prepared map packages and metadata.
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
