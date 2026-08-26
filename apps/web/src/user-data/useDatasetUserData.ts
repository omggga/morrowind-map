import { useMemo } from 'react';
import type { CustomMarkerRecord, ProgressRecord } from '@morrowind-map/contracts';
import { useLiveQuery } from 'dexie-react-hooks';
import {
  userDatabase,
  type MorrowindMapDatabase,
} from '../storage/database';

export interface DatasetProgressSnapshot {
  readonly loading: boolean;
  readonly records: readonly ProgressRecord[];
  readonly byPlaceId: ReadonlyMap<string, ProgressRecord>;
}

export interface DatasetCustomMarkersSnapshot {
  readonly loading: boolean;
  readonly records: readonly CustomMarkerRecord[];
  readonly byId: ReadonlyMap<string, CustomMarkerRecord>;
}

function isVisibleMarker(marker: CustomMarkerRecord): boolean {
  return marker.deletedAt === null;
}

export function useDatasetProgress(
  datasetId: string,
  database: MorrowindMapDatabase = userDatabase,
): DatasetProgressSnapshot {
  const rows = useLiveQuery(
    () => database.progress.where('datasetId').equals(datasetId).toArray(),
    [database, datasetId],
  );
  const byPlaceId = useMemo<ReadonlyMap<string, ProgressRecord>>(
    () => new Map((rows ?? []).map((record) => [record.placeId, record])),
    [rows],
  );

  return {
    loading: rows === undefined,
    records: rows ?? [],
    byPlaceId,
  };
}

export function useDatasetCustomMarkers(
  datasetId: string,
  database: MorrowindMapDatabase = userDatabase,
): DatasetCustomMarkersSnapshot {
  const rows = useLiveQuery(
    () => database.customMarkers.where('datasetId').equals(datasetId).toArray(),
    [database, datasetId],
  );
  const visibleRows = useMemo(
    () => (rows ?? []).filter(isVisibleMarker),
    [rows],
  );
  const byId = useMemo<ReadonlyMap<string, CustomMarkerRecord>>(
    () => new Map(visibleRows.map((marker) => [marker.id, marker])),
    [visibleRows],
  );

  return {
    loading: rows === undefined,
    records: visibleRows,
    byId,
  };
}
