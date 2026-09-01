import type {
  PlaceRecord,
  PlaceType,
  ProgressRecord,
  ProgressStatus,
} from '@morrowind-map/contracts';
import { describe, expect, it } from 'vitest';
import type { PlaceView } from './placeSearch';
import {
  PLACE_TYPE_ORDER,
  PROGRESS_STATUS_ORDER,
  comparePlaceLabelPriority,
  getAvailablePlaceTypes,
  isPlaceVisible,
  progressStatusFor,
  type PlaceFilterState,
} from './placeFilters';

function place(
  id: string,
  type: PlaceType,
  options: { readonly regionId?: string; readonly minZoom?: number } = {},
): PlaceView {
  const record = {
    id,
    regionId: options.regionId ?? 'vvardenfell',
    type,
    mapPosition: [0, 0],
    exteriorCell: [0, 0],
    mimCategory: null,
    minZoom: options.minZoom ?? 2,
    entrances: [],
    sources: [],
  } satisfies PlaceRecord;
  return {
    id,
    place: record,
    locale: 'en',
    name: id,
    aliases: [],
    searchableType: type,
  };
}

function progress(placeId: string, status: ProgressStatus): ProgressRecord {
  return {
    datasetId: 'fixture',
    placeId,
    status,
    note: '',
    updatedAt: '2026-09-01T00:00:00.000Z',
    provenance: { kind: 'manual', sourceFingerprint: null },
  };
}

function filters(
  overrides: Partial<PlaceFilterState> = {},
): PlaceFilterState {
  return {
    regionId: 'all',
    types: new Set(PLACE_TYPE_ORDER),
    statuses: new Set(PROGRESS_STATUS_ORDER),
    ...overrides,
  };
}

describe('place filter model', () => {
  it('publishes the documented deterministic type and progress order', () => {
    expect(PLACE_TYPE_ORDER).toEqual([
      'settlement',
      'landmark',
      'stronghold',
      'dwemer-ruin',
      'temple',
      'shrine',
      'mine',
      'cave',
      'ancestral-tomb',
      'ship',
      'guild',
      'shop',
      'house',
      'other',
    ]);
    expect(PROGRESS_STATUS_ORDER).toEqual(['active', 'unvisited', 'visited']);
  });

  it('treats missing progress as unvisited and returns stored progress otherwise', () => {
    const records = new Map<string, ProgressRecord>([
      ['active-place', progress('active-place', 'active')],
    ]);

    expect(progressStatusFor('missing-place', records)).toBe('unvisited');
    expect(progressStatusFor('active-place', records)).toBe('active');
  });

  it('returns only present types in canonical priority order', () => {
    const places = [
      place('house-b', 'house'),
      place('settlement-a', 'settlement'),
      place('house-a', 'house'),
      place('cave-a', 'cave'),
    ];

    expect(getAvailablePlaceTypes(places)).toEqual(['settlement', 'cave', 'house']);
  });

  it('applies OR within type and status axes and AND across region, type, status, and minZoom', () => {
    const candidate = place('target', 'cave', { regionId: 'solstheim', minZoom: 4 });
    const progressByPlaceId = new Map<string, ProgressRecord>([
      [candidate.id, progress(candidate.id, 'active')],
    ]);
    const matchingFilters = filters({
      regionId: 'solstheim',
      types: new Set<PlaceType>(['cave', 'mine']),
      statuses: new Set<ProgressStatus>(['active', 'visited']),
    });

    expect(isPlaceVisible(candidate, {
      filters: matchingFilters,
      zoom: 4,
      progressByPlaceId,
    })).toBe(true);
    expect(isPlaceVisible(candidate, {
      filters: { ...matchingFilters, regionId: 'vvardenfell' },
      zoom: 4,
      progressByPlaceId,
    })).toBe(false);
    expect(isPlaceVisible(candidate, {
      filters: { ...matchingFilters, types: new Set<PlaceType>(['mine']) },
      zoom: 4,
      progressByPlaceId,
    })).toBe(false);
    expect(isPlaceVisible(candidate, {
      filters: { ...matchingFilters, statuses: new Set<ProgressStatus>(['visited']) },
      zoom: 4,
      progressByPlaceId,
    })).toBe(false);
    expect(isPlaceVisible(candidate, {
      filters: matchingFilters,
      zoom: 3.99,
      progressByPlaceId,
    })).toBe(false);
  });

  it('treats an empty type or status selection as canonical All', () => {
    const candidate = place('target', 'settlement');

    expect(isPlaceVisible(candidate, {
      filters: filters({ types: new Set<PlaceType>() }),
      zoom: 2,
      progressByPlaceId: new Map(),
    })).toBe(true);
    expect(isPlaceVisible(candidate, {
      filters: filters({ statuses: new Set<ProgressStatus>() }),
      zoom: 2,
      progressByPlaceId: new Map(),
    })).toBe(true);
  });

  it('uses unvisited status filtering for places without a progress record', () => {
    const candidate = place('target', 'settlement');

    expect(isPlaceVisible(candidate, {
      filters: filters({ statuses: new Set<ProgressStatus>(['unvisited']) }),
      zoom: 2,
      progressByPlaceId: new Map(),
    })).toBe(true);
    expect(isPlaceVisible(candidate, {
      filters: filters({ statuses: new Set<ProgressStatus>(['active']) }),
      zoom: 2,
      progressByPlaceId: new Map(),
    })).toBe(false);
  });
});

describe('place label priority', () => {
  it('orders selected, query match, type, status, then raw ASCII id', () => {
    const selected = place('z-selected', 'other');
    const matched = place('z-matched', 'other');
    const typePriority = place('z-settlement', 'settlement');
    const active = place('z-active', 'house');
    const asciiUpper = place('A-house', 'house');
    const asciiLower = place('a-house', 'house');
    const visited = place('z-visited', 'house');
    const places = [asciiLower, visited, matched, asciiUpper, selected, active, typePriority];
    const progressByPlaceId = new Map<string, ProgressRecord>([
      [active.id, progress(active.id, 'active')],
      [asciiUpper.id, progress(asciiUpper.id, 'unvisited')],
      [asciiLower.id, progress(asciiLower.id, 'unvisited')],
      [visited.id, progress(visited.id, 'visited')],
    ]);
    const context = {
      selectedPlaceId: selected.id,
      searchMatchIds: new Set([matched.id]),
      progressByPlaceId,
    };

    expect([...places].sort((left, right) =>
      comparePlaceLabelPriority(left, right, context)
    ).map(({ id }) => id)).toEqual([
      selected.id,
      matched.id,
      typePriority.id,
      active.id,
      asciiUpper.id,
      asciiLower.id,
      visited.id,
    ]);
  });

  it('produces the same unique order for different input permutations', () => {
    const candidates = [
      place('b', 'cave'),
      place('a', 'cave'),
      place('c', 'settlement'),
      place('d', 'house'),
    ];
    const context = {
      selectedPlaceId: null,
      searchMatchIds: new Set<string>(),
      progressByPlaceId: new Map<string, ProgressRecord>(),
    };
    const sortIds = (input: readonly PlaceView[]) => [...input]
      .sort((left, right) => comparePlaceLabelPriority(left, right, context))
      .map(({ id }) => id);

    expect(sortIds(candidates)).toEqual(['c', 'a', 'b', 'd']);
    expect(sortIds([...candidates].reverse())).toEqual(['c', 'a', 'b', 'd']);
  });
});
