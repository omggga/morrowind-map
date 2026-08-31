import { describe, expect, it } from 'vitest';
import type { PlaceLocaleCatalog, PlaceRecord } from '@morrowind-map/contracts';
import { buildPlaceViews, PlaceSearch } from './placeSearch';

const place = {
  id: 'original-goty-hd.place-balmora',
  regionId: 'vvardenfell',
  type: 'settlement',
  mapPosition: [-20_000, -12_000],
  exteriorCell: [-3, -2],
  mimCategory: null,
  minZoom: 0,
  entrances: [],
  sources: [{ kind: 'esm', plugin: 'Morrowind.esm', recordId: 'Balmora', mimIndex: null }],
} satisfies PlaceRecord;

function locale(name: string, aliases: string[] = []): PlaceLocaleCatalog {
  return {
    schemaVersion: 1,
    datasetId: 'original-goty-hd',
    snapshotId: 'original:goty-hd:fixture',
    locale: 'en',
    places: [{ placeId: place.id, name, aliases }],
  };
}

describe('English place search', () => {
  it('searches English names and aliases without changing place identity', () => {
    const views = buildPlaceViews([place], [locale('Balmora', ['Balmora City'])], 'en');
    const search = new PlaceSearch(views);

    expect(search.search('Balmora')[0]?.id).toBe(place.id);
    expect(search.search('Balmora City')[0]?.id).toBe(place.id);
    expect(views[0]).toMatchObject({
      name: 'Balmora',
      aliases: ['Balmora City'],
    });
  });
});
