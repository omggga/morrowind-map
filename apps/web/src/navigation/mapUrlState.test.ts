import { describe, expect, it } from 'vitest';
import {
  readMapUrl,
  writeMapUrl,
  type MapUrlState,
  type MapUrlView,
} from './mapUrlState';

describe('map URL state', () => {
  it('reads a complete direct-link state', () => {
    const url = new URL(
      'https://maps.test/?dataset=poison-song-26.08&region=tr-mainland&x=90112&y=-98304&z=5.25&place=poison.place-1',
    );

    expect(readMapUrl(url)).toEqual({
      datasetId: 'poison-song-26.08',
      regionId: 'tr-mainland',
      view: { center: [90_112, -98_304], zoom: 5.25 },
      placeId: 'poison.place-1',
    });
  });

  it('returns the canonical landing state when dataset is absent or empty', () => {
    const landing: MapUrlState = {
      datasetId: null,
      regionId: 'all',
      view: null,
      placeId: null,
    };

    expect(
      readMapUrl(
        new URL('https://maps.test/?region=vvardenfell&x=1&y=2&z=3&place=ignored'),
      ),
    ).toEqual(landing);
    expect(readMapUrl(new URL('https://maps.test/?dataset=&region=vvardenfell'))).toEqual(landing);
  });

  it.each([
    'x=1&y=2',
    'x=1&z=3',
    'y=2&z=3',
    'x=&y=2&z=3',
    'x=one&y=2&z=3',
  ])('rejects a partial or invalid view triple: %s', (viewQuery) => {
    const state = readMapUrl(
      new URL(`https://maps.test/?dataset=original-goty-hd&${viewQuery}`),
    );

    expect(state.view).toBeNull();
  });

  it.each(['NaN', 'Infinity', '-Infinity', '1e309'])('rejects non-finite view values: %s', (value) => {
    const state = readMapUrl(
      new URL(`https://maps.test/?dataset=original-goty-hd&x=${value}&y=2&z=3`),
    );

    expect(state.view).toBeNull();
  });

  it('defaults optional identifiers and decodes encoded identifiers', () => {
    expect(
      readMapUrl(
        new URL(
          'https://maps.test/?dataset=Poison%20Song%2F26.08&region=TR%20Mainland&place=tomb%20%26%20mine',
        ),
      ),
    ).toEqual({
      datasetId: 'Poison Song/26.08',
      regionId: 'TR Mainland',
      view: null,
      placeId: 'tomb & mine',
    });

    expect(readMapUrl(new URL('https://maps.test/?dataset=original-goty-hd'))).toEqual({
      datasetId: 'original-goty-hd',
      regionId: 'all',
      view: null,
      placeId: null,
    });
  });

  it('writes owned parameters in canonical order and precision', () => {
    const view: MapUrlView = { center: [1_234.6, -987.6], zoom: 6.236 };
    const state: MapUrlState = {
      datasetId: 'Poison Song/26.08',
      regionId: 'TR Mainland',
      view,
      placeId: 'tomb & mine',
    };

    const result = writeMapUrl(new URL('https://maps.test/archive'), state);

    expect(result.search).toBe(
      '?dataset=Poison+Song%2F26.08&region=TR+Mainland&x=1235&y=-988&z=6.24&place=tomb+%26+mine',
    );
    expect(readMapUrl(result)).toEqual({
      ...state,
      view: { center: [1_235, -988], zoom: 6.24 },
    });
  });

  it('preserves unrelated query parameters and hash while replacing every owned value', () => {
    const baseUrl = new URL(
      'https://maps.test/archive?theme=sepia&dataset=old&region=old&x=0&y=0&z=0&place=old&tag=a&tag=b#ledger',
    );
    const state: MapUrlState = {
      datasetId: 'original-goty-hd',
      regionId: 'all',
      view: null,
      placeId: null,
    };

    const result = writeMapUrl(baseUrl, state);

    expect(result.href).toBe(
      'https://maps.test/archive?theme=sepia&tag=a&tag=b&dataset=original-goty-hd&region=all#ledger',
    );
    expect(baseUrl.searchParams.get('dataset')).toBe('old');
  });

  it('removes all owned parameters for the landing state', () => {
    const result = writeMapUrl(
      new URL(
        'https://maps.test/?dataset=old&region=old&x=1&y=2&z=3&place=old&theme=sepia#map',
      ),
      { datasetId: null, regionId: 'all', view: null, placeId: null },
    );

    expect(result.href).toBe('https://maps.test/?theme=sepia#map');
  });

  it('omits the complete view group when a writer receives non-finite view data', () => {
    const result = writeMapUrl(new URL('https://maps.test/'), {
      datasetId: 'original-goty-hd',
      regionId: 'all',
      view: { center: [Number.NaN, 2], zoom: 3 },
      placeId: null,
    });

    expect(result.search).toBe('?dataset=original-goty-hd&region=all');
  });

  it('is idempotent after canonicalization', () => {
    const state: MapUrlState = {
      datasetId: 'poison-song-26.08',
      regionId: 'tr-mainland',
      view: { center: [1.4, -2.6], zoom: 4.567 },
      placeId: 'poison.place-1',
    };
    const once = writeMapUrl(new URL('https://maps.test/?theme=sepia#map'), state);
    const twice = writeMapUrl(once, readMapUrl(once));

    expect(twice.href).toBe(once.href);
  });

  it('canonicalizes duplicate owned parameters to one first-value state', () => {
    const source = new URL(
      'https://maps.test/?dataset=original-goty-hd&dataset=poison-song-26.08&region=vvardenfell&region=solstheim&x=10&x=99&y=20&z=3&place=first&place=second',
    );
    const canonical = writeMapUrl(source, readMapUrl(source));

    expect(canonical.searchParams.getAll('dataset')).toEqual(['original-goty-hd']);
    expect(canonical.searchParams.getAll('region')).toEqual(['vvardenfell']);
    expect(canonical.searchParams.getAll('x')).toEqual(['10']);
    expect(canonical.searchParams.getAll('place')).toEqual(['first']);
  });
});
