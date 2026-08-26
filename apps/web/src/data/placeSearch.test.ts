import { describe, expect, it } from 'vitest';
import type { PlaceLocaleCatalog, PlaceRecord } from '@morrowind-map/contracts';
import { buildPlaceViews, PlaceSearch } from './placeSearch';

const place = {
  id: 'original-goty.vvardenfell.mim-0000',
  regionId: 'vvardenfell',
  type: 'settlement',
  mapPosition: [-20_000, -12_000],
  exteriorCell: [-3, -2],
  mimCategory: 19,
  minZoom: 0,
  entrances: [],
  sources: [{ kind: 'mim', plugin: 'mwmain.gdb', recordId: null, mimIndex: 0 }],
} satisfies PlaceRecord;

function locale(locale: 'en' | 'ru', name: string): PlaceLocaleCatalog {
  return {
    schemaVersion: 1,
    datasetId: 'original-goty',
    snapshotId: 'original:goty:fixture',
    locale,
    places: [{ placeId: place.id, name, aliases: [] }],
  };
}

describe('Original place search', () => {
  it('searches the selected and alternate language without changing place identity', () => {
    const views = buildPlaceViews([place], locale('en', 'Balmora'), locale('ru', 'Балмора'), 'ru');
    const search = new PlaceSearch(views);

    expect(search.search('Балмора')[0]?.id).toBe(place.id);
    expect(search.search('Balmora')[0]?.id).toBe(place.id);
    expect(views[0]?.name).toBe('Балмора');
    expect(views[0]?.alternateName).toBe('Balmora');
  });
});
