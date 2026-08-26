import {
  parseLocationCatalog,
  parseMapAssetsManifest,
  parsePlaceLocaleCatalog,
  type DatasetManifest,
  type LocationCatalog,
  type Locale,
  type MapAssetsManifest,
  type PlaceLocaleCatalog,
} from '@morrowind-map/contracts';

export interface OriginalDatasetBundle {
  readonly locations: LocationCatalog;
  readonly locales: Readonly<Record<Locale, PlaceLocaleCatalog>>;
  readonly mapAssets: MapAssetsManifest;
}

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal,
  });
  if (!response.ok) {
    throw new Error(`Не удалось загрузить ${url} (HTTP ${response.status})`);
  }
  return response.json() as Promise<unknown>;
}

function requireArtifactUrl(url: string | undefined, label: string): string {
  if (!url) {
    throw new Error(`Original dataset не содержит ${label}`);
  }
  return url;
}

function assertIdentity(
  manifest: DatasetManifest,
  artifact: { readonly datasetId: string; readonly snapshotId: string },
  label: string,
): void {
  if (artifact.datasetId !== manifest.datasetId || artifact.snapshotId !== manifest.snapshotId) {
    throw new Error(`${label} относится к другому dataset snapshot`);
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
    throw new Error(`Locale ${localeCatalog.locale} не покрывает весь location catalog`);
  }
}

export async function loadOriginalDataset(
  manifest: DatasetManifest,
  signal: AbortSignal,
): Promise<OriginalDatasetBundle> {
  const locationUrl = requireArtifactUrl(manifest.artifacts.locations?.url, 'location catalog');
  const mapAssetsUrl = requireArtifactUrl(manifest.artifacts.tiles?.manifestUrl, 'map assets');
  const localeUrls = new Map(
    manifest.artifacts.locales.flatMap(({ locale, artifact }) =>
      artifact ? ([[locale, artifact.url]] as const) : [],
    ),
  );
  const enUrl = requireArtifactUrl(localeUrls.get('en'), 'EN locale catalog');
  const ruUrl = requireArtifactUrl(localeUrls.get('ru'), 'RU locale catalog');

  const [locations, english, russian, mapAssets] = await Promise.all([
    fetchJson(locationUrl, signal).then(parseLocationCatalog),
    fetchJson(enUrl, signal).then(parsePlaceLocaleCatalog),
    fetchJson(ruUrl, signal).then(parsePlaceLocaleCatalog),
    fetchJson(mapAssetsUrl, signal).then(parseMapAssetsManifest),
  ]);

  assertIdentity(manifest, locations, 'Location catalog');
  assertIdentity(manifest, english, 'EN locale catalog');
  assertIdentity(manifest, russian, 'RU locale catalog');
  assertIdentity(manifest, mapAssets, 'Map assets');
  if (english.locale !== 'en' || russian.locale !== 'ru') {
    throw new Error('Original locale artifacts объявлены в неверном порядке');
  }
  assertLocaleCoverage(locations, english);
  assertLocaleCoverage(locations, russian);

  return {
    locations,
    locales: { en: english, ru: russian },
    mapAssets,
  };
}
