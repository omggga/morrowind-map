# Architecture

## System components

Morrowind Map has three core parts:

1. A React/Vite web runtime loads the dataset index, manifest, catalog, and sparse WebP tile pyramid.
2. Python tooling extracts the TES3 catalog and builds the basemap with a pinned headless OpenMW renderer.
3. Browser storage keeps user progress separate from the read-only game datasets.

Map data, fonts, icons, manifests, and runtime artifacts are served from the same origin. Optional analytics load only after consent. The application and repository prose use English; contribution conventions are defined in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Dataset contract

`apps/web/public/datasets/index.json` lists prepared maps in this order:

- `original-goty-hd`;
- one active versioned Tamriel Rebuilt dataset;
- one active versioned Project Cyrodiil dataset;
- one active versioned Home of the Nords dataset;
- one active versioned Lyithdonea dataset.

The index contains only identity, ordering, and the manifest URL. Each manifest defines:

- `datasetId`, `snapshotId`, title, and release metadata;
- the exact source profile and load order;
- the TES3 world projection, extent, origin, and resolutions;
- content-addressed references and hashes for the catalog, locale, tile metadata, and audit;
- readiness and available regions.

The loader validates JSON schemas, identity, and cross-references before opening a map. Index, manifest, catalog, coverage, and tile-metadata errors are not disguised as empty states.

## Maps

### Original GOTY HD

Original uses its own profile and producer modules. Its inputs are limited to the three English ESM files and the three matching BSA files. The dataset is frozen: routine work on a new Tamriel Rebuilt release does not run the Original renderer, catalog pipeline, or publisher, and does not change its manifest.

### Tamriel Rebuilt

The active TR map is built from the same six base inputs and a matching Tamriel Data / TR Core pair. Release-specific identity and hashes live in the release config and generated lock. Each new release receives a new `datasetId` and `snapshotId`; see [TR_UPDATE.md](TR_UPDATE.md) for the full process.

### Project Cyrodiil

Cyrodiil uses the same OpenMW renderer, tile geometry, presentation, seam audits and
release adapter as TR. `config/pc-release.json` supplies its version, load order,
source hashes and smoke controls. GOTY and Tamriel Data remain loaded dependencies;
LAND coverage and the published location catalog are restricted to Cyrodiil.
A single-map update preserves every other active map and its artifacts.
The landing page reads the prepared manifest and opens Cyrodiil as its third choice.

### Skyrim: Home of the Nords

Home of the Nords uses the shared province release workflow with
`config/shotn-release.json`. Its `Sky_Main.esm` defines the LAND extent, the `skyrim`
region limits the published catalog, and `shotn:` identifies its snapshots. GOTY
and Tamriel Data supply dependencies; grass, TR and Cyrodiil plugins are excluded.
The candidate adds or replaces the fourth map while retaining every other active
map and its immutable artifacts.

### Lyithdonea: The Azurian Isles

The `azurian-isles` map uses `config/az-release.json`, the shared province workflow,
and an additional OAAB Data dependency. Its `az:` snapshots contain only
`MD_Azurian Isles.esm` LAND and locations on that LAND. The contract accepts five
maps; a Lyithdonea addition or update preserves every other active map. Its fifth
landing choice opens the prepared Lyithdonea manifest.

## Basemap and catalog

The basemap is a sparse lossless WebP pyramid, `z0…z7`, with a native tile size of `512×512`. The manifest declares a top-left XYZ grid and coverage, so coordinates outside that coverage do not generate unnecessary HTTP requests. Presentation is already baked into the output by the producer; the runtime must not alter color or alpha again.

The catalog merges TES3 records according to load-order semantics, including overrides and deletions. The runtime receives:

- stable place identifiers and world coordinates;
- entrances and teleport destinations;
- region/type metadata;
- an English locale;
- an audit bound to the same `datasetId` and `snapshotId`.

The basemap and catalog are published independently, but a manifest must not mix artifacts from different release identities.

## Content-addressed publication

Generated artifacts are published into a directory named from their inventory hash. A completed package is never overwritten. A candidate manifest is assembled from publication metadata read back from disk, then validated against the schemas and files.

Local activation is the final atomic operation in the release workflow. Until then, the active index and manifest continue to reference the previous complete dataset. A producer or gate failure leaves the active map unchanged.

Prepared active WebP tiles stay outside Git and are distributed through immutable GitHub Releases. The schema-version-2 `config/dataset-releases.lock.json` pins all five maps to one product release, initially `v1.0.0`, with a short TAR asset name and hash for each map. Runtime JSON catalogs/locales, metadata, the transport lock and upload plan use regular Git. Game inputs and intermediate renderer outputs stay local. `pnpm datasets:stage` validates the complete active graph and lock, stages only reachable generated JSON plus the lock and `config/dataset-upload-plan.json`, and removes tracked generated WebP while preserving local files.

`pnpm datasets:download` restores the complete map selection from the committed lock without resolving Latest. Each archive and tile is verified before a map is installed; unchanged complete maps and SHA-256 cache entries are reused. A new product bundle includes all maps while reusing unchanged TAR bytes. The transport version is independent of runtime dataset identities and does not itself change browser user-data binding.

Changes enter `main` through topic-branch PRs. CI validates the Git source boundary and application; dataset changes also restore the pinned Release packages, verify the recorded plan, and run prepared browser acceptance for all maps. Application-only CI does not download tiles. A manually dispatched trusted workflow exports candidate and base metadata as data, without executing candidate code, and binds its review to the exact PR head/base SHAs, transport locks and complete graphs. Only its separate protected publication job can promote verified packages into the canonical release. Every reviewed snapshot requires its own valid Release lock and upload plan. Lockless snapshots from before the Release migration are unsupported; current tools contain no LFS restore path.


## Browser state

The URL stores `dataset`, `region`, `x`, `y`, `z`, and the selected `place`. Input parameters are validated and canonicalized; Back/Forward restores meaningful navigation state without adding history entries for every pan or zoom.

Entering a map from the landing page without an explicit camera uses `map.projection.center` from the manifest. Original and TR open at `z=3`; Cyrodiil, Home of the Nords and Lyithdonea open at `z=4`. The selected `tr-mainland` region opens at Old Ebonheart at `z=4`. Explicit valid `x/y/z` URL coordinates always take precedence over defaults or region focus.

Region, type, status, and zoom-tier filters apply to the full catalog. The results list appends DOM rows in batches as the user scrolls; search, facet counts, map markers, and the total number of matches use the full filtered set, not just the rendered batch.

Dataset and catalog loading have explicit loading, missing, invalid, network-error, partial-failure, and retry states. Routine tile loading shows no status text, spinner, or overlay over the map. Missing coverage, tile errors, and retry remain visible recovery states. Abort/generation guards prevent a late response from an old request from replacing newer state. Tile retry requests only the current failed set and does not recreate the map, camera, filters, or selection.

## User data

IndexedDB stores progress, notes, and personal markers separately from read-only dataset files. Every record belongs to a `datasetId`; its binding also checks `snapshotId`.

A new map release must receive both new identities. This prevents coordinates and records from different snapshots from being mixed. Old records are neither deleted nor migrated automatically; they remain bound to the previous dataset. JSON export/import is validated before an atomic write and does not alter game artifacts.

If IndexedDB is unavailable, the map remains usable in read-only mode. A local-write failure preserves the draft and offers a retry without resetting the camera or selected place.
