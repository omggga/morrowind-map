import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  parseDatasetIndex,
  parseDatasetManifest,
  parseMapAssetsManifest,
  parseTileCoverage,
  type DatasetManifest,
  type MapAssetsManifest,
  type TileCoverage,
  type TileCoverageLevel,
} from '@morrowind-map/contracts';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LandingMapBackdrop } from './LandingMapBackdrop';

const PUBLIC_ROOT = resolve(process.cwd(), 'apps/web/public');

function readPublicJson(url: string): unknown {
  return JSON.parse(readFileSync(resolve(PUBLIC_ROOT, `.${url}`), 'utf8')) as unknown;
}

function activeTamrielRebuiltManifest(): DatasetManifest {
  const index = parseDatasetIndex(readPublicJson('/datasets/index.json'));
  const manifests = index.datasets.map(({ manifestUrl }) =>
    parseDatasetManifest(readPublicJson(manifestUrl))
  );
  const manifest = manifests.find(({ mapKey }) => mapKey === 'tamriel-rebuilt');
  if (manifest === undefined) {
    throw new Error('The active dataset index must publish Tamriel Rebuilt');
  }
  return manifest;
}

function levelTileCount(level: TileCoverageLevel): number {
  return level.columns.reduce(
    (count, column) => count + column.yRanges.reduce(
      (columnCount, [minY, maxY]) => columnCount + maxY - minY + 1,
      0,
    ),
    0,
  );
}

function previewFixture(): {
  readonly dataset: DatasetManifest;
  readonly mapAssets: MapAssetsManifest;
  readonly coverage: TileCoverage;
} {
  const dataset = activeTamrielRebuiltManifest();
  const mapAssets = structuredClone(parseMapAssetsManifest(
    readPublicJson(dataset.artifacts.tiles?.manifestUrl ?? ''),
  ));
  const pyramid = mapAssets.tilePyramids?.[0];
  if (pyramid === undefined) {
    throw new Error('The active Tamriel Rebuilt dataset must publish a tile pyramid');
  }
  const coverage = structuredClone(parseTileCoverage(
    readPublicJson(pyramid.coverage.url),
    mapAssets,
  ));
  const previewLevel = coverage.levels.find(({ z }) => z === 2);
  if (previewLevel === undefined) {
    throw new Error('The active Tamriel Rebuilt dataset must publish z2 coverage');
  }
  const removedTiles = levelTileCount(previewLevel) - 1;
  previewLevel.columns = [{ x: 0, yRanges: [[0, 0]] }];
  coverage.tileCount -= removedTiles;
  pyramid.integrity.tileCount = coverage.tileCount;
  return { dataset, mapAssets, coverage };
}

function ok(value: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(value),
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('LandingMapBackdrop', () => {
  it('renders only covered tiles from the highest preview zoom and waits for their pixels', async () => {
    const { dataset, mapAssets, coverage } = previewFixture();
    const mapAssetsUrl = dataset.artifacts.tiles?.manifestUrl ?? '';
    const coverageUrl = mapAssets.tilePyramids?.[0]?.coverage.url ?? '';
    const fetchMock = vi.fn((url: string) => {
      if (url === mapAssetsUrl) {
        return ok(mapAssets);
      }
      if (url === coverageUrl) {
        return ok(coverage);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { container } = render(<LandingMapBackdrop dataset={dataset} />);
    const backdrop = container.querySelector<HTMLElement>('.landing-map-backdrop');
    expect(backdrop).not.toBeNull();
    expect(backdrop).toHaveAttribute('aria-hidden', 'true');
    expect(backdrop).toHaveAttribute('data-ready', 'false');
    expect(backdrop).toHaveStyle({ pointerEvents: 'none' });

    await waitFor(() => {
      expect(container.querySelectorAll('.landing-map-backdrop__tile')).toHaveLength(1);
    });
    const grid = container.querySelector<HTMLElement>('.landing-map-backdrop__grid');
    const tile = container.querySelector<HTMLImageElement>('.landing-map-backdrop__tile');
    expect(grid).not.toBeNull();
    expect(grid?.style.getPropertyValue('--preview-columns')).not.toBe('');
    expect(grid?.style.getPropertyValue('--preview-rows')).not.toBe('');
    expect(tile?.getAttribute('src')).toMatch(/\/tiles\/2\/0\/0\.webp$/);
    expect(tile?.style.gridColumn).toBe('1');
    expect(tile?.style.gridRow).toBe('1');

    fireEvent.load(tile!);
    await waitFor(() => expect(backdrop).toHaveAttribute('data-ready', 'true'));
    expect(backdrop).toHaveAttribute('data-state', 'ready');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('settles silently into the atmospheric fallback when strict parsing fails', async () => {
    const dataset = activeTamrielRebuiltManifest();
    vi.stubGlobal('fetch', vi.fn(() => ok({})));

    const { container } = render(<LandingMapBackdrop dataset={dataset} />);
    const backdrop = container.querySelector<HTMLElement>('.landing-map-backdrop');

    await waitFor(() => expect(backdrop).toHaveAttribute('data-ready', 'true'));
    expect(backdrop).toHaveAttribute('data-state', 'fallback');
    expect(container.querySelectorAll('.landing-map-backdrop__tile')).toHaveLength(0);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.textContent).toBe('');
  });
});
