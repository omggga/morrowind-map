import type { DatasetManifest } from '@morrowind-map/contracts';

type DatasetTone = 'ash' | 'brass';

interface DatasetCopy {
  readonly plate: string;
  readonly era: string;
  readonly scope: string;
  readonly tone: DatasetTone;
}

type DatasetCopyFactory = (manifest: DatasetManifest) => DatasetCopy;

const DATASET_COPY: Record<string, DatasetCopyFactory> = {
  original: () => ({
    plate: '01',
    era: 'GOTY · 2003',
    scope: 'Vvardenfell / Solstheim',
    tone: 'ash',
  }),
  'tamriel-rebuilt': (manifest) => ({
    plate: '02',
    era: `TR · ${manifest.release.version}`,
    scope: manifest.release.name,
    tone: 'brass',
  }),
};

const FALLBACK_COPY: DatasetCopy = {
  plate: '--',
  era: 'TES3 DATASET',
  scope: 'Mapped world',
  tone: 'ash',
};

export interface DatasetPresentation extends DatasetCopy {
  readonly title: string;
  readonly summary: string;
  readonly readiness: string;
}

export function presentDataset(manifest: DatasetManifest): DatasetPresentation {
  const copy = DATASET_COPY[manifest.mapKey]?.(manifest) ?? FALLBACK_COPY;

  return {
    ...copy,
    title: manifest.title.en,
    summary: manifest.summary.en,
    readiness: manifest.readiness.status,
  };
}
