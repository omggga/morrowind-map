import {
  PORTABLE_BACKUP_SCHEMA_VERSION,
  parsePortableBackup,
  type CustomMarkerRecord,
  type PortableBackup,
  type ProgressRecord,
  type ProgressStatus,
} from '@morrowind-map/contracts';
import type {
  MorrowindMapDatabase,
  StoredDatasetSnapshot,
  StoredProgressRecord,
} from './database';
import { progressKey } from './database';

export const MAX_NOTE_LENGTH = 10_000;
export const MAX_MARKER_LABEL_LENGTH = 512;

export interface ProgressPatch {
  readonly status?: ProgressStatus;
  readonly note?: string;
}

export interface CustomMarkerInput {
  readonly id?: string;
  readonly datasetId: string;
  readonly label: string;
  readonly note: string;
  readonly position: readonly [number, number];
}

export interface BackupImportResult {
  readonly progressImported: number;
  readonly progressSkipped: number;
  readonly markersImported: number;
  readonly markersSkipped: number;
}

export interface PortableBackupImportScope {
  readonly currentSnapshots: Readonly<Record<string, string>>;
  readonly knownPlaceIdsByDataset?: ReadonlyMap<string, ReadonlySet<string>>;
}

export interface DatasetSnapshotReadiness {
  readonly kind: 'ready';
}

function nowIso(now: () => Date): string {
  return now().toISOString();
}

function timestampEpoch(value: string): number {
  const epoch = Date.parse(value);
  if (!Number.isFinite(epoch)) {
    throw new Error(`Invalid timestamp: ${value}`);
  }
  return epoch;
}

function monotonicTimestamp(candidate: string, previous?: string): string {
  if (!previous) {
    return candidate;
  }
  const candidateEpoch = timestampEpoch(candidate);
  const previousEpoch = timestampEpoch(previous);
  return candidateEpoch > previousEpoch
    ? candidate
    : new Date(previousEpoch + 1).toISOString();
}

function compareTimestamps(left: string, right: string): number {
  return timestampEpoch(left) - timestampEpoch(right);
}

function manualProvenance() {
  return { kind: 'manual', sourceFingerprint: null } as const;
}

function withoutStorageKey(record: StoredProgressRecord): ProgressRecord {
  return {
    datasetId: record.datasetId,
    placeId: record.placeId,
    status: record.status,
    note: record.note,
    updatedAt: record.updatedAt,
    provenance: record.provenance,
  };
}

function snapshotMismatchMessage(
  datasetId: string,
  expectedSnapshotId: string,
  storedSnapshotId: string,
): string {
  return (
    `Local data for ${datasetId} belongs to snapshot ${storedSnapshotId}, ` +
    `not ${expectedSnapshotId}. An explicit migration or archive is required.`
  );
}

async function countDatasetRecords(
  database: MorrowindMapDatabase,
  datasetId: string,
): Promise<number> {
  const [progress, markers] = await Promise.all([
    database.progress.where('datasetId').equals(datasetId).count(),
    database.customMarkers.where('datasetId').equals(datasetId).count(),
  ]);
  return progress + markers;
}

async function bindEmptyDatasetSnapshot(
  database: MorrowindMapDatabase,
  datasetId: string,
  snapshotId: string,
  bindingKind: StoredDatasetSnapshot['bindingKind'],
  boundAt: string,
): Promise<void> {
  const existing = await database.datasetSnapshots.get(datasetId);
  if (existing) {
    if (existing.snapshotId !== snapshotId) {
      throw new Error(snapshotMismatchMessage(datasetId, snapshotId, existing.snapshotId));
    }
    return;
  }
  if ((await countDatasetRecords(database, datasetId)) > 0) {
    throw new Error(`Local data for ${datasetId} is missing its snapshot binding.`);
  }
  await database.datasetSnapshots.put({ datasetId, snapshotId, bindingKind, boundAt });
}

async function requireDatasetSnapshotBinding(
  database: MorrowindMapDatabase,
  datasetId: string,
): Promise<StoredDatasetSnapshot> {
  const binding = await database.datasetSnapshots.get(datasetId);
  if (!binding) {
    throw new Error(`Dataset ${datasetId} must be bound to a snapshot before editing local data.`);
  }
  return binding;
}

export async function ensureDatasetSnapshot(
  database: MorrowindMapDatabase,
  datasetId: string,
  snapshotId: string,
  now: () => Date = () => new Date(),
): Promise<DatasetSnapshotReadiness> {
  return database.transaction(
    'rw',
    database.datasetSnapshots,
    database.progress,
    database.customMarkers,
    async () => {
      const existing = await database.datasetSnapshots.get(datasetId);
      if (existing) {
        if (existing.snapshotId === snapshotId) {
          return { kind: 'ready' };
        }
        if ((await countDatasetRecords(database, datasetId)) > 0) {
          throw new Error(snapshotMismatchMessage(datasetId, snapshotId, existing.snapshotId));
        }
      } else if ((await countDatasetRecords(database, datasetId)) > 0) {
        throw new Error(`Local data for ${datasetId} is missing its snapshot binding.`);
      }
      await database.datasetSnapshots.put({
        datasetId,
        snapshotId,
        boundAt: nowIso(now),
        bindingKind: 'fresh',
      });
      return { kind: 'ready' };
    },
  );
}

export async function savePlaceProgress(
  database: MorrowindMapDatabase,
  datasetId: string,
  placeId: string,
  patch: ProgressPatch,
  now: () => Date = () => new Date(),
): Promise<ProgressRecord> {
  if (patch.note !== undefined && patch.note.length > MAX_NOTE_LENGTH) {
    throw new Error(`Note must not exceed ${MAX_NOTE_LENGTH} characters`);
  }
  const key = progressKey(datasetId, placeId);
  return database.transaction('rw', database.datasetSnapshots, database.progress, async () => {
    await requireDatasetSnapshotBinding(database, datasetId);
    const existing = await database.progress.get(key);
    const next: StoredProgressRecord = {
      key,
      datasetId,
      placeId,
      status: patch.status ?? existing?.status ?? 'unvisited',
      note: patch.note ?? existing?.note ?? '',
      updatedAt: monotonicTimestamp(nowIso(now), existing?.updatedAt),
      provenance: manualProvenance(),
    };
    await database.progress.put(next);
    return withoutStorageKey(next);
  });
}

export async function saveCustomMarker(
  database: MorrowindMapDatabase,
  input: CustomMarkerInput,
  now: () => Date = () => new Date(),
  createId: () => string = () => crypto.randomUUID(),
): Promise<CustomMarkerRecord> {
  const id = input.id ?? `${input.datasetId}.custom.${createId()}`;
  const label = input.label.trim();
  if (!id.startsWith(`${input.datasetId}.`)) {
    throw new Error('Custom marker id must be scoped to its dataset');
  }
  if (!label || label.length > MAX_MARKER_LABEL_LENGTH) {
    throw new Error(`Custom marker label must contain 1–${MAX_MARKER_LABEL_LENGTH} characters`);
  }
  if (input.note.length > MAX_NOTE_LENGTH) {
    throw new Error(`Note must not exceed ${MAX_NOTE_LENGTH} characters`);
  }
  if (!input.position.every(Number.isFinite)) {
    throw new Error('Custom marker position must contain finite coordinates');
  }
  return database.transaction('rw', database.datasetSnapshots, database.customMarkers, async () => {
    await requireDatasetSnapshotBinding(database, input.datasetId);
    const existing = await database.customMarkers.get(id);
    if (existing && existing.datasetId !== input.datasetId) {
      throw new Error('Custom marker belongs to a different dataset');
    }
    if (existing?.deletedAt !== null && existing?.deletedAt !== undefined) {
      throw new Error('Deleted custom markers must be restored explicitly');
    }
    const timestamp = monotonicTimestamp(nowIso(now), existing?.updatedAt);
    const marker: CustomMarkerRecord = {
      id,
      datasetId: input.datasetId,
      label,
      note: input.note,
      position: [input.position[0], input.position[1]],
      createdAt: existing?.createdAt ?? timestamp,
      updatedAt: timestamp,
      deletedAt: null,
      provenance: manualProvenance(),
    };
    await database.customMarkers.put(marker);
    return marker;
  });
}

export async function deleteCustomMarker(
  database: MorrowindMapDatabase,
  markerId: string,
  now: () => Date = () => new Date(),
): Promise<void> {
  await database.transaction('rw', database.datasetSnapshots, database.customMarkers, async () => {
    const existing = await database.customMarkers.get(markerId);
    if (!existing) {
      return;
    }
    await requireDatasetSnapshotBinding(database, existing.datasetId);
    const timestamp = monotonicTimestamp(nowIso(now), existing.updatedAt);
    await database.customMarkers.put({
      ...existing,
      updatedAt: timestamp,
      deletedAt: timestamp,
      provenance: manualProvenance(),
    });
  });
}

export async function createPortableBackup(
  database: MorrowindMapDatabase,
  datasets: Readonly<Record<string, string>>,
  now: () => Date = () => new Date(),
): Promise<PortableBackup> {
  const datasetIds = new Set(Object.keys(datasets));
  const [allProgress, allMarkers, allBindings] = await database.transaction(
    'r',
    database.datasetSnapshots,
    database.progress,
    database.customMarkers,
    async () =>
      Promise.all([
        database.progress.toArray(),
        database.customMarkers.toArray(),
        database.datasetSnapshots.toArray(),
      ]),
  );
  const storedProgress = allProgress.filter(({ datasetId }) => datasetIds.has(datasetId));
  const customMarkers = allMarkers.filter(({ datasetId }) => datasetIds.has(datasetId));
  const bindingsByDataset = new Map(
    allBindings
      .filter(({ datasetId }) => datasetIds.has(datasetId))
      .map((binding) => [binding.datasetId, binding]),
  );
  for (const datasetId of new Set(
    [...storedProgress, ...customMarkers].map((record) => record.datasetId),
  )) {
    const binding = bindingsByDataset.get(datasetId);
    if (!binding) {
      throw new Error(`Local data for ${datasetId} is not bound to a dataset snapshot.`);
    }
    if (binding.snapshotId !== datasets[datasetId]) {
      throw new Error(
        snapshotMismatchMessage(datasetId, datasets[datasetId] ?? '(missing)', binding.snapshotId),
      );
    }
  }
  return parsePortableBackup({
    schemaVersion: PORTABLE_BACKUP_SCHEMA_VERSION,
    kind: 'morrowind-map-backup',
    exportedAt: nowIso(now),
    datasets: { ...datasets },
    progress: storedProgress
      .map(withoutStorageKey)
      .sort((left, right) =>
        `${left.datasetId}\0${left.placeId}`.localeCompare(`${right.datasetId}\0${right.placeId}`),
      ),
    customMarkers: customMarkers.sort((left, right) => left.id.localeCompare(right.id)),
  });
}

export async function importPortableBackup(
  database: MorrowindMapDatabase,
  input: unknown,
  scope: PortableBackupImportScope,
): Promise<BackupImportResult> {
  const backup = parsePortableBackup(input);
  for (const [datasetId, snapshotId] of Object.entries(backup.datasets)) {
    const currentSnapshotId = scope.currentSnapshots[datasetId];
    if (!currentSnapshotId) {
      throw new Error(`Backup contains an unknown dataset: ${datasetId}`);
    }
    if (currentSnapshotId !== snapshotId) {
      throw new Error(
        `Backup snapshot mismatch for ${datasetId}: expected ${currentSnapshotId}, received ${snapshotId}`,
      );
    }
  }
  const unknownPlace = backup.progress.find(({ datasetId, placeId }) => {
    const knownPlaceIds = scope.knownPlaceIdsByDataset?.get(datasetId);
    return knownPlaceIds ? !knownPlaceIds.has(placeId) : false;
  });
  if (unknownPlace) {
    throw new Error(`Backup contains an unknown place: ${unknownPlace.placeId}`);
  }
  return database.transaction(
    'rw',
    database.datasetSnapshots,
    database.progress,
    database.customMarkers,
    async () => {
      const touchedDatasetIds = new Set([
        ...backup.progress.map(({ datasetId }) => datasetId),
        ...backup.customMarkers.map(({ datasetId }) => datasetId),
      ]);
      for (const datasetId of touchedDatasetIds) {
        await bindEmptyDatasetSnapshot(
          database,
          datasetId,
          backup.datasets[datasetId] ?? '',
          'backup-import',
          backup.exportedAt,
        );
      }
      let progressImported = 0;
      let progressSkipped = 0;
      let markersImported = 0;
      let markersSkipped = 0;
      for (const incoming of backup.progress) {
        const key = progressKey(incoming.datasetId, incoming.placeId);
        const existing = await database.progress.get(key);
        if (existing && compareTimestamps(existing.updatedAt, incoming.updatedAt) >= 0) {
          progressSkipped += 1;
          continue;
        }
        await database.progress.put({ key, ...incoming });
        progressImported += 1;
      }
      for (const incoming of backup.customMarkers) {
        const existing = await database.customMarkers.get(incoming.id);
        const comparison = existing ? compareTimestamps(existing.updatedAt, incoming.updatedAt) : -1;
        const existingWinsTie =
          comparison === 0 && (existing?.deletedAt !== null || incoming.deletedAt === null);
        if (existing && (comparison > 0 || existingWinsTie)) {
          markersSkipped += 1;
          continue;
        }
        await database.customMarkers.put(incoming);
        markersImported += 1;
      }
      return { progressImported, progressSkipped, markersImported, markersSkipped };
    },
  );
}
