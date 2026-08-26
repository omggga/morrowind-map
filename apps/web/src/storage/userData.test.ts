import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createMimImportReceiptId } from '@morrowind-map/contracts';
import Dexie from 'dexie';
import { MorrowindMapDatabase, progressKey } from './database';
import {
  applyMimImport,
  adoptLegacyDatasetSnapshots,
  createPortableBackup,
  deleteCustomMarker,
  ensureDatasetSnapshot,
  importPortableBackup,
  saveCustomMarker,
  savePlaceProgress,
} from './userData';

const datasetId = 'original-goty';
const snapshotId = 'original:goty:fixture';
const placeId = 'original-goty.vvardenfell.mim-0000';
const secondDatasetId = 'fullrest-25.08';
const secondSnapshotId = 'fullrest:25.08:fixture';
const secondPlaceId = 'fullrest-25.08.mainland.fixture-0000';
const fingerprint = 'a'.repeat(64);
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

function mimBundle(nextFingerprint = fingerprint) {
  return {
    schemaVersion: 1,
    kind: 'mim-progress',
    targetDatasetId: datasetId,
    targetSnapshotId: snapshotId,
    sourceFingerprint: nextFingerprint,
    sourceFiles: [{ path: 'mim_morrowind/user.gdb', sha256: 'b'.repeat(64) }],
    progress: [{ placeId, status: 'visited', note: 'ф' }],
    customMarkers: [
      {
        id: 'original-goty.custom.mim-0000',
        label: 'Дом с силовым полем',
        note: '',
        position: [59_590, 184_171],
      },
    ],
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

  it('keeps status, note and custom markers after closing and reopening the database', async () => {
    await savePlaceProgress(
      database,
      datasetId,
      placeId,
      { status: 'active', note: 'Вернуться позже' },
      at('2026-08-26T20:00:00.000Z'),
    );
    await saveCustomMarker(
      database,
      { datasetId, label: 'Моя отметка', note: 'сундук', position: [10, 20] },
      at('2026-08-26T20:00:01.000Z'),
      () => 'fixture',
    );
    database.close();

    database = new MorrowindMapDatabase(databaseName);
    const progress = await database.progress.get(progressKey(datasetId, placeId));
    const markers = await database.customMarkers.toArray();

    expect(progress).toMatchObject({ status: 'active', note: 'Вернуться позже' });
    expect(markers).toEqual([
      expect.objectContaining({
        id: 'original-goty.custom.fixture',
        label: 'Моя отметка',
        position: [10, 20],
      }),
    ]);
  });

  it('migrates legacy MIM receipt keys without losing duplicate protection', async () => {
    database.close();
    await database.delete();
    const legacy = new Dexie(databaseName);
    legacy.version(1).stores({
      progress: '&key,datasetId',
      customMarkers: '&id,datasetId',
      importReceipts: '&id,datasetId',
    });
    await legacy.table('importReceipts').put({
      id: `mim:${datasetId}:${fingerprint}`,
      datasetId,
      sourceKind: 'mim',
      sourceFingerprint: fingerprint,
      importedAt: '2026-08-26T20:00:00.000Z',
    });
    legacy.close();

    database = new MorrowindMapDatabase(databaseName);
    const receipts = await database.importReceipts.toArray();

    expect(database.verno).toBe(3);
    expect(receipts).toEqual([
      expect.objectContaining({
        id: createMimImportReceiptId(datasetId, fingerprint),
        sourceFingerprint: fingerprint,
      }),
    ]);
  });

  it('imports a MIM run once and protects later manual edits from a new run', async () => {
    const knownPlaces = new Set([placeId]);
    const first = await applyMimImport(
      database,
      mimBundle(),
      datasetId,
      snapshotId,
      knownPlaces,
      at('2026-08-26T20:00:00.000Z'),
    );
    const duplicate = await applyMimImport(
      database,
      mimBundle(),
      datasetId,
      snapshotId,
      knownPlaces,
      at('2026-08-26T20:01:00.000Z'),
    );

    expect(first).toMatchObject({ duplicate: false, progressImported: 1, markersImported: 1 });
    expect(duplicate).toMatchObject({ duplicate: true, progressImported: 0, markersImported: 0 });
    await savePlaceProgress(
      database,
      datasetId,
      placeId,
      { status: 'active' },
      at('2026-08-26T20:02:00.000Z'),
    );
    const nextRun = await applyMimImport(
      database,
      mimBundle('c'.repeat(64)),
      datasetId,
      snapshotId,
      knownPlaces,
      at('2026-08-26T20:03:00.000Z'),
    );

    expect(nextRun.progressSkipped).toBe(1);
    expect(await database.progress.get(progressKey(datasetId, placeId))).toMatchObject({
      status: 'active',
      note: 'ф',
      provenance: { kind: 'manual', sourceFingerprint: null },
    });

    await deleteCustomMarker(
      database,
      'original-goty.custom.mim-0000',
      at('2026-08-26T20:04:00.000Z'),
    );
    const afterDeletion = await applyMimImport(
      database,
      mimBundle('d'.repeat(64)),
      datasetId,
      snapshotId,
      knownPlaces,
      at('2026-08-26T20:05:00.000Z'),
    );

    expect(afterDeletion.markersSkipped).toBe(1);
    expect(await database.customMarkers.get('original-goty.custom.mim-0000')).toMatchObject({
      deletedAt: '2026-08-26T20:04:00.000Z',
      provenance: { kind: 'manual', sourceFingerprint: null },
    });
  });

  it('round-trips a portable JSON backup without creating duplicates', async () => {
    await savePlaceProgress(
      database,
      datasetId,
      placeId,
      { status: 'visited', note: 'готово' },
      at('2026-08-26T20:00:00.000Z'),
    );
    const backup = await createPortableBackup(
      database,
      { [datasetId]: snapshotId },
      at('2026-08-26T20:05:00.000Z'),
    );
    const target = new MorrowindMapDatabase(`${databaseName}-restore`);
    try {
      const first = await importPortableBackup(target, backup, backupScope());
      const second = await importPortableBackup(target, backup, backupScope());

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

  it('exports every registered dataset and refuses to omit unknown stored data', async () => {
    await savePlaceProgress(database, datasetId, placeId, { status: 'visited' });
    await ensureDatasetSnapshot(database, secondDatasetId, secondSnapshotId);
    await savePlaceProgress(database, secondDatasetId, secondPlaceId, { status: 'active' });

    const complete = await createPortableBackup(database, {
      [datasetId]: snapshotId,
      [secondDatasetId]: secondSnapshotId,
    });

    expect(complete.progress.map(({ datasetId: recordDatasetId }) => recordDatasetId)).toEqual([
      secondDatasetId,
      datasetId,
    ]);
    expect(complete.schemaVersion).toBe(2);
    await expect(
      createPortableBackup(database, { [datasetId]: snapshotId }),
    ).rejects.toThrow('missing snapshot metadata');
  });

  it('requires explicit adoption for unbound legacy data and rejects a later snapshot', async () => {
    const legacyName = `${databaseName}-legacy-binding`;
    const legacy = new Dexie(legacyName);
    legacy.version(2).stores({
      progress: '&key,datasetId',
      customMarkers: '&id,datasetId',
      importReceipts: '&id,datasetId',
    });
    await legacy.table('progress').put({
      key: progressKey(datasetId, placeId),
      datasetId,
      placeId,
      status: 'visited',
      note: '',
      updatedAt: '2026-08-26T20:00:00.000Z',
      provenance: { kind: 'manual', sourceFingerprint: null },
    });
    await legacy.table('progress').put({
      key: progressKey(secondDatasetId, secondPlaceId),
      datasetId: secondDatasetId,
      placeId: secondPlaceId,
      status: 'active',
      note: '',
      updatedAt: '2026-08-26T20:00:00.000Z',
      provenance: { kind: 'manual', sourceFingerprint: null },
    });
    legacy.close();

    const upgraded = new MorrowindMapDatabase(legacyName);
    try {
      await expect(ensureDatasetSnapshot(upgraded, datasetId, snapshotId)).resolves.toEqual({
        kind: 'needs-legacy-adoption',
        storedRecords: 1,
      });
      expect(await upgraded.datasetSnapshots.get(datasetId)).toBeUndefined();
      await expect(
        ensureDatasetSnapshot(upgraded, secondDatasetId, secondSnapshotId),
      ).resolves.toEqual({ kind: 'needs-legacy-adoption', storedRecords: 1 });

      await adoptLegacyDatasetSnapshots(upgraded, [
        { datasetId, snapshotId },
        { datasetId: secondDatasetId, snapshotId: secondSnapshotId },
      ]);
      expect(await upgraded.datasetSnapshots.get(datasetId)).toMatchObject({
        snapshotId,
        bindingKind: 'legacy-adoption',
      });
      expect(await upgraded.datasetSnapshots.get(secondDatasetId)).toMatchObject({
        snapshotId: secondSnapshotId,
        bindingKind: 'legacy-adoption',
      });
      await expect(
        createPortableBackup(upgraded, {
          [datasetId]: snapshotId,
          [secondDatasetId]: secondSnapshotId,
        }),
      ).resolves.toMatchObject({ schemaVersion: 2 });
      await expect(
        createPortableBackup(upgraded, {
          [datasetId]: 'original:goty:newer',
          [secondDatasetId]: secondSnapshotId,
        }),
      ).rejects.toThrow('explicit migration or archive');
      await expect(
        ensureDatasetSnapshot(upgraded, datasetId, 'original:goty:newer'),
      ).rejects.toThrow('explicit migration or archive');
    } finally {
      upgraded.close();
      await upgraded.delete();
    }
  });

  it('rejects an incompatible snapshot or unknown place before writing anything', async () => {
    await savePlaceProgress(database, datasetId, placeId, { status: 'visited' });
    const backup = await createPortableBackup(database, { [datasetId]: snapshotId });
    const target = new MorrowindMapDatabase(`${databaseName}-reject`);
    try {
      await expect(
        importPortableBackup(target, backup, {
          currentSnapshots: { [datasetId]: 'original:goty:newer' },
          knownPlaceIdsByDataset: new Map([[datasetId, new Set([placeId])]]),
        }),
      ).rejects.toThrow('snapshot mismatch');
      expect(await target.progress.count()).toBe(0);

      await expect(
        importPortableBackup(target, backup, backupScope(new Set())),
      ).rejects.toThrow('unknown place');
      expect(await target.progress.count()).toBe(0);
    } finally {
      target.close();
      await target.delete();
    }
  });

  it('orders timestamp variants chronologically and makes local revisions strictly newer', async () => {
    const oldBackup = {
      schemaVersion: 1,
      kind: 'morrowind-map-backup',
      exportedAt: '2026-08-26T20:00:01Z',
      datasets: { [datasetId]: snapshotId },
      progress: [
        {
          datasetId,
          placeId,
          status: 'unvisited',
          note: 'old',
          updatedAt: '2026-08-26T20:00:00Z',
          provenance: { kind: 'manual', sourceFingerprint: null },
        },
      ],
      customMarkers: [],
      importReceipts: [],
    } as const;
    const newerBackup = {
      ...oldBackup,
      exportedAt: '2026-08-26T20:00:02Z',
      progress: [{ ...oldBackup.progress[0], note: 'newer', updatedAt: '2026-08-26T20:00:00.500Z' }],
    } as const;

    await importPortableBackup(database, oldBackup, backupScope());
    await importPortableBackup(database, newerBackup, backupScope());
    expect(await database.progress.get(progressKey(datasetId, placeId))).toMatchObject({
      note: 'newer',
      updatedAt: '2026-08-26T20:00:00.500Z',
    });

    const local = await savePlaceProgress(
      database,
      datasetId,
      placeId,
      { note: 'local' },
      at('2026-08-26T20:00:00.500Z'),
    );
    expect(local.updatedAt).toBe('2026-08-26T20:00:00.501Z');
  });

  it('does not resurrect a marker when delete wins a concurrent transaction', async () => {
    const marker = await saveCustomMarker(
      database,
      { datasetId, label: 'Marker', note: '', position: [1, 2] },
      at('2026-08-26T20:00:00.000Z'),
      () => 'concurrent',
    );

    const deleting = deleteCustomMarker(
      database,
      marker.id,
      at('2026-08-26T20:00:01.000Z'),
    );
    const editing = saveCustomMarker(
      database,
      { ...marker, label: 'Stale edit' },
      at('2026-08-26T20:00:02.000Z'),
    );
    const [, editResult] = await Promise.allSettled([deleting, editing]);

    expect(editResult).toMatchObject({ status: 'rejected' });
    expect(await database.customMarkers.get(marker.id)).toMatchObject({
      deletedAt: '2026-08-26T20:00:01.000Z',
      label: 'Marker',
    });
  });

  it('soft-deletes imported markers removed from a later MIM snapshot', async () => {
    const knownPlaces = new Set([placeId]);
    await applyMimImport(
      database,
      mimBundle(),
      datasetId,
      snapshotId,
      knownPlaces,
      at('2026-08-26T20:00:00.000Z'),
    );
    const nextBundle = { ...mimBundle('c'.repeat(64)), customMarkers: [] };

    const result = await applyMimImport(
      database,
      nextBundle,
      datasetId,
      snapshotId,
      knownPlaces,
      at('2026-08-26T20:01:00.000Z'),
    );

    expect(result.markersRemoved).toBe(1);
    expect(await database.customMarkers.get('original-goty.custom.mim-0000')).toMatchObject({
      deletedAt: '2026-08-26T20:01:00.000Z',
      provenance: { kind: 'mim-import', sourceFingerprint: 'c'.repeat(64) },
    });
  });
});
