import { act, cleanup, renderHook } from '@testing-library/react';
import type { CustomMarkerRecord, ProgressRecord } from '@morrowind-map/contracts';
import type { Observable, Observer, Subscription } from 'dexie';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MorrowindMapDatabase } from '../storage/database';
import {
  useDatasetCustomMarkers,
  useDatasetProgress,
} from './useDatasetUserData';

const { liveQueryMock } = vi.hoisted(() => ({
  liveQueryMock: vi.fn(),
}));

vi.mock('dexie', async () => {
  const actual = await vi.importActual<typeof import('dexie')>('dexie');
  return { ...actual, liveQuery: liveQueryMock };
});

class ControlledLiveQuery<T> {
  private observer: Partial<Observer<T>> | null = null;
  readonly unsubscribe = vi.fn();
  readonly observable = {
    subscribe: (observer: Partial<Observer<T>>): Subscription => {
      this.observer = observer;
      return {
        closed: false,
        unsubscribe: this.unsubscribe,
      };
    },
  } as Observable<T>;

  next(value: T): void {
    this.observer?.next?.(value);
  }

  fail(error: unknown): void {
    this.observer?.error?.(error);
  }
}

const datasetId = 'original-goty-hd';
const database = {} as MorrowindMapDatabase;
const sources: ControlledLiveQuery<unknown>[] = [];

const progressRecord: ProgressRecord = {
  datasetId,
  placeId: `${datasetId}.place-balmora`,
  status: 'active',
  note: 'Return later',
  updatedAt: '2026-09-01T10:00:00.000Z',
  provenance: { kind: 'manual', sourceFingerprint: null },
};

function marker(id: string, deletedAt: string | null = null): CustomMarkerRecord {
  return {
    id,
    datasetId,
    label: id,
    note: '',
    position: [10, 20],
    createdAt: '2026-09-01T10:00:00.000Z',
    updatedAt: '2026-09-01T10:00:00.000Z',
    deletedAt,
    provenance: { kind: 'manual', sourceFingerprint: null },
  };
}

function source<T>(index: number): ControlledLiveQuery<T> {
  return sources[index] as ControlledLiveQuery<T>;
}

describe('recoverable dataset live queries', () => {
  beforeEach(() => {
    sources.length = 0;
    liveQueryMock.mockReset();
    liveQueryMock.mockImplementation(() => {
      const controlled = new ControlledLiveQuery<unknown>();
      sources.push(controlled);
      return controlled.observable;
    });
  });

  afterEach(cleanup);

  it('returns progress values and recovers from an error through a fresh subscription', () => {
    const { result } = renderHook(() => useDatasetProgress(datasetId, database));
    const first = source<readonly ProgressRecord[]>(0);

    expect(result.current).toMatchObject({
      loading: true,
      error: null,
      records: [],
    });

    act(() => first.next([progressRecord]));
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.records).toEqual([progressRecord]);
    expect(result.current.byPlaceId.get(progressRecord.placeId)).toBe(progressRecord);

    const failure = new Error('IndexedDB unavailable');
    act(() => first.fail(failure));
    expect(result.current).toMatchObject({
      loading: false,
      error: failure,
      records: [],
    });
    expect(result.current.byPlaceId.size).toBe(0);

    act(() => result.current.retry());
    expect(first.unsubscribe).toHaveBeenCalledOnce();
    expect(sources).toHaveLength(2);
    expect(result.current).toMatchObject({ loading: true, error: null, records: [] });

    act(() => first.next([{ ...progressRecord, note: 'stale' }]));
    expect(result.current.records).toEqual([]);

    const recovered = { ...progressRecord, note: 'recovered' };
    act(() => source<readonly ProgressRecord[]>(1).next([recovered]));
    expect(result.current).toMatchObject({ loading: false, error: null });
    expect(result.current.records).toEqual([recovered]);
  });

  it('filters deleted markers and unsubscribes stale generations on dependency change and cleanup', () => {
    const { result, rerender, unmount } = renderHook(
      ({ currentDatasetId }) => useDatasetCustomMarkers(currentDatasetId, database),
      { initialProps: { currentDatasetId: datasetId } },
    );
    const first = source<readonly CustomMarkerRecord[]>(0);
    const visible = marker(`${datasetId}.custom.visible`);
    const deleted = marker(
      `${datasetId}.custom.deleted`,
      '2026-09-01T10:05:00.000Z',
    );

    act(() => first.next([visible, deleted]));
    expect(result.current.records).toEqual([visible]);
    expect(result.current.byId.get(visible.id)).toBe(visible);
    expect(result.current.byId.has(deleted.id)).toBe(false);

    rerender({ currentDatasetId: 'poison-song-26.08' });
    expect(first.unsubscribe).toHaveBeenCalledOnce();
    expect(sources).toHaveLength(2);
    expect(result.current).toMatchObject({ loading: true, error: null, records: [] });

    act(() => first.fail(new Error('stale failure')));
    expect(result.current.error).toBeNull();

    const second = source<readonly CustomMarkerRecord[]>(1);
    unmount();
    expect(second.unsubscribe).toHaveBeenCalledOnce();
    act(() => second.next([visible]));
  });
});
