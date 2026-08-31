import {
  parseLocationCatalog,
  parseMapAssetsManifest,
  parsePlaceLocaleCatalog,
  parseTileCoverage,
  type DatasetManifest,
  type LocationCatalog,
  type Locale,
  type MapAssetsManifest,
  type PlaceLocaleCatalog,
  type PlaceLocaleRecord,
  type TileCoverage,
  type TilePyramid,
} from '@morrowind-map/contracts';

export class DatasetAssetsMissingError extends Error {
  override readonly name = 'DatasetAssetsMissingError';
}

export interface DatasetBundle {
  readonly locations: LocationCatalog;
  readonly locales: ReadonlyMap<Locale, PlaceLocaleCatalog>;
  readonly mapAssets: MapAssetsManifest;
  readonly tileCoverages: ReadonlyMap<string, TileCoverage>;
}

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal,
  });
  if (!response.ok) {
    throw new Error(`Could not load ${url} (HTTP ${response.status})`);
  }
  return response.json() as Promise<unknown>;
}

function requireArtifactUrl(
  manifest: DatasetManifest,
  url: string | undefined,
  label: string,
): string {
  if (!url) {
    throw new DatasetAssetsMissingError(`Dataset ${manifest.datasetId} does not contain ${label}`);
  }
  return url;
}

function assertIdentity(
  manifest: DatasetManifest,
  artifact: { readonly datasetId: string; readonly snapshotId: string },
  label: string,
): void {
  if (artifact.datasetId !== manifest.datasetId || artifact.snapshotId !== manifest.snapshotId) {
    throw new Error(`${label} belongs to a different dataset snapshot`);
  }
}

function assertLocaleCoverage(
  locations: LocationCatalog,
  localeCatalog: PlaceLocaleCatalog,
): void {
  const structuralIds = new Set(locations.places.map(({ id }) => id));
  const localeIds = new Set(localeCatalog.places.map(({ placeId }) => placeId));
  if (
    structuralIds.size !== localeIds.size ||
    [...structuralIds].some((placeId) => !localeIds.has(placeId))
  ) {
    throw new Error(`Locale ${localeCatalog.locale} does not cover the complete location catalog`);
  }
}

function arraysEqual<T>(left: readonly T[], right: readonly T[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function assertPyramidGrid(manifest: DatasetManifest, pyramid: TilePyramid): void {
  const availableRegions = new Set(
    manifest.regions
      .filter(({ kind, status }) => kind === 'exterior' && status === 'available')
      .map(({ id }) => id),
  );
  const grid = manifest.map.tileGrid;
  const [worldMinX, worldMinY, worldMaxX, worldMaxY] = manifest.map.projection.extent;
  const [minX, minY, maxX, maxY] = pyramid.extent;

  if (minX < worldMinX || minY < worldMinY || maxX > worldMaxX || maxY > worldMaxY) {
    throw new Error(`Tile pyramid ${pyramid.id} extent exceeds the dataset manifest`);
  }
  if (!arraysEqual(pyramid.origin, grid.origin)) {
    throw new Error(`Tile pyramid ${pyramid.id} origin does not match the dataset manifest`);
  }
  if (!arraysEqual(pyramid.resolutions, grid.resolutions)) {
    throw new Error(`Tile pyramid ${pyramid.id} resolutions do not match the dataset manifest`);
  }
  if (pyramid.tileSize !== grid.tileSize) {
    throw new Error(`Tile pyramid ${pyramid.id} tileSize does not match the dataset manifest`);
  }
  const unknownRegions = pyramid.regionIds.filter((regionId) => !availableRegions.has(regionId));
  if (unknownRegions.length > 0) {
    throw new Error(
      `Tile pyramid ${pyramid.id} contains unknown regionIds: ${unknownRegions.join(', ')}`,
    );
  }
}

async function loadLocales(
  manifest: DatasetManifest,
  locations: LocationCatalog,
  signal: AbortSignal,
): Promise<ReadonlyMap<Locale, PlaceLocaleCatalog>> {
  const catalogs = await Promise.all(
    manifest.artifacts.locales.flatMap(({ locale, artifact }) =>
      artifact === null
        ? []
        : [
            fetchJson(artifact.url, signal).then((source) => {
              const catalog = parsePlaceLocaleCatalog(source);
              assertIdentity(manifest, catalog, `${locale.toUpperCase()} locale catalog`);
              const descriptor = manifest.localization.locales.find(
                (candidate) => candidate.locale === locale,
              );
              if (descriptor?.status === 'available') {
                assertLocaleCoverage(locations, catalog);
              }
              return [locale, catalog] as const;
            }),
          ],
    ),
  );

  return new Map(catalogs);
}

function localeFallbackChain(manifest: DatasetManifest, locale: Locale): Locale[] {
  const descriptors = new Map(
    manifest.localization.locales.map((descriptor) => [descriptor.locale, descriptor] as const),
  );
  const chain: Locale[] = [];
  let current: Locale | null = locale;

  while (current !== null) {
    chain.push(current);
    current = descriptors.get(current)?.fallbackLocale ?? null;
  }

  return chain;
}

function resolveLocaleFallbacks(
  manifest: DatasetManifest,
  locations: LocationCatalog,
  catalogs: ReadonlyMap<Locale, PlaceLocaleCatalog>,
): ReadonlyMap<Locale, PlaceLocaleCatalog> {
  const recordsByLocale = new Map(
    [...catalogs].map(([locale, catalog]) => [
      locale,
      new Map(catalog.places.map((record) => [record.placeId, record] as const)),
    ] as const),
  );
  const resolved = new Map<Locale, PlaceLocaleCatalog>();

  for (const descriptor of manifest.localization.locales) {
    if (descriptor.status === 'planned' || descriptor.status === 'unavailable') {
      continue;
    }
    const primaryCatalog = catalogs.get(descriptor.locale);
    if (!primaryCatalog) {
      continue;
    }
    const chain = localeFallbackChain(manifest, descriptor.locale);
    const effectivePlaces: PlaceLocaleRecord[] = [];

    for (const place of locations.places) {
      const localized = chain
        .map((candidate) => recordsByLocale.get(candidate)?.get(place.id))
        .find((record): record is PlaceLocaleRecord => record !== undefined);
      if (localized) {
        effectivePlaces.push(localized);
      }
    }

    if (effectivePlaces.length !== locations.places.length) {
      if (descriptor.locale === manifest.localization.defaultLocale) {
        throw new Error(
          `Locale ${descriptor.locale} and its fallback chain do not cover the complete location catalog`,
        );
      }
      continue;
    }

    resolved.set(descriptor.locale, {
      ...primaryCatalog,
      places: effectivePlaces,
    });
  }

  if (!resolved.has(manifest.localization.defaultLocale)) {
    throw new Error(
      `Default locale ${manifest.localization.defaultLocale} cannot be used for the location catalog`,
    );
  }

  return resolved;
}

function assertRequiredLocaleArtifacts(manifest: DatasetManifest): void {
  const artifactByLocale = new Map(
    manifest.artifacts.locales.map(({ locale, artifact }) => [locale, artifact] as const),
  );

  for (const descriptor of manifest.localization.locales) {
    if (
      (descriptor.locale === manifest.localization.defaultLocale || descriptor.status === 'available') &&
      !artifactByLocale.get(descriptor.locale)?.url
    ) {
      throw new DatasetAssetsMissingError(
        `Dataset ${manifest.datasetId} does not contain an ${descriptor.locale.toUpperCase()} locale catalog`,
      );
    }
  }
}

async function loadTileCoverages(
  manifest: DatasetManifest,
  mapAssets: MapAssetsManifest,
  signal: AbortSignal,
): Promise<ReadonlyMap<string, TileCoverage>> {
  const coverages = await Promise.all(
    (mapAssets.tilePyramids ?? []).map(async (pyramid) => {
      assertPyramidGrid(manifest, pyramid);
      const source = await fetchJson(pyramid.coverage.url, signal);
      return [pyramid.id, parseTileCoverage(source, mapAssets)] as const;
    }),
  );
  return new Map(coverages);
}

export async function loadDataset(
  manifest: DatasetManifest,
  signal: AbortSignal,
): Promise<DatasetBundle> {
  const locationUrl = requireArtifactUrl(
    manifest,
    manifest.artifacts.locations?.url,
    'location catalog',
  );
  const mapAssetsUrl = requireArtifactUrl(
    manifest,
    manifest.artifacts.tiles?.manifestUrl,
    'map assets',
  );
  assertRequiredLocaleArtifacts(manifest);

  const [locations, mapAssets] = await Promise.all([
    fetchJson(locationUrl, signal).then(parseLocationCatalog),
    fetchJson(mapAssetsUrl, signal).then(parseMapAssetsManifest),
  ]);
  assertIdentity(manifest, locations, 'Location catalog');
  assertIdentity(manifest, mapAssets, 'Map assets');
  if (mapAssets.projection !== manifest.map.projection.code) {
    throw new Error('Map assets projection does not match the dataset manifest');
  }

  const [rawLocales, tileCoverages] = await Promise.all([
    loadLocales(manifest, locations, signal),
    loadTileCoverages(manifest, mapAssets, signal),
  ]);
  const locales = resolveLocaleFallbacks(manifest, locations, rawLocales);

  return { locations, locales, mapAssets, tileCoverages };
}
