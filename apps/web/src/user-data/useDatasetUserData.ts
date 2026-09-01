import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { CustomMarkerRecord, ProgressRecord } from '@morrowind-map/contracts';
import { liveQuery, type Subscription } from 'dexie';
import {
  userDatabase,
  type MorrowindMapDatabase,
} from '../storage/database';

export interface DatasetProgressSnapshot {
  readonly loading: boolean;
  readonly error: Error | null;
  readonly retry: () => void;
  readonly records: readonly ProgressRecord[];
  readonly byPlaceId: ReadonlyMap<string, ProgressRecord>;
}

export interface DatasetCustomMarkersSnapshot {
  readonly loading: boolean;
  readonly error: Error | null;
  readonly retry: () => void;
  readonly records: readonly CustomMarkerRecord[];
  readonly byId: ReadonlyMap<string, CustomMarkerRecord>;
}

interface LiveQueryState<T> {
  readonly querier: () => T | Promise<T>;
  readonly loading: boolean;
  readonly error: Error | null;
  readonly value: T;
}

interface RecoverableLiveQueryResult<T> {
  readonly loading: boolean;
  readonly error: Error | null;
  readonly retry: () => void;
  readonly value: T;
}

const EMPTY_PROGRESS_RECORDS: readonly ProgressRecord[] = [];
const EMPTY_CUSTOM_MARKERS: readonly CustomMarkerRecord[] = [];

function normalizeError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}

function useRecoverableLiveQuery<T>(
  querier: () => T | Promise<T>,
  emptyValue: T,
): RecoverableLiveQueryResult<T> {
  const generationRef = useRef(0);
  const [retryRevision, setRetryRevision] = useState(0);
  const [state, setState] = useState<LiveQueryState<T>>(() => ({
    querier,
    loading: true,
    error: null,
    value: emptyValue,
  }));

  const retry = useCallback(() => {
    generationRef.current += 1;
    setState({ querier, loading: true, error: null, value: emptyValue });
    setRetryRevision((current) => current + 1);
  }, [emptyValue, querier]);

  useEffect(() => {
    const generation = generationRef.current + 1;
    generationRef.current = generation;

    const next = (value: T) => {
      if (generationRef.current === generation) {
        setState({ querier, loading: false, error: null, value });
      }
    };
    const fail = (error: unknown) => {
      if (generationRef.current === generation) {
        setState({
          querier,
          loading: false,
          error: normalizeError(error),
          value: emptyValue,
        });
      }
    };

    let subscription: Subscription | null = null;
    try {
      subscription = liveQuery(querier).subscribe({ next, error: fail });
    } catch (error: unknown) {
      fail(error);
    }

    return () => {
      if (generationRef.current === generation) {
        generationRef.current += 1;
      }
      subscription?.unsubscribe();
    };
  }, [emptyValue, querier, retryRevision]);

  const current: LiveQueryState<T> = state.querier === querier
    ? state
    : { querier, loading: true, error: null, value: emptyValue };

  return {
    loading: current.loading,
    error: current.error,
    retry,
    value: current.value,
  };
}

function isVisibleMarker(marker: CustomMarkerRecord): boolean {
  return marker.deletedAt === null;
}

export function useDatasetProgress(
  datasetId: string,
  database: MorrowindMapDatabase = userDatabase,
): DatasetProgressSnapshot {
  const query = useCallback(
    () => database.progress.where('datasetId').equals(datasetId).toArray(),
    [database, datasetId],
  );
  const result = useRecoverableLiveQuery<readonly ProgressRecord[]>(
    query,
    EMPTY_PROGRESS_RECORDS,
  );
  const rows = result.value;
  const byPlaceId = useMemo<ReadonlyMap<string, ProgressRecord>>(
    () => new Map(rows.map((record) => [record.placeId, record])),
    [rows],
  );

  return {
    loading: result.loading,
    error: result.error,
    retry: result.retry,
    records: rows,
    byPlaceId,
  };
}

export function useDatasetCustomMarkers(
  datasetId: string,
  database: MorrowindMapDatabase = userDatabase,
): DatasetCustomMarkersSnapshot {
  const query = useCallback(
    () => database.customMarkers.where('datasetId').equals(datasetId).toArray(),
    [database, datasetId],
  );
  const result = useRecoverableLiveQuery<readonly CustomMarkerRecord[]>(
    query,
    EMPTY_CUSTOM_MARKERS,
  );
  const rows = result.value;
  const visibleRows = useMemo(
    () => rows.filter(isVisibleMarker),
    [rows],
  );
  const byId = useMemo<ReadonlyMap<string, CustomMarkerRecord>>(
    () => new Map(visibleRows.map((marker) => [marker.id, marker])),
    [visibleRows],
  );

  return {
    loading: result.loading,
    error: result.error,
    retry: result.retry,
    records: visibleRows,
    byId,
  };
}
