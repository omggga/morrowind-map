import { describe, expect, it } from 'vitest';
import type { MapUrlState } from './mapUrlState';
import { normalizeMapUrlState, type MapUrlConstraints } from './normalizeMapUrlState';

const constraints: MapUrlConstraints = {
  datasetId: 'original-goty-hd',
  availableRegionIds: new Set(['vvardenfell', 'solstheim']),
  placeRegions: new Map([
    ['original.place-balmora', 'vvardenfell'],
    ['original.place-raven-rock', 'solstheim'],
  ]),
  extent: [-100, -200, 300, 400],
  minimumZoom: 0,
  maximumZoom: 7,
};

function state(overrides: Partial<MapUrlState> = {}): MapUrlState {
  return {
    datasetId: 'original-goty-hd',
    regionId: 'all',
    view: null,
    placeId: null,
    ...overrides,
  };
}

describe('dataset map URL normalization', () => {
  it('forces the active dataset and rejects unavailable regions and stale places', () => {
    expect(normalizeMapUrlState(state({
      datasetId: 'poison-song-26.08',
      regionId: 'mournhold',
      placeId: 'poison.place-1',
    }), constraints)).toEqual(state());
  });

  it('keeps all with a valid place and normalizes a conflicting specific region', () => {
    expect(normalizeMapUrlState(state({
      regionId: 'all',
      placeId: 'original.place-raven-rock',
    }), constraints)).toMatchObject({
      regionId: 'all',
      placeId: 'original.place-raven-rock',
    });
    expect(normalizeMapUrlState(state({
      regionId: 'vvardenfell',
      placeId: 'original.place-raven-rock',
    }), constraints)).toMatchObject({
      regionId: 'solstheim',
      placeId: 'original.place-raven-rock',
    });
  });

  it('clamps a complete finite view to the map extent and zoom range', () => {
    expect(normalizeMapUrlState(state({
      view: { center: [-500, 900], zoom: 12 },
    }), constraints).view).toEqual({ center: [-100, 400], zoom: 7 });
    expect(normalizeMapUrlState(state({
      view: { center: [10, 20], zoom: -2 },
    }), constraints).view).toEqual({ center: [10, 20], zoom: 0 });
  });

  it('preserves an in-range camera independently from place selection', () => {
    expect(normalizeMapUrlState(state({
      regionId: 'vvardenfell',
      placeId: 'original.place-balmora',
      view: { center: [250, 350], zoom: 4.25 },
    }), constraints)).toEqual(state({
      regionId: 'vvardenfell',
      placeId: 'original.place-balmora',
      view: { center: [250, 350], zoom: 4.25 },
    }));
  });
});
