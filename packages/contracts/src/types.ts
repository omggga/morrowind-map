export const DATASET_SCHEMA_VERSION = 1 as const;
export const ARTIFACT_SCHEMA_VERSION = 1 as const;
export const PORTABLE_BACKUP_SCHEMA_VERSION = 3 as const;
export const TES3_PROJECTION_CODE = "TES3:WORLD" as const;
export const TES3_CELL_SIZE = 8192 as const;

export type DatasetSchemaVersion = typeof DATASET_SCHEMA_VERSION;
export type Tes3ProjectionCode = typeof TES3_PROJECTION_CODE;
export type Tes3CellSize = typeof TES3_CELL_SIZE;
export type Locale = "en";
export type MapKey = "original" | "tamriel-rebuilt" | "project-cyrodiil";
export type DatasetReadiness = "placeholder" | "blocked" | "ready";
export type LocaleStatus = "available" | "partial" | "planned" | "unavailable";
export type RegionKind = "exterior" | "interior-inset";
export type RegionStatus = "available" | "planned" | "blocked" | "unconfirmed";
export type ProfileStatus = "confirmed" | "unconfirmed";
export type ContentFileKind = "esm" | "esp";
export type ContentFileInclusion = "required" | "optional" | "candidate" | "excluded";
export type ProfileItemStatus = "confirmed" | "unconfirmed";
export type ModuleStatus = "enabled" | "disabled" | "unconfirmed";
export type PlaceType =
  | "settlement"
  | "guild"
  | "temple"
  | "cave"
  | "mine"
  | "ship"
  | "shrine"
  | "ancestral-tomb"
  | "stronghold"
  | "dwemer-ruin"
  | "house"
  | "shop"
  | "landmark"
  | "other";
export type PlaceSourceKind = "esm";
export type ProgressStatus = "unvisited" | "active" | "visited";
export type UserDataProvenanceKind = "manual";

export type Point = readonly [x: number, y: number];
export type Extent = readonly [minX: number, minY: number, maxX: number, maxY: number];

export interface LocalizedText {
  en: string;
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
  catalogAudit?: ArtifactReference | null;
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

export interface PlaceSource {
  kind: PlaceSourceKind;
  plugin: string;
  recordId: string | null;
  mimIndex: number | null;
}

export interface PlaceEntrance {
  id: string;
  coordinate: Point;
  exteriorCell: Point;
  sourcePlugin: string;
  sourceRef: string;
}

export interface PlaceRecord {
  id: string;
  regionId: string;
  type: PlaceType;
  mapPosition: Point;
  exteriorCell: Point;
  mimCategory: number | null;
  minZoom: number;
  entrances: PlaceEntrance[];
  sources: PlaceSource[];
}

export interface LocationCatalog {
  schemaVersion: typeof ARTIFACT_SCHEMA_VERSION;
  datasetId: string;
  snapshotId: string;
  places: PlaceRecord[];
}

export interface PlaceLocaleRecord {
  placeId: string;
  name: string;
  aliases: string[];
}

export interface PlaceLocaleCatalog {
  schemaVersion: typeof ARTIFACT_SCHEMA_VERSION;
  datasetId: string;
  snapshotId: string;
  locale: Locale;
  places: PlaceLocaleRecord[];
}

export interface StaticRasterLayer {
  id: string;
  regionId: string;
  kind: "static-image";
  imageUrl: string;
  mediaType: "image/jpeg";
  pixelSize: Point;
  extent: Extent;
  sha256: string;
}

export interface TilePyramidIntegrity {
  tileCount: number;
  totalBytes: number;
  inventorySha256: string;
  inventoryFileSha256: string;
  provenanceFingerprint: string;
  planFingerprint: string;
  profileFingerprint: string;
  rendererFingerprint: string;
  productionSourceFingerprint: string;
  assetTreeFingerprint: string;
  inputFingerprint: string;
}

export interface TilePyramidDerivation {
  kind: "cross-shard-seam-stabilization";
  version: string;
  sourceInventorySha256: string;
  implementationSha256: string;
  receipt: ArtifactReference;
}

export interface TilePyramidPresentation {
  gradeVersion: "mim-opaque-v4";
  alphaMode: "binary-nonzero";
  colorGrade: "baked";
}

export interface TilePyramid {
  id: string;
  regionIds: string[];
  kind: "xyz-pyramid";
  urlTemplate: string;
  mediaType: "image/webp";
  tileSize: 512;
  extent: Extent;
  origin: Point;
  resolutions: number[];
  minZoom: number;
  maxZoom: number;
  sparse: true;
  coverage: ArtifactReference;
  qualityReport: ArtifactReference;
  derivation: TilePyramidDerivation;
  integrity: TilePyramidIntegrity;
  presentation?: TilePyramidPresentation;
}

export interface MapAssetsManifest {
  schemaVersion: typeof ARTIFACT_SCHEMA_VERSION;
  datasetId: string;
  snapshotId: string;
  projection: Tes3ProjectionCode;
  rasters: StaticRasterLayer[];
  tilePyramids?: TilePyramid[];
}

export type TileYRange = readonly [minY: number, maxY: number];

export interface TileCoverageColumn {
  x: number;
  yRanges: TileYRange[];
}

export interface TileCoverageLevel {
  z: number;
  columns: TileCoverageColumn[];
}

export interface TileCoverage {
  schemaVersion: typeof ARTIFACT_SCHEMA_VERSION;
  datasetId: string;
  snapshotId: string;
  tilePyramidId: string;
  encoding: "x-y-ranges-v1";
  tileCount: number;
  levels: TileCoverageLevel[];
}

export interface UserDataProvenance {
  kind: UserDataProvenanceKind;
  sourceFingerprint: null;
}

export interface ProgressRecord {
  datasetId: string;
  placeId: string;
  status: ProgressStatus;
  note: string;
  updatedAt: string;
  provenance: UserDataProvenance;
}

export interface CustomMarkerRecord {
  id: string;
  datasetId: string;
  label: string;
  note: string;
  position: Point;
  createdAt: string;
  updatedAt: string;
  deletedAt: string | null;
  provenance: UserDataProvenance;
}

export interface PortableBackup {
  schemaVersion: typeof PORTABLE_BACKUP_SCHEMA_VERSION;
  kind: "morrowind-map-backup";
  exportedAt: string;
  datasets: Record<string, string>;
  progress: ProgressRecord[];
  customMarkers: CustomMarkerRecord[];
}
