import type { CustomMarkerRecord, ProgressRecord } from '@morrowind-map/contracts';
import Dexie, { type EntityTable } from 'dexie';
import { DATABASE_NAME } from './userDataNamespace';

export { DATABASE_NAME } from './userDataNamespace';

export const DATABASE_SCHEMA_VERSION = 1;

const DATABASE_STORES = {
  progress: '&key,datasetId',
  customMarkers: '&id,datasetId',
  datasetSnapshots: '&datasetId,snapshotId',
} as const;

export interface StoredDatasetSnapshot {
  readonly datasetId: string;
  readonly snapshotId: string;
  readonly boundAt: string;
  readonly bindingKind: 'fresh' | 'backup-import';
}

export interface StoredProgressRecord extends ProgressRecord {
  readonly key: string;
}

export class MorrowindMapDatabase extends Dexie {
  readonly progress!: EntityTable<StoredProgressRecord, 'key'>;
  readonly customMarkers!: EntityTable<CustomMarkerRecord, 'id'>;
  readonly datasetSnapshots!: EntityTable<StoredDatasetSnapshot, 'datasetId'>;

  constructor(name: string = DATABASE_NAME) {
    super(name);
    this.version(DATABASE_SCHEMA_VERSION).stores(DATABASE_STORES);
    this.on('versionchange', () => this.close());
  }
}

export function progressKey(datasetId: string, placeId: string): string {
  return `${datasetId}\0${placeId}`;
}

export const userDatabase = new MorrowindMapDatabase();
