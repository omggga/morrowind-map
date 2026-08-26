export const DATASET_SCHEMA_VERSION = 1 as const;
export const TES3_PROJECTION_CODE = "TES3:WORLD" as const;
export const TES3_CELL_SIZE = 8192 as const;

export type DatasetSchemaVersion = typeof DATASET_SCHEMA_VERSION;
export type Tes3ProjectionCode = typeof TES3_PROJECTION_CODE;
export type Tes3CellSize = typeof TES3_CELL_SIZE;
export type Locale = "en" | "ru";
export type MapKey = "original" | "fullrest-old" | "poison-song";
export type DatasetReadiness = "placeholder" | "blocked" | "ready";
export type LocaleStatus = "available" | "partial" | "planned" | "unavailable";
export type RegionKind = "exterior" | "interior-inset";
export type RegionStatus = "available" | "planned" | "blocked" | "unconfirmed";
export type ProfileStatus = "confirmed" | "unconfirmed";
export type ContentFileKind = "esm" | "esp";
export type ContentFileInclusion = "required" | "optional" | "candidate" | "excluded";
export type ProfileItemStatus = "confirmed" | "unconfirmed";
export type ModuleStatus = "enabled" | "disabled" | "unconfirmed";

export type Point = readonly [x: number, y: number];
export type Extent = readonly [minX: number, minY: number, maxX: number, maxY: number];

export interface LocalizedText {
  en: string;
  ru?: string;
}

export interface DatasetIndexEntry {
  datasetId: string;
  manifestUrl: string;
  order: number;
}

export interface DatasetIndex {
  schemaVersion: DatasetSchemaVersion;
  defaultDatasetId: string;
  datasets: DatasetIndexEntry[];
}

export interface ReleaseDescriptor {
  name: string;
  version: string;
  build: string | null;
}

export interface ReadinessDescriptor {
  status: DatasetReadiness;
  exactProfile: boolean;
  blockers: string[];
  warnings: string[];
}

export interface LocaleDescriptor {
  locale: Locale;
  status: LocaleStatus;
  coverage: number;
  fallbackLocale: Locale | null;
}

export interface LocalizationDescriptor {
  defaultLocale: Locale;
  locales: LocaleDescriptor[];
}

export interface RegionDescriptor {
  id: string;
  title: LocalizedText;
  kind: RegionKind;
  status: RegionStatus;
}

export interface ContentFileDescriptor {
  name: string;
  kind: ContentFileKind;
  version: string | null;
  sha256: string | null;
  loadOrder: number | null;
  inclusion: ContentFileInclusion;
  enabled: boolean | null;
}

export interface RegisteredArchiveDescriptor {
  name: string;
  sha256: string | null;
  order: number | null;
  required: boolean;
  registered: boolean | null;
}

export interface DataDirectoryDescriptor {
  id: string;
  order: number | null;
  status: ProfileItemStatus;
}

export interface ModuleDescriptor {
  id: string;
  status: ModuleStatus;
  notes: string[];
}

export interface SourceProfileDescriptor {
  status: ProfileStatus;
  contentFiles: ContentFileDescriptor[];
  registeredArchives: RegisteredArchiveDescriptor[];
  dataDirectories: DataDirectoryDescriptor[];
  modules: ModuleDescriptor[];
}

export interface ProjectionDescriptor {
  code: Tes3ProjectionCode;
  units: "world-units";
  cellSize: Tes3CellSize;
  extent: Extent;
  center: Point;
}

export interface TileGridDescriptor {
  tileSize: 512;
  origin: Point;
  resolutions: number[];
}

export interface MapDescriptor {
  projection: ProjectionDescriptor;
  tileGrid: TileGridDescriptor;
}

export interface ArtifactReference {
  url: string;
  mediaType: "application/json";
  sha256: string;
  bytes: number;
}

export interface LocaleArtifactReference {
  locale: Locale;
  artifact: ArtifactReference | null;
}

export interface TileSetReference {
  manifestUrl: string;
  sha256: string;
}

export interface DatasetArtifacts {
  locations: ArtifactReference | null;
  locales: LocaleArtifactReference[];
  tiles: TileSetReference | null;
}

export interface ProvenanceDescriptor {
  kind: "placeholder" | "generated";
  notes: string[];
  knownIssues: string[];
}

export interface DatasetManifest {
  schemaVersion: DatasetSchemaVersion;
  datasetId: string;
  mapKey: MapKey;
  snapshotId: string;
  title: LocalizedText;
  summary: LocalizedText;
  release: ReleaseDescriptor;
  readiness: ReadinessDescriptor;
  localization: LocalizationDescriptor;
  regions: RegionDescriptor[];
  profile: SourceProfileDescriptor;
  map: MapDescriptor;
  artifacts: DatasetArtifacts;
  provenance: ProvenanceDescriptor;
}
