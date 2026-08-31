import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DATABASE_NAME, MorrowindMapDatabase, progressKey } from './database';
import {
  createPortableBackup,
  deleteCustomMarker,
  ensureDatasetSnapshot,
  importPortableBackup,
  saveCustomMarker,
  savePlaceProgress,
} from './userData';

const datasetId = 'original-goty-hd';
const snapshotId = 'original:goty:fff441f864a7f73e';
const placeId = 'original-goty-hd.place-fixture';
const secondDatasetId = 'poison-song-26.08';
const secondSnapshotId = 'tr:poison-song-26.08:6964517551e0fcb0';
const secondPlaceId = 'poison-song-26.08.place-fixture';
const at = (iso: string) => () => new Date(iso);

function backupScope(knownPlaces: ReadonlySet<string> = new Set([placeId])) {
  return {
    currentSnapshots: {
      [datasetId]: snapshotId,
      [secondDatasetId]: secondSnapshotId,
    },
    knownPlaceIdsByDataset: new Map([[datasetId, knownPlaces]]),
  };
}

describe('Dexie user data storage', () => {
  let database: MorrowindMapDatabase;
  let databaseName: string;

  beforeEach(async () => {
    databaseName = `morrowind-map-test-${crypto.randomUUID()}`;
    database = new MorrowindMapDatabase(databaseName);
    await ensureDatasetSnapshot(database, datasetId, snapshotId);
  });

  afterEach(async () => {
    database.close();
    await database.delete();
  });

  it('uses a fresh two-map EN epoch instead of opening the retired database', async () => {
    expect(DATABASE_NAME).toBe('morrowind-map-two-map-en-v1');

    const retired = new MorrowindMapDatabase(`${databaseName}-retired`);
    const current = new MorrowindMapDatabase(`${databaseName}-current`);
    try {
      await ensureDatasetSnapshot(retired, secondDatasetId, secondSnapshotId);
      await savePlaceProgress(retired, secondDatasetId, secondPlaceId, {
        status: 'visited',
        note: 'Retired state',
      });

      expect(await current.progress.count()).toBe(0);
      expect(await retired.progress.count()).toBe(1);
    } finally {
      retired.close();
      current.close();
      await retired.delete();
      await current.delete();
    }
  });

  it('keeps status, note and custom markers after closing and reopening the current database', async () => {
    await savePlaceProgress(
      database,
      datasetId,
      placeId,
      { status: 'active', note: 'Return later' },
      at('2026-08-31T12:00:00.000Z'),
    );
    await saveCustomMarker(
      database,
      { datasetId, label: 'Supply cache', note: 'Chest', position: [10, 20] },
      at('2026-08-31T12:00:01.000Z'),
      () => 'fixture',
    );
    database.close();

    database = new MorrowindMapDatabase(databaseName);

    await expect(database.progress.get(progressKey(datasetId, placeId))).resolves.toMatchObject({
      status: 'active',
      note: 'Return later',
    });
    await expect(database.customMarkers.toArray()).resolves.toEqual([
      expect.objectContaining({
        id: 'original-goty-hd.custom.fixture',
        label: 'Supply cache',
        position: [10, 20],
      }),
    ]);
  });

  it('round-trips a manual-only v3 JSON backup without creating duplicates', async () => {
    await savePlaceProgress(
      database,
      datasetId,
      placeId,
      { status: 'visited', note: 'Complete' },
      at('2026-08-31T12:00:00.000Z'),
    );
    const backup = await createPortableBackup(
      database,
      { [datasetId]: snapshotId },
      at('2026-08-31T12:05:00.000Z'),
    );
    const target = new MorrowindMapDatabase(`${databaseName}-restore`);
    try {
      const first = await importPortableBackup(target, backup, backupScope());
      const second = await importPortableBackup(target, backup, backupScope());

      expect(backup).not.toHaveProperty('importReceipts');
      expect(backup.schemaVersion).toBe(3);
      expect(first.progressImported).toBe(1);
      expect(second).toMatchObject({ progressImported: 0, progressSkipped: 1 });
      expect(await target.progress.count()).toBe(1);
      expect(await target.datasetSnapshots.get(datasetId)).toMatchObject({
        snapshotId,
        bindingKind: 'backup-import',
      });
    } finally {
      target.close();
      await target.delete();
    }
  });

  it('exports only active dataset scope and ignores retired rows without deleting them', async () => {
    await savePlaceProgress(database, datasetId, placeId, { status: 'visited' });
    await ensureDatasetSnapshot(database, secondDatasetId, secondSnapshotId);
    await savePlaceProgress(database, secondDatasetId, secondPlaceId, { status: 'active' });

    const originalOnly = await createPortableBackup(database, { [datasetId]: snapshotId });

    expect(originalOnly.progress.map((record) => record.datasetId)).toEqual([datasetId]);
    expect(await database.progress.where('datasetId').equals(secondDatasetId).count()).toBe(1);
  });

  it('rejects a snapshot change with data but rebinds an empty dataset', async () => {
    await savePlaceProgress(database, datasetId, placeId, { status: 'visited' });
    await expect(
      ensureDatasetSnapshot(database, datasetId, 'original:goty:newer'),
    ).rejects.toThrow('explicit migration or archive');

    await ensureDatasetSnapshot(database, secondDatasetId, secondSnapshotId);
    await expect(
      ensureDatasetSnapshot(database, secondDatasetId, 'tr:poison-song:newer'),
    ).resolves.toEqual({ kind: 'ready' });
    expect(await database.datasetSnapshots.get(secondDatasetId)).toMatchObject({
      snapshotId: 'tr:poison-song:newer',
      bindingKind: 'fresh',
    });
  });

  it('rejects old backup contracts, incompatible snapshots and unknown places before writing', async () => {
    await savePlaceProgress(database, datasetId, placeId, { status: 'visited' });
    const backup = await createPortableBackup(database, { [datasetId]: snapshotId });
    const target = new MorrowindMapDatabase(`${databaseName}-reject`);
    try {
      await expect(
        importPortableBackup(target, { ...backup, schemaVersion: 2 }, backupScope()),
      ).rejects.toThrow();
      await expect(
        importPortableBackup(target, backup, {
          currentSnapshots: { [datasetId]: 'original:goty:newer' },
          knownPlaceIdsByDataset: new Map([[datasetId, new Set([placeId])]]),
        }),
      ).rejects.toThrow('snapshot mismatch');
      await expect(
        importPortableBackup(target, backup, backupScope(new Set())),
      ).rejects.toThrow('unknown place');
      expect(await target.progress.count()).toBe(0);
    } finally {
      target.close();
      await target.delete();
    }
  });

  it('orders timestamps chronologically and makes local revisions strictly newer', async () => {
    const oldBackup = {
      schemaVersion: 3,
      kind: 'morrowind-map-backup',
      exportedAt: '2026-08-31T12:00:01Z',
      datasets: { [datasetId]: snapshotId },
      progress: [
        {
          datasetId,
          placeId,
          status: 'unvisited',
          note: 'old',
          updatedAt: '2026-08-31T12:00:00Z',
          provenance: { kind: 'manual', sourceFingerprint: null },
        },
      ],
      customMarkers: [],
    } as const;
    const newerBackup = {
      ...oldBackup,
      exportedAt: '2026-08-31T12:00:02Z',
      progress: [
        {
          ...oldBackup.progress[0],
          note: 'newer',
          updatedAt: '2026-08-31T12:00:00.500Z',
        },
      ],
    } as const;

    await importPortableBackup(database, oldBackup, backupScope());
    await importPortableBackup(database, newerBackup, backupScope());
    expect(await database.progress.get(progressKey(datasetId, placeId))).toMatchObject({
      note: 'newer',
      updatedAt: '2026-08-31T12:00:00.500Z',
    });

    const local = await savePlaceProgress(
      database,
      datasetId,
      placeId,
      { note: 'local' },
      at('2026-08-31T12:00:00.500Z'),
    );
    expect(local.updatedAt).toBe('2026-08-31T12:00:00.501Z');
  });

  it('does not resurrect a marker when delete wins a concurrent transaction', async () => {
    const marker = await saveCustomMarker(
      database,
      { datasetId, label: 'Marker', note: '', position: [1, 2] },
      at('2026-08-31T12:00:00.000Z'),
      () => 'concurrent',
    );

    const deleting = deleteCustomMarker(
      database,
      marker.id,
      at('2026-08-31T12:00:01.000Z'),
    );
    const editing = saveCustomMarker(
      database,
      { ...marker, label: 'Stale edit' },
      at('2026-08-31T12:00:02.000Z'),
    );
    const [, editResult] = await Promise.allSettled([deleting, editing]);

    expect(editResult).toMatchObject({ status: 'rejected' });
    expect(await database.customMarkers.get(marker.id)).toMatchObject({
      deletedAt: '2026-08-31T12:00:01.000Z',
      label: 'Marker',
    });
  });
});
