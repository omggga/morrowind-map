import type {
  CustomMarkerRecord,
  ImportReceipt,
  ProgressRecord,
} from '@morrowind-map/contracts';
import { createMimImportReceiptId } from '@morrowind-map/contracts';
import Dexie, { type EntityTable } from 'dexie';

export const DATABASE_NAME = 'morrowind-map';
export const DATABASE_SCHEMA_VERSION = 3;

const LEGACY_DATABASE_STORES = {
  progress: '&key,datasetId',
  customMarkers: '&id,datasetId',
  importReceipts: '&id,datasetId',
} as const;

const DATABASE_STORES = {
  ...LEGACY_DATABASE_STORES,
  datasetSnapshots: '&datasetId,snapshotId',
} as const;

export interface StoredDatasetSnapshot {
  readonly datasetId: string;
  readonly snapshotId: string;
  readonly boundAt: string;
  readonly bindingKind: 'fresh' | 'legacy-adoption' | 'mim-import' | 'backup-import';
}

export interface StoredProgressRecord extends ProgressRecord {
  readonly key: string;
}

export class MorrowindMapDatabase extends Dexie {
  readonly progress!: EntityTable<StoredProgressRecord, 'key'>;
  readonly customMarkers!: EntityTable<CustomMarkerRecord, 'id'>;
  readonly importReceipts!: EntityTable<ImportReceipt, 'id'>;
  readonly datasetSnapshots!: EntityTable<StoredDatasetSnapshot, 'datasetId'>;

  constructor(name = DATABASE_NAME) {
    super(name);
    this.version(1).stores(LEGACY_DATABASE_STORES);
    this.version(2)
      .stores(LEGACY_DATABASE_STORES)
      .upgrade(async (transaction) => {
        const receipts = transaction.table<ImportReceipt, string>('importReceipts');
        const legacyReceipts = (await receipts.toArray()).filter(
          (receipt) =>
            receipt.id !==
            createMimImportReceiptId(receipt.datasetId, receipt.sourceFingerprint),
        );
        if (legacyReceipts.length === 0) {
          return;
        }
        await receipts.bulkDelete(legacyReceipts.map(({ id }) => id));
        await receipts.bulkPut(
          legacyReceipts.map((receipt) => ({
            ...receipt,
            id: createMimImportReceiptId(receipt.datasetId, receipt.sourceFingerprint),
          })),
        );
      });
    this.version(DATABASE_SCHEMA_VERSION).stores(DATABASE_STORES);
    this.on('versionchange', () => this.close());
  }
}

export function progressKey(datasetId: string, placeId: string): string {
  return `${datasetId}\0${placeId}`;
}

export function mimReceiptId(datasetId: string, sourceFingerprint: string): string {
  return createMimImportReceiptId(datasetId, sourceFingerprint);
}

export const userDatabase = new MorrowindMapDatabase();
