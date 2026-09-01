import type { DatasetManifest } from '@morrowind-map/contracts';
import { describe, expect, it } from 'vitest';
import { presentDataset } from './datasetPresentation';

function tamrielRebuiltManifest(
  name: string,
  version: string,
): DatasetManifest {
  return {
    mapKey: 'tamriel-rebuilt',
    release: { name, version, build: null },
    title: { en: `Tamriel Rebuilt ${version} — ${name}` },
    summary: { en: 'Tamriel Rebuilt mainland map.' },
    readiness: {
      status: 'ready',
      exactProfile: true,
      blockers: [],
      warnings: [],
    },
  } as unknown as DatasetManifest;
}

describe('presentDataset', () => {
  it('derives Tamriel Rebuilt labels from release metadata', () => {
    const presentation = presentDataset(tamrielRebuiltManifest('Next Release', '27.01'));

    expect(presentation).toMatchObject({
      plate: '02',
      era: 'TR · 27.01',
      scope: 'Next Release',
      tone: 'brass',
    });
  });
});
