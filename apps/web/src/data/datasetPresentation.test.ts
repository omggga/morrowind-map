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
    ['original', 'Morrowind Game of the Year — HD', 'GOTY', 'Morrowind Game of the Year'],
    ['tamriel-rebuilt', 'Tamriel Rebuilt 27.01', 'Next Release', 'Tamriel Rebuilt — Next Release'],
    ['project-cyrodiil', 'Project Cyrodiil 25.05', 'Abecean Shores', 'Project Cyrodiil — Abecean Shores'],
    ['home-of-nords', 'Skyrim: Home of the Nords 25.05', 'Dragonstar', 'Skyrim: Home of the Nords — Dragonstar'],
  ] as const)('presents %s as a flat landing choice', (mapKey, manifestTitle, releaseName, title) => {
    expect(presentDataset(manifest(mapKey, manifestTitle, releaseName))).toMatchObject({ title });
  });
});
