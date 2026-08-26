import Ajv2020 from "ajv/dist/2020.js";
import type { ErrorObject, ValidateFunction } from "ajv";

import datasetIndexSchema from "./schemas/dataset-index.schema.json";
import datasetManifestSchema from "./schemas/dataset-manifest.schema.json";
import locationCatalogSchema from "./schemas/location-catalog.schema.json";
import mapAssetsSchema from "./schemas/map-assets.schema.json";
import placeLocaleCatalogSchema from "./schemas/place-locale-catalog.schema.json";
import type {
  DatasetIndex,
  DatasetManifest,
  LocationCatalog,
  LocaleDescriptor,
  MapAssetsManifest,
  PlaceLocaleCatalog,
  SourceProfileDescriptor,
} from "./types";

export type ContractKind =
  | "dataset index"
  | "dataset manifest"
  | "location catalog"
  | "place locale catalog"
  | "map assets manifest";

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

  const issues = duplicateIssues(
    value.rasters.map((raster) => raster.id),
    "/rasters",
    "raster ids",
  );
  value.rasters.forEach((raster, index) => {
    const [minX, minY, maxX, maxY] = raster.extent;
    if (!(minX < maxX && minY < maxY)) {
      issues.push(
        semanticIssue(`/rasters/${index}/extent`, "must have ordered non-empty bounds"),
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
