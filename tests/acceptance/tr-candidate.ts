import { readFileSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, sep } from 'node:path';

import type {
  DatasetIndex,
  DatasetManifest,
  LocationCatalog,
  MapAssetsManifest,
  PlaceLocaleCatalog,
  PlaceRecord,
  TilePyramid,
} from '../../packages/contracts/src/types';

const ORIGINAL_DATASET_ID = 'original-goty-hd';
const CANDIDATE_PREFIX = '[TR candidate acceptance]';
const CONTRACT_SCHEMAS_ROOT = resolve(process.cwd(), 'packages/contracts/src/schemas');

interface SchemaValidationError {
  readonly instancePath?: string;
  readonly message?: string;
}

interface SchemaValidator<T> {
  (value: unknown): value is T;
  readonly errors?: readonly SchemaValidationError[] | null;
}

interface AjvInstance {
  compile<T>(schema: unknown): SchemaValidator<T>;
}

interface AjvConstructor {
  new (options: Readonly<Record<string, unknown>>): AjvInstance;
}

const schemaValidators = new Map<string, SchemaValidator<unknown>>();

export interface TrCandidate {
  readonly root: string;
  readonly index: DatasetIndex;
  readonly indexJson: string;
  readonly manifest: DatasetManifest;
  readonly manifestJson: string;
  readonly manifestUrl: string;
}

export interface TrCandidatePreparedAssets {
  readonly locations: LocationCatalog;
  readonly locale: PlaceLocaleCatalog;
  readonly mapAssets: MapAssetsManifest;
  readonly primaryPyramid: TilePyramid;
  readonly selectedPlace: PlaceRecord;
  readonly selectedPlaceName: string;
  readonly selectedRegionId: string;
  readonly selectedRegionName: string;
  readonly anyTypeCount: number;
  readonly zoom: number;
  readonly tileInventorySha256: string;
  readonly tileRequestPrefix: string;
  readonly tilesRoot: string;
}

function candidateError(message: string, cause?: unknown): Error {
  const detail = cause instanceof Error ? `: ${cause.message}` : '';
  return new Error(`${CANDIDATE_PREFIX} ${message}${detail}`, { cause });
}

function readText(path: string, label: string): string {
  try {
    return readFileSync(path, 'utf8');
  } catch (error) {
    throw candidateError(`cannot read ${label} at ${path}`, error);
  }
}

function parseContract<T>(
  path: string,
  label: string,
  parser: (value: unknown) => T,
): { readonly value: T; readonly source: string } {
  const source = readText(path, label);
  let decoded: unknown;
  try {
    decoded = JSON.parse(source) as unknown;
  } catch (error) {
    throw candidateError(`${label} at ${path} is not valid JSON`, error);
  }
  try {
    return { value: parser(decoded), source };
  } catch (error) {
    throw candidateError(`${label} at ${path} does not satisfy its contract`, error);
  }
}

function schemaParser<T>(schemaFile: string): (value: unknown) => T {
  return (value: unknown): T => {
    let validator = schemaValidators.get(schemaFile) as SchemaValidator<T> | undefined;
    if (!validator) {
      const requireFromContracts = createRequire(
        resolve(process.cwd(), 'packages/contracts/package.json'),
      );
      const Ajv2020 = (
        requireFromContracts('ajv/dist/2020.js') as { readonly default: AjvConstructor }
      ).default;
      const ajv = new Ajv2020({
        allErrors: true,
        allowUnionTypes: true,
        strict: true,
      });
      const schema = JSON.parse(
        readText(resolve(CONTRACT_SCHEMAS_ROOT, schemaFile), `${schemaFile} schema`),
      ) as unknown;
      validator = ajv.compile<T>(schema);
      schemaValidators.set(schemaFile, validator);
    }
    if (!validator(value)) {
      const details = (validator.errors ?? [])
        .map((error) => `${error.instancePath || '/'} ${error.message ?? 'is invalid'}`)
        .join('; ');
      throw new Error(details || 'schema validation failed');
    }
    return value;
  };
}

const parseDatasetIndex = schemaParser<DatasetIndex>('dataset-index.schema.json');
const parseDatasetManifest = schemaParser<DatasetManifest>('dataset-manifest.schema.json');
const parseLocationCatalog = schemaParser<LocationCatalog>('location-catalog.schema.json');
const parseMapAssetsManifest = schemaParser<MapAssetsManifest>('map-assets.schema.json');
const parsePlaceLocaleCatalog = schemaParser<PlaceLocaleCatalog>(
  'place-locale-catalog.schema.json',
);

function publicPath(url: string, label: string): string {
  if (!url.startsWith('/datasets/') || url.includes('?') || url.includes('#')) {
    throw candidateError(`${label} must be a root-relative /datasets/ URL; got ${url}`);
  }
  const publicRoot = resolve(process.cwd(), 'apps/web/public');
  const path = resolve(publicRoot, `.${url}`);
  if (path !== publicRoot && !path.startsWith(`${publicRoot}${sep}`)) {
    throw candidateError(`${label} escapes the public dataset root: ${url}`);
  }
  return path;
}

function requireMatchingIdentity(
  label: string,
  datasetId: string,
  snapshotId: string,
  candidate: TrCandidate,
): void {
  if (
    datasetId !== candidate.manifest.datasetId ||
    snapshotId !== candidate.manifest.snapshotId
  ) {
    throw candidateError(
      `${label} identity ${datasetId}/${snapshotId} does not match candidate ` +
        `${candidate.manifest.datasetId}/${candidate.manifest.snapshotId}`,
    );
  }
}

export function loadTrCandidateFromEnvironment(
  environment: NodeJS.ProcessEnv = process.env,
): TrCandidate | null {
  const configuredRoot = environment.MORROWIND_TR_CANDIDATE_ROOT;
  if (environment.MORROWIND_ACCEPTANCE_PREPARED !== '1' || configuredRoot === undefined) {
    return null;
  }
  if (configuredRoot.trim() === '') {
    throw candidateError('MORROWIND_TR_CANDIDATE_ROOT must not be empty');
  }

  const root = resolve(process.cwd(), configuredRoot);
  const indexPath = resolve(root, 'datasets/index.json');
  const parsedIndex = parseContract(indexPath, 'candidate dataset index', parseDatasetIndex);
  const originalEntries = parsedIndex.value.datasets.filter(
    ({ datasetId }) => datasetId === ORIGINAL_DATASET_ID,
  );
  const trEntries = parsedIndex.value.datasets.filter(
    ({ datasetId }) => datasetId !== ORIGINAL_DATASET_ID,
  );
  if (
    parsedIndex.value.defaultDatasetId !== ORIGINAL_DATASET_ID ||
    originalEntries.length !== 1 ||
    originalEntries[0]?.manifestUrl !==
      `/datasets/manifests/${ORIGINAL_DATASET_ID}.json`
  ) {
    throw candidateError(
      `candidate index must retain ${ORIGINAL_DATASET_ID} as the default public dataset`,
    );
  }
  if (trEntries.length !== 1) {
    throw candidateError(
      `candidate index must contain exactly one TR dataset in addition to ` +
        `${ORIGINAL_DATASET_ID}; found ${trEntries.length}`,
    );
  }

  const trEntry = trEntries[0]!;
  const expectedManifestUrl = `/datasets/manifests/${trEntry.datasetId}.json`;
  if (trEntry.manifestUrl !== expectedManifestUrl) {
    throw candidateError(
      `candidate index manifestUrl for ${trEntry.datasetId} must be ` +
        `${expectedManifestUrl}; got ${trEntry.manifestUrl}`,
    );
  }
  const manifestPath = resolve(
    root,
    'datasets/manifests',
    `${trEntry.datasetId}.json`,
  );
  const parsedManifest = parseContract(
    manifestPath,
    'candidate TR manifest',
    parseDatasetManifest,
  );
  if (
    parsedManifest.value.datasetId !== trEntry.datasetId ||
    parsedManifest.value.mapKey !== 'tamriel-rebuilt'
  ) {
    throw candidateError(
      `manifest ${manifestPath} must declare datasetId ${trEntry.datasetId} and ` +
        'mapKey tamriel-rebuilt',
    );
  }
  if (parsedManifest.value.readiness.status !== 'ready') {
    throw candidateError(
      `candidate TR manifest must be ready; got ${parsedManifest.value.readiness.status}`,
    );
  }

  return {
    root,
    index: parsedIndex.value,
    indexJson: parsedIndex.source,
    manifest: parsedManifest.value,
    manifestJson: parsedManifest.source,
    manifestUrl: expectedManifestUrl,
  };
}

export function loadTrCandidatePreparedAssets(
  candidate: TrCandidate,
): TrCandidatePreparedAssets {
  const locationsReference = candidate.manifest.artifacts.locations;
  const tilesReference = candidate.manifest.artifacts.tiles;
  const localeReference = candidate.manifest.artifacts.locales.find(
    ({ locale }) => locale === candidate.manifest.localization.defaultLocale,
  )?.artifact;
  if (locationsReference === null || tilesReference === null || !localeReference) {
    throw candidateError('ready candidate manifest must reference locations, locale, and tiles');
  }

  const locationsPath = publicPath(locationsReference.url, 'locations artifact URL');
  const localePath = publicPath(localeReference.url, 'locale artifact URL');
  const mapAssetsPath = publicPath(tilesReference.manifestUrl, 'map-assets URL');
  const locations = parseContract(
    locationsPath,
    'candidate locations artifact',
    parseLocationCatalog,
  ).value;
  const locale = parseContract(
    localePath,
    'candidate locale artifact',
    parsePlaceLocaleCatalog,
  ).value;
  const mapAssets = parseContract(
    mapAssetsPath,
    'candidate map-assets manifest',
    parseMapAssetsManifest,
  ).value;
  requireMatchingIdentity('locations artifact', locations.datasetId, locations.snapshotId, candidate);
  requireMatchingIdentity('locale artifact', locale.datasetId, locale.snapshotId, candidate);
  requireMatchingIdentity('map-assets manifest', mapAssets.datasetId, mapAssets.snapshotId, candidate);

  const primaryPyramid = mapAssets.tilePyramids?.[0];
  if (!primaryPyramid) {
    throw candidateError('candidate map-assets manifest must contain a tile pyramid');
  }
  const tileTemplateMarker = '/{z}/{x}/{y}.';
  const tileTemplateOffset = primaryPyramid.urlTemplate.indexOf(tileTemplateMarker);
  if (tileTemplateOffset < 0) {
    throw candidateError(
      `candidate tile URL template must contain ${tileTemplateMarker}; got ` +
        primaryPyramid.urlTemplate,
    );
  }
  const tilesUrl = primaryPyramid.urlTemplate.slice(0, tileTemplateOffset);
  const tilesRoot = publicPath(tilesUrl, 'candidate tiles root');
  try {
    if (!statSync(tilesRoot).isDirectory()) {
      throw new Error('path is not a directory');
    }
  } catch (error) {
    throw candidateError(`candidate tiles root is unavailable at ${tilesRoot}`, error);
  }

  const regionById = new Map(
    candidate.manifest.regions
      .filter(({ status }) => status === 'available')
      .map((region) => [region.id, region] as const),
  );
  const nameByPlaceId = new Map(locale.places.map((place) => [place.placeId, place.name]));
  const selectedPlace = [...locations.places]
    .filter(
      (place) =>
        regionById.has(place.regionId) &&
        primaryPyramid.regionIds.includes(place.regionId) &&
        nameByPlaceId.has(place.id) &&
        place.minZoom <= primaryPyramid.maxZoom,
    )
    .sort((left, right) => {
      const leftMainland = left.regionId === 'tr-mainland' ? 0 : 1;
      const rightMainland = right.regionId === 'tr-mainland' ? 0 : 1;
      return leftMainland - rightMainland || left.minZoom - right.minZoom || left.id.localeCompare(right.id);
    })[0];
  if (!selectedPlace) {
    throw candidateError(
      'candidate catalog has no localized place in an available tile-pyramid region',
    );
  }
  const selectedRegion = regionById.get(selectedPlace.regionId)!;
  const selectedPlaceName = nameByPlaceId.get(selectedPlace.id)!;
  const zoom = Math.max(
    primaryPyramid.minZoom,
    Math.min(primaryPyramid.maxZoom, Math.max(4.5, selectedPlace.minZoom)),
  );
  const anyTypeCount = locations.places.filter(
    (place) => place.regionId === selectedRegion.id && place.minZoom <= zoom,
  ).length;

  return {
    locations,
    locale,
    mapAssets,
    primaryPyramid,
    selectedPlace,
    selectedPlaceName,
    selectedRegionId: selectedRegion.id,
    selectedRegionName: selectedRegion.title.en,
    anyTypeCount,
    zoom,
    tileInventorySha256: primaryPyramid.integrity.inventorySha256,
    tileRequestPrefix: primaryPyramid.urlTemplate.slice(0, tileTemplateOffset + 1),
    tilesRoot,
  };
}
