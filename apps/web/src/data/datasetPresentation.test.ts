import type { DatasetManifest } from '@morrowind-map/contracts';
import { describe, expect, it } from 'vitest';
import { presentDataset } from './datasetPresentation';

function manifest(
  mapKey: DatasetManifest['mapKey'],
  title: string,
  releaseName: string,
): DatasetManifest {
  return {
    mapKey,
    title: { en: title },
    release: { name: releaseName },
  } as unknown as DatasetManifest;
}

describe('presentDataset', () => {
  it.each([
    ['original', 'Classic', 'Morrowind Game of the Year — HD', 'GOTY', 'Morrowind Game of the Year'],
    ['tamriel-rebuilt', 'Tamriel Rebuilt', 'Tamriel Rebuilt 27.01', 'Next Release', 'Tamriel Rebuilt — Next Release'],
  ] as const)('presents %s as a flat landing choice', (mapKey, kind, manifestTitle, releaseName, title) => {
    expect(presentDataset(manifest(mapKey, manifestTitle, releaseName))).toEqual({ kind, title });
  });
});
