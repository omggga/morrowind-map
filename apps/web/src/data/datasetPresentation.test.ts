import type { DatasetManifest } from '@morrowind-map/contracts';
import { describe, expect, it } from 'vitest';
import { presentDataset } from './datasetPresentation';

function manifest(mapKey: DatasetManifest['mapKey'], title: string): DatasetManifest {
  return {
    mapKey,
    title: { en: title },
  } as unknown as DatasetManifest;
}

describe('presentDataset', () => {
  it.each([
    ['original', 'Classic', 'Morrowind Game of the Year — HD'],
    ['tamriel-rebuilt', 'Tamriel Rebuilt', 'Tamriel Rebuilt 27.01 — Next Release'],
  ] as const)('presents %s as a flat landing choice', (mapKey, kind, title) => {
    expect(presentDataset(manifest(mapKey, title))).toEqual({ kind, title });
  });
});
