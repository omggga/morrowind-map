import Ajv2020 from "ajv/dist/2020.js";
import type { ErrorObject, ValidateFunction } from "ajv";

import datasetIndexSchema from "./schemas/dataset-index.schema.json";
import datasetManifestSchema from "./schemas/dataset-manifest.schema.json";
import locationCatalogSchema from "./schemas/location-catalog.schema.json";
import mapAssetsSchema from "./schemas/map-assets.schema.json";
import mimImportSchema from "./schemas/mim-import.schema.json";
import placeLocaleCatalogSchema from "./schemas/place-locale-catalog.schema.json";
import portableBackupSchema from "./schemas/portable-backup.schema.json";
import tileCoverageSchema from "./schemas/tile-coverage.schema.json";
import { createMimImportReceiptId } from "./import-receipt";
import { PORTABLE_BACKUP_SCHEMA_VERSION } from "./types";
import type {
  DatasetIndex,
  DatasetManifest,
  LocationCatalog,
  LocaleDescriptor,
  MapAssetsManifest,
  MimImportBundle,
  PlaceLocaleCatalog,
  PortableBackup,
  SourceProfileDescriptor,
  TileCoverage,
} from "./types";

export type ContractKind =
  | "dataset index"
  | "dataset manifest"
  | "location catalog"
  | "place locale catalog"
  | "map assets manifest"
  | "tile coverage"
  | "MIM import bundle"
  | "portable backup";

export interface ContractValidationIssue {
  instancePath: string;
  schemaPath: string;
  keyword: string;
  message: string;
  params: Readonly<Record<string, unknown>>;
}

export class ContractValidationError extends Error {
  readonly contract: ContractKind;
  readonly issues: readonly ContractValidationIssue[];

  constructor(contract: ContractKind, issues: readonly ContractValidationIssue[]) {
    super(
      `Invalid ${contract}: ${issues
        .map((issue) => `${issue.instancePath || "/"} ${issue.message}`)
        .join("; ")}`,
    );
    this.name = "ContractValidationError";
    this.contract = contract;
    this.issues = issues;
  }
}

const ajv = new Ajv2020({
  allErrors: true,
  allowUnionTypes: true,
  strict: true,
});

const validateIndexSchema = ajv.compile<DatasetIndex>(datasetIndexSchema);
const validateManifestSchema = ajv.compile<DatasetManifest>(datasetManifestSchema);
const validateLocationCatalogSchema = ajv.compile<LocationCatalog>(locationCatalogSchema);
const validatePlaceLocaleCatalogSchema =
  ajv.compile<PlaceLocaleCatalog>(placeLocaleCatalogSchema);
const validateMapAssetsSchema = ajv.compile<MapAssetsManifest>(mapAssetsSchema);
const validateTileCoverageSchema = ajv.compile<TileCoverage>(tileCoverageSchema);
const validateMimImportSchema = ajv.compile<MimImportBundle>(mimImportSchema);
const validatePortableBackupSchema = ajv.compile<PortableBackup>(portableBackupSchema);

function schemaIssues(validate: ValidateFunction): ContractValidationIssue[] {
  return (validate.errors ?? []).map((error: ErrorObject) => ({
    instancePath: error.instancePath,
    schemaPath: error.schemaPath,
    keyword: error.keyword,
    message: error.message ?? "failed schema validation",
    params: error.params,
  }));
}

function semanticIssue(instancePath: string, message: string): ContractValidationIssue {
  return {
    instancePath,
    schemaPath: "#/semantic",
    keyword: "semantic",
    message,
    params: {},
  };
}

function duplicateIssues(
  values: readonly string[],
  instancePath: string,
  label: string,
): ContractValidationIssue[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();

  for (const value of values) {
    if (seen.has(value)) {
      duplicates.add(value);
    }
    seen.add(value);
  }

  return [...duplicates].map((value) =>
    semanticIssue(instancePath, `${label} must be unique; duplicate ${JSON.stringify(value)}`),
  );
}

function numericDuplicateIssues(
  values: readonly number[],
  instancePath: string,
  label: string,
): ContractValidationIssue[] {
  return duplicateIssues(values.map(String), instancePath, label);
}

function getIndexSemanticIssues(index: DatasetIndex): ContractValidationIssue[] {
  const issues: ContractValidationIssue[] = [];
  const datasetIds = index.datasets.map((entry) => entry.datasetId);

  issues.push(...duplicateIssues(datasetIds, "/datasets", "datasetId values"));
  issues.push(
    ...duplicateIssues(
      index.datasets.map((entry) => entry.manifestUrl),
      "/datasets",
      "manifestUrl values",
    ),
  );
  issues.push(
    ...numericDuplicateIssues(
      index.datasets.map((entry) => entry.order),
      "/datasets",
      "order values",
    ),
  );

  if (!datasetIds.includes(index.defaultDatasetId)) {
    issues.push(
      semanticIssue("/defaultDatasetId", "must reference a datasetId present in datasets"),
    );
  }

  index.datasets.forEach((entry, indexPosition) => {
    if (!entry.manifestUrl.endsWith(`/${entry.datasetId}.json`)) {
      issues.push(
        semanticIssue(
          `/datasets/${indexPosition}/manifestUrl`,
          "filename must match datasetId",
        ),
      );
    }
  });

  return issues;
}

function getLocaleSemanticIssues(
  manifest: DatasetManifest,
  locales: readonly LocaleDescriptor[],
): ContractValidationIssue[] {
  const issues: ContractValidationIssue[] = [];
  const localeIds = locales.map((entry) => entry.locale);

  issues.push(...duplicateIssues(localeIds, "/localization/locales", "locale values"));

  const defaultEntry = locales.find(
    (entry) => entry.locale === manifest.localization.defaultLocale,
  );
  if (!defaultEntry || defaultEntry.status === "unavailable") {
    issues.push(
      semanticIssue(
        "/localization/defaultLocale",
        "must reference a locale that is present and not unavailable",
      ),
    );
  }

  locales.forEach((entry, index) => {
    const path = `/localization/locales/${index}`;
    if (entry.status === "available" && entry.coverage !== 1) {
      issues.push(semanticIssue(`${path}/coverage`, "must be 1 when status is available"));
    }
    if (entry.status === "partial" && !(entry.coverage > 0 && entry.coverage < 1)) {
      issues.push(
        semanticIssue(`${path}/coverage`, "must be between 0 and 1 when status is partial"),
      );
    }
    if (
      (entry.status === "planned" || entry.status === "unavailable") &&
      entry.coverage !== 0
    ) {
      issues.push(
        semanticIssue(`${path}/coverage`, `must be 0 when status is ${entry.status}`),
      );
    }
    if (entry.fallbackLocale === entry.locale) {
      issues.push(semanticIssue(`${path}/fallbackLocale`, "cannot refer to the same locale"));
    }
    if (entry.fallbackLocale !== null && !localeIds.includes(entry.fallbackLocale)) {
      issues.push(
        semanticIssue(`${path}/fallbackLocale`, "must reference another declared locale"),
      );
    }

    const visited = new Set([entry.locale]);
    let fallback = entry.fallbackLocale;
    while (fallback !== null) {
      if (visited.has(fallback)) {
        issues.push(semanticIssue(`${path}/fallbackLocale`, "fallback chain cannot contain a cycle"));
        break;
      }

      visited.add(fallback);
      fallback = locales.find((candidate) => candidate.locale === fallback)?.fallbackLocale ?? null;
    }
  });

  const artifactLocaleIds = manifest.artifacts.locales.map((entry) => entry.locale);
  issues.push(
    ...duplicateIssues(artifactLocaleIds, "/artifacts/locales", "artifact locale values"),
  );

  const declared = [...localeIds].sort().join(",");
  const artifacts = [...artifactLocaleIds].sort().join(",");
  if (declared !== artifacts) {
    issues.push(
      semanticIssue(
        "/artifacts/locales",
        "must contain exactly one entry for each declared locale",
      ),
    );
  }

  return issues;
}

function getProfileSemanticIssues(profile: SourceProfileDescriptor): ContractValidationIssue[] {
  const issues: ContractValidationIssue[] = [];

  issues.push(
    ...duplicateIssues(
      profile.contentFiles.map((entry) => entry.name.toLocaleLowerCase("en-US")),
      "/profile/contentFiles",
      "content file names",
    ),
    ...duplicateIssues(
      profile.registeredArchives.map((entry) => entry.name.toLocaleLowerCase("en-US")),
      "/profile/registeredArchives",
      "archive names",
    ),
    ...duplicateIssues(
      profile.dataDirectories.map((entry) => entry.id),
      "/profile/dataDirectories",
      "data directory ids",
    ),
    ...duplicateIssues(
      profile.modules.map((entry) => entry.id),
      "/profile/modules",
      "module ids",
    ),
  );

  const enabledOrders = profile.contentFiles.flatMap((entry) =>
    entry.enabled === true && entry.loadOrder !== null ? [entry.loadOrder] : [],
  );
  issues.push(
    ...numericDuplicateIssues(enabledOrders, "/profile/contentFiles", "enabled loadOrder values"),
  );

  profile.contentFiles.forEach((entry, index) => {
    const path = `/profile/contentFiles/${index}`;
    if (entry.kind !== entry.name.slice(-3).toLocaleLowerCase("en-US")) {
      issues.push(semanticIssue(`${path}/kind`, "must match the filename extension"));
    }
    if (entry.inclusion === "excluded" && entry.enabled !== false) {
      issues.push(semanticIssue(`${path}/enabled`, "must be false when inclusion is excluded"));
    }
    if (profile.status === "confirmed" && entry.enabled === null) {
      issues.push(semanticIssue(`${path}/enabled`, "cannot be null in a confirmed profile"));
    }
    if (profile.status === "confirmed" && entry.enabled === true && entry.loadOrder === null) {
      issues.push(
        semanticIssue(`${path}/loadOrder`, "cannot be null for an enabled confirmed content file"),
      );
    }
  });

  if (profile.status === "confirmed") {
    profile.dataDirectories.forEach((entry, index) => {
      if (entry.status !== "confirmed" || entry.order === null) {
        issues.push(
          semanticIssue(
            `/profile/dataDirectories/${index}`,
            "must be confirmed and ordered in a confirmed profile",
          ),
        );
      }
    });
    profile.registeredArchives.forEach((entry, index) => {
      if (entry.registered === null || (entry.registered && entry.order === null)) {
        issues.push(
          semanticIssue(
            `/profile/registeredArchives/${index}`,
            "registration and order must be known in a confirmed profile",
          ),
        );
      }
    });
  }

  return issues;
}

function getManifestSemanticIssues(manifest: DatasetManifest): ContractValidationIssue[] {
  const issues: ContractValidationIssue[] = [];
  const { extent, center, cellSize } = manifest.map.projection;
  const [minX, minY, maxX, maxY] = extent;
  const [centerX, centerY] = center;

  if (!(minX < maxX && minY < maxY)) {
    issues.push(semanticIssue("/map/projection/extent", "must have ordered non-empty bounds"));
  }
  if (extent.some((coordinate) => coordinate % cellSize !== 0)) {
    issues.push(
      semanticIssue("/map/projection/extent", "all bounds must align to TES3 cellSize"),
    );
  }
  if (centerX < minX || centerX > maxX || centerY < minY || centerY > maxY) {
    issues.push(semanticIssue("/map/projection/center", "must be inside projection extent"));
  }

  const expectedOrigin = [minX, maxY] as const;
  const origin = manifest.map.tileGrid.origin;
  if (origin[0] !== expectedOrigin[0] || origin[1] !== expectedOrigin[1]) {
    issues.push(
      semanticIssue("/map/tileGrid/origin", "must equal [extent.minX, extent.maxY]"),
    );
  }

  const resolutions = manifest.map.tileGrid.resolutions;
  for (let index = 1; index < resolutions.length; index += 1) {
    const previous = resolutions[index - 1];
    const current = resolutions[index];
    if (previous === undefined || current === undefined || previous <= current) {
      issues.push(
        semanticIssue("/map/tileGrid/resolutions", "must be strictly descending"),
      );
      break;
    }
  }

  issues.push(
    ...duplicateIssues(
      manifest.regions.map((region) => region.id),
      "/regions",
      "region ids",
    ),
    ...getLocaleSemanticIssues(manifest, manifest.localization.locales),
    ...getProfileSemanticIssues(manifest.profile),
  );

  if (manifest.readiness.status === "blocked" && manifest.readiness.blockers.length === 0) {
    issues.push(semanticIssue("/readiness/blockers", "must be non-empty when status is blocked"));
  }
  if (manifest.readiness.status !== "blocked" && manifest.readiness.blockers.length > 0) {
    issues.push(semanticIssue("/readiness/blockers", "must be empty unless status is blocked"));
  }
  if (manifest.readiness.exactProfile && manifest.profile.status !== "confirmed") {
    issues.push(
      semanticIssue("/readiness/exactProfile", "requires profile.status to be confirmed"),
    );
  }

  if (manifest.readiness.status === "ready") {
    if (!manifest.readiness.exactProfile) {
      issues.push(semanticIssue("/readiness/exactProfile", "must be true when status is ready"));
    }
    if (manifest.artifacts.locations === null || manifest.artifacts.tiles === null) {
      issues.push(
        semanticIssue("/artifacts", "ready datasets require locations and tile artifacts"),
      );
    }
    manifest.localization.locales.forEach((locale, index) => {
      const artifact = manifest.artifacts.locales.find(
        (entry) => entry.locale === locale.locale,
      )?.artifact;
      if (locale.status === "available" && !artifact) {
        issues.push(
          semanticIssue(
            `/artifacts/locales/${index}/artifact`,
            "an available locale in a ready dataset requires an artifact",
          ),
        );
      }
    });
    if (manifest.provenance.kind !== "generated") {
      issues.push(semanticIssue("/provenance/kind", "must be generated when status is ready"));
    }
  }

  return issues;
}

export function getDatasetIndexValidationIssues(value: unknown): ContractValidationIssue[] {
  if (!validateIndexSchema(value)) {
    return schemaIssues(validateIndexSchema);
  }
  return getIndexSemanticIssues(value);
}

export function getDatasetManifestValidationIssues(value: unknown): ContractValidationIssue[] {
  if (!validateManifestSchema(value)) {
    return schemaIssues(validateManifestSchema);
  }
  return getManifestSemanticIssues(value);
}

export function getLocationCatalogValidationIssues(value: unknown): ContractValidationIssue[] {
  if (!validateLocationCatalogSchema(value)) {
    return schemaIssues(validateLocationCatalogSchema);
  }

  const catalog = value;
  const issues = duplicateIssues(
    catalog.places.map((place) => place.id),
    "/places",
    "place ids",
  );
  catalog.places.forEach((place, placeIndex) => {
    issues.push(
      ...duplicateIssues(
        place.entrances.map((entrance) => entrance.id),
        `/places/${placeIndex}/entrances`,
        "entrance ids",
      ),
    );
  });
  return issues;
}

export function getPlaceLocaleCatalogValidationIssues(
  value: unknown,
): ContractValidationIssue[] {
  if (!validatePlaceLocaleCatalogSchema(value)) {
    return schemaIssues(validatePlaceLocaleCatalogSchema);
  }
  return duplicateIssues(
    value.places.map((place) => place.placeId),
    "/places",
    "localized place ids",
  );
}

export function getMapAssetsManifestValidationIssues(
  value: unknown,
): ContractValidationIssue[] {
  if (!validateMapAssetsSchema(value)) {
    return schemaIssues(validateMapAssetsSchema);
  }

  const tilePyramids = value.tilePyramids ?? [];
  const issues = [
    ...duplicateIssues(
      value.rasters.map((raster) => raster.id),
      "/rasters",
      "raster ids",
    ),
    ...duplicateIssues(
      tilePyramids.map((pyramid) => pyramid.id),
      "/tilePyramids",
      "tile pyramid ids",
    ),
    ...duplicateIssues(
      [...value.rasters.map((raster) => raster.id), ...tilePyramids.map((pyramid) => pyramid.id)],
      "/",
      "map asset ids",
    ),
  ];
  value.rasters.forEach((raster, index) => {
    const [minX, minY, maxX, maxY] = raster.extent;
    if (!(minX < maxX && minY < maxY)) {
      issues.push(
        semanticIssue(`/rasters/${index}/extent`, "must have ordered non-empty bounds"),
      );
    }
  });
  tilePyramids.forEach((pyramid, index) => {
    const path = `/tilePyramids/${index}`;
    const [minX, minY, maxX, maxY] = pyramid.extent;
    if (!(minX < maxX && minY < maxY)) {
      issues.push(
        semanticIssue(`${path}/extent`, "must have ordered non-empty bounds"),
      );
    }
    if (pyramid.origin[0] !== minX || pyramid.origin[1] !== maxY) {
      issues.push(
        semanticIssue(`${path}/origin`, "must equal [extent.minX, extent.maxY]"),
      );
    }
    if (pyramid.minZoom > pyramid.maxZoom) {
      issues.push(semanticIssue(`${path}/minZoom`, "must not exceed maxZoom"));
    }
    if (pyramid.resolutions.length !== pyramid.maxZoom - pyramid.minZoom + 1) {
      issues.push(
        semanticIssue(
          `${path}/resolutions`,
          "must contain exactly one resolution for every zoom from minZoom through maxZoom",
        ),
      );
    }
    for (
      let resolutionIndex = 1;
      resolutionIndex < pyramid.resolutions.length;
      resolutionIndex += 1
    ) {
      const previous = pyramid.resolutions[resolutionIndex - 1];
      const current = pyramid.resolutions[resolutionIndex];
      if (previous === undefined || current === undefined || previous <= current) {
        issues.push(
          semanticIssue(`${path}/resolutions`, "must be strictly descending"),
        );
        break;
      }
    }
  });
  return issues;
}

export function getTileCoverageValidationIssues(
  value: unknown,
  mapAssets?: MapAssetsManifest,
): ContractValidationIssue[] {
  if (!validateTileCoverageSchema(value)) {
    return schemaIssues(validateTileCoverageSchema);
  }

  const issues: ContractValidationIssue[] = [];
  let countedTiles = 0;
  let previousZ: number | undefined;

  value.levels.forEach((level, levelIndex) => {
    const levelPath = `/levels/${levelIndex}`;
    if (previousZ !== undefined && level.z <= previousZ) {
      issues.push(semanticIssue(`${levelPath}/z`, "must be strictly increasing"));
    }
    previousZ = level.z;

    let previousX: number | undefined;
    level.columns.forEach((column, columnIndex) => {
      const columnPath = `${levelPath}/columns/${columnIndex}`;
      if (previousX !== undefined && column.x <= previousX) {
        issues.push(semanticIssue(`${columnPath}/x`, "must be strictly increasing"));
      }
      previousX = column.x;

      let previousMaxY: number | undefined;
      column.yRanges.forEach(([minY, maxY], rangeIndex) => {
        const rangePath = `${columnPath}/yRanges/${rangeIndex}`;
        if (minY > maxY) {
          issues.push(semanticIssue(rangePath, "must have ordered inclusive bounds"));
          return;
        }
        if (previousMaxY !== undefined && minY <= previousMaxY + 1) {
          issues.push(
            semanticIssue(
              rangePath,
              "must be sorted, non-overlapping and maximally merge adjacent values",
            ),
          );
        }
        countedTiles += maxY - minY + 1;
        previousMaxY = maxY;
      });
    });
  });

  if (countedTiles !== value.tileCount) {
    issues.push(
      semanticIssue(
        "/tileCount",
        `must equal the ${countedTiles} tiles encoded by levels`,
      ),
    );
  }

  if (mapAssets !== undefined) {
    if (getMapAssetsManifestValidationIssues(mapAssets).length > 0) {
      issues.push(
        semanticIssue("/", "cannot validate coverage against an invalid map assets manifest"),
      );
      return issues;
    }

    if (value.datasetId !== mapAssets.datasetId) {
      issues.push(semanticIssue("/datasetId", "must match the map assets manifest"));
    }
    if (value.snapshotId !== mapAssets.snapshotId) {
      issues.push(semanticIssue("/snapshotId", "must match the map assets manifest"));
    }

    const pyramid = mapAssets.tilePyramids?.find(
      (candidate) => candidate.id === value.tilePyramidId,
    );
    if (pyramid === undefined) {
      issues.push(
        semanticIssue("/tilePyramidId", "must reference a tile pyramid in the map assets manifest"),
      );
    } else {
      if (value.tileCount !== pyramid.integrity.tileCount) {
        issues.push(
          semanticIssue("/tileCount", "must match tile pyramid integrity.tileCount"),
        );
      }
      const expectedZooms = Array.from(
        { length: pyramid.maxZoom - pyramid.minZoom + 1 },
        (_, index) => pyramid.minZoom + index,
      );
      if (
        value.levels.length !== expectedZooms.length ||
        value.levels.some((level, index) => level.z !== expectedZooms[index])
      ) {
        issues.push(
          semanticIssue(
            "/levels",
            "must contain exactly one ordered level for every tile pyramid zoom",
          ),
        );
      }
      value.levels.forEach((level, levelIndex) => {
        if (level.z < pyramid.minZoom || level.z > pyramid.maxZoom) {
          issues.push(
            semanticIssue(
              `/levels/${levelIndex}/z`,
              `must be between tile pyramid minZoom ${pyramid.minZoom} and maxZoom ${pyramid.maxZoom}`,
            ),
          );
          return;
        }
        const resolution = pyramid.resolutions[level.z - pyramid.minZoom];
        if (resolution === undefined) {
          return;
        }
        const [minX, minY, maxX, maxY] = pyramid.extent;
        const tileWorldSize = pyramid.tileSize * resolution;
        const columnCount = Math.ceil((maxX - minX) / tileWorldSize);
        const rowCount = Math.ceil((maxY - minY) / tileWorldSize);
        level.columns.forEach((column, columnIndex) => {
          const columnPath = `/levels/${levelIndex}/columns/${columnIndex}`;
          if (column.x >= columnCount) {
            issues.push(
              semanticIssue(
                `${columnPath}/x`,
                `must be inside the ${columnCount}-column tile grid at z${level.z}`,
              ),
            );
          }
          column.yRanges.forEach(([, rangeMaxY], rangeIndex) => {
            if (rangeMaxY >= rowCount) {
              issues.push(
                semanticIssue(
                  `${columnPath}/yRanges/${rangeIndex}`,
                  `must be inside the ${rowCount}-row tile grid at z${level.z}`,
                ),
              );
            }
          });
        });
      });
    }
  }

  return issues;
}

export function getMimImportBundleValidationIssues(
  value: unknown,
): ContractValidationIssue[] {
  if (!validateMimImportSchema(value)) {
    return schemaIssues(validateMimImportSchema);
  }

  const issues = [
    ...duplicateIssues(
      value.sourceFiles.map((sourceFile) => sourceFile.path),
      "/sourceFiles",
      "source file paths",
    ),
    ...duplicateIssues(
      value.progress.map((progress) => progress.placeId),
      "/progress",
      "MIM progress place ids",
    ),
    ...duplicateIssues(
      value.customMarkers.map((marker) => marker.id),
      "/customMarkers",
      "MIM custom marker ids",
    ),
  ];
  value.progress.forEach((progress, index) => {
    if (!progress.placeId.startsWith(`${value.targetDatasetId}.`)) {
      issues.push(
        semanticIssue(
          `/progress/${index}/placeId`,
          "must be scoped to targetDatasetId",
        ),
      );
    }
  });
  value.customMarkers.forEach((marker, index) => {
    if (!marker.id.startsWith(`${value.targetDatasetId}.`)) {
      issues.push(
        semanticIssue(
          `/customMarkers/${index}/id`,
          "must be scoped to targetDatasetId",
        ),
      );
    }
  });
  return issues;
}

function getProvenanceIssues(
  provenance: PortableBackup["progress"][number]["provenance"],
  instancePath: string,
): ContractValidationIssue[] {
  if (provenance.kind === "manual" && provenance.sourceFingerprint !== null) {
    return [semanticIssue(instancePath, "manual provenance requires a null fingerprint")];
  }
  if (provenance.kind === "mim-import" && provenance.sourceFingerprint === null) {
    return [semanticIssue(instancePath, "MIM provenance requires a source fingerprint")];
  }
  return [];
}

interface PortableBackupNormalizationResult {
  value: unknown;
  issues: ContractValidationIssue[];
}

function isUnknownRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeLegacyPortableBackup(value: unknown): PortableBackupNormalizationResult {
  if (!isUnknownRecord(value) || value.schemaVersion !== 1) {
    return { value, issues: [] };
  }

  const issues: ContractValidationIssue[] = [];
  const importReceipts = Array.isArray(value.importReceipts)
    ? (value.importReceipts as unknown[]).map((receipt, index) => {
        if (!isUnknownRecord(receipt)) {
          return receipt;
        }

        const { datasetId, id, sourceFingerprint } = receipt;
        if (
          typeof datasetId !== "string" ||
          typeof id !== "string" ||
          typeof sourceFingerprint !== "string"
        ) {
          return receipt;
        }

        if (id !== `mim:${datasetId}:${sourceFingerprint}`) {
          issues.push(
            semanticIssue(
              `/importReceipts/${index}/id`,
              "legacy receipt id must match datasetId and sourceFingerprint",
            ),
          );
          return receipt;
        }

        return {
          ...receipt,
          id: createMimImportReceiptId(datasetId, sourceFingerprint),
        };
      })
    : value.importReceipts;

  return {
    value: {
      ...value,
      schemaVersion: PORTABLE_BACKUP_SCHEMA_VERSION,
      importReceipts,
    },
    issues,
  };
}

export function getPortableBackupValidationIssues(value: unknown): ContractValidationIssue[] {
  if (!validatePortableBackupSchema(value)) {
    return schemaIssues(validatePortableBackupSchema);
  }

  const datasetIds = new Set(Object.keys(value.datasets));
  const issues = [
    ...duplicateIssues(
      value.progress.map(({ datasetId, placeId }) => `${datasetId}\0${placeId}`),
      "/progress",
      "progress identities",
    ),
    ...duplicateIssues(
      value.customMarkers.map(({ id }) => id),
      "/customMarkers",
      "custom marker ids",
    ),
    ...duplicateIssues(
      value.importReceipts.map(({ id }) => id),
      "/importReceipts",
      "import receipt ids",
    ),
  ];

  if (Number.isNaN(Date.parse(value.exportedAt))) {
    issues.push(semanticIssue("/exportedAt", "must be a real UTC timestamp"));
  }
  value.progress.forEach((progress, index) => {
    if (!datasetIds.has(progress.datasetId)) {
      issues.push(
        semanticIssue(`/progress/${index}/datasetId`, "must be declared in datasets"),
      );
    }
    if (!progress.placeId.startsWith(`${progress.datasetId}.`)) {
      issues.push(
        semanticIssue(`/progress/${index}/placeId`, "must be scoped to datasetId"),
      );
    }
    if (Number.isNaN(Date.parse(progress.updatedAt))) {
      issues.push(semanticIssue(`/progress/${index}/updatedAt`, "must be a real timestamp"));
    }
    issues.push(...getProvenanceIssues(progress.provenance, `/progress/${index}/provenance`));
  });
  value.customMarkers.forEach((marker, index) => {
    if (!datasetIds.has(marker.datasetId)) {
      issues.push(
        semanticIssue(`/customMarkers/${index}/datasetId`, "must be declared in datasets"),
      );
    }
    if (!marker.id.startsWith(`${marker.datasetId}.`)) {
      issues.push(
        semanticIssue(`/customMarkers/${index}/id`, "must be scoped to datasetId"),
      );
    }
    const createdAt = Date.parse(marker.createdAt);
    const updatedAt = Date.parse(marker.updatedAt);
    const deletedAt = marker.deletedAt === null ? null : Date.parse(marker.deletedAt);
    if (
      Number.isNaN(createdAt) ||
      Number.isNaN(updatedAt) ||
      (deletedAt !== null && Number.isNaN(deletedAt))
    ) {
      issues.push(
        semanticIssue(`/customMarkers/${index}`, "marker timestamps must be real timestamps"),
      );
    } else {
      if (createdAt > updatedAt) {
        issues.push(
          semanticIssue(
            `/customMarkers/${index}/updatedAt`,
            "must not be earlier than createdAt",
          ),
        );
      }
      if (deletedAt !== null && (deletedAt < createdAt || deletedAt > updatedAt)) {
        issues.push(
          semanticIssue(
            `/customMarkers/${index}/deletedAt`,
            "must be between createdAt and updatedAt",
          ),
        );
      }
    }
    issues.push(
      ...getProvenanceIssues(marker.provenance, `/customMarkers/${index}/provenance`),
    );
  });
  value.importReceipts.forEach((receipt, index) => {
    if (!datasetIds.has(receipt.datasetId)) {
      issues.push(
        semanticIssue(`/importReceipts/${index}/datasetId`, "must be declared in datasets"),
      );
    }
    if (Number.isNaN(Date.parse(receipt.importedAt))) {
      issues.push(
        semanticIssue(`/importReceipts/${index}/importedAt`, "must be a real timestamp"),
      );
    }
    if (
      receipt.id !==
      createMimImportReceiptId(receipt.datasetId, receipt.sourceFingerprint)
    ) {
      issues.push(
        semanticIssue(
          `/importReceipts/${index}/id`,
          "must be the canonical id for datasetId and sourceFingerprint",
        ),
      );
    }
  });
  return issues;
}

export function isDatasetIndex(value: unknown): value is DatasetIndex {
  return getDatasetIndexValidationIssues(value).length === 0;
}

export function isDatasetManifest(value: unknown): value is DatasetManifest {
  return getDatasetManifestValidationIssues(value).length === 0;
}

export function isLocationCatalog(value: unknown): value is LocationCatalog {
  return getLocationCatalogValidationIssues(value).length === 0;
}

export function isPlaceLocaleCatalog(value: unknown): value is PlaceLocaleCatalog {
  return getPlaceLocaleCatalogValidationIssues(value).length === 0;
}

export function isMapAssetsManifest(value: unknown): value is MapAssetsManifest {
  return getMapAssetsManifestValidationIssues(value).length === 0;
}

export function isTileCoverage(
  value: unknown,
  mapAssets?: MapAssetsManifest,
): value is TileCoverage {
  return getTileCoverageValidationIssues(value, mapAssets).length === 0;
}

export function isMimImportBundle(value: unknown): value is MimImportBundle {
  return getMimImportBundleValidationIssues(value).length === 0;
}

export function isPortableBackup(value: unknown): value is PortableBackup {
  return getPortableBackupValidationIssues(value).length === 0;
}

export function parseDatasetIndex(value: unknown): DatasetIndex {
  const issues = getDatasetIndexValidationIssues(value);
  if (issues.length > 0) {
    throw new ContractValidationError("dataset index", issues);
  }
  return value as DatasetIndex;
}

export function parseDatasetManifest(value: unknown): DatasetManifest {
  const issues = getDatasetManifestValidationIssues(value);
  if (issues.length > 0) {
    throw new ContractValidationError("dataset manifest", issues);
  }
  return value as DatasetManifest;
}

export function parseLocationCatalog(value: unknown): LocationCatalog {
  const issues = getLocationCatalogValidationIssues(value);
  if (issues.length > 0) {
    throw new ContractValidationError("location catalog", issues);
  }
  return value as LocationCatalog;
}

export function parsePlaceLocaleCatalog(value: unknown): PlaceLocaleCatalog {
  const issues = getPlaceLocaleCatalogValidationIssues(value);
  if (issues.length > 0) {
    throw new ContractValidationError("place locale catalog", issues);
  }
  return value as PlaceLocaleCatalog;
}

export function parseMapAssetsManifest(value: unknown): MapAssetsManifest {
  const issues = getMapAssetsManifestValidationIssues(value);
  if (issues.length > 0) {
    throw new ContractValidationError("map assets manifest", issues);
  }
  return value as MapAssetsManifest;
}

export function parseTileCoverage(
  value: unknown,
  mapAssets?: MapAssetsManifest,
): TileCoverage {
  const issues = getTileCoverageValidationIssues(value, mapAssets);
  if (issues.length > 0) {
    throw new ContractValidationError("tile coverage", issues);
  }
  return value as TileCoverage;
}

export function parseMimImportBundle(value: unknown): MimImportBundle {
  const issues = getMimImportBundleValidationIssues(value);
  if (issues.length > 0) {
    throw new ContractValidationError("MIM import bundle", issues);
  }
  return value as MimImportBundle;
}

export function parsePortableBackup(value: unknown): PortableBackup {
  const normalized = normalizeLegacyPortableBackup(value);
  const issues = [
    ...normalized.issues,
    ...getPortableBackupValidationIssues(normalized.value),
  ];
  if (issues.length > 0) {
    throw new ContractValidationError("portable backup", issues);
  }
  return normalized.value as PortableBackup;
}
