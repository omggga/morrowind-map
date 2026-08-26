import type { DatasetManifest } from '@morrowind-map/contracts';

type DatasetTone = 'ash' | 'moss' | 'brass';

interface DatasetCopy {
  readonly plate: string;
  readonly era: string;
  readonly scope: string;
  readonly tone: DatasetTone;
}

const DATASET_COPY: Record<string, DatasetCopy> = {
  original: {
    plate: '01',
    era: 'GOTY · 2003',
    scope: 'Vvardenfell / Solstheim',
    tone: 'ash',
  },
  'fullrest-old': {
    plate: '02',
    era: 'TR · 25.08',
    scope: 'Fullrest archive',
    tone: 'moss',
  },
  'poison-song': {
    plate: '03',
    era: 'TR · 26.08',
    scope: 'Poison Song',
    tone: 'brass',
  },
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
  readonly languages: readonly string[];
  readonly readiness: string;
}

export function presentDataset(manifest: DatasetManifest): DatasetPresentation {
  const copy = DATASET_COPY[manifest.mapKey] ?? FALLBACK_COPY;
  const title = manifest.title.ru ?? manifest.title.en;
  const summary = manifest.summary.ru ?? manifest.summary.en;
  const languages = manifest.localization.locales.map(({ locale }) =>
    locale.toLocaleUpperCase('en-US'),
  );

  return {
    ...copy,
    title,
    summary,
    languages,
    readiness: manifest.readiness.status,
  };
}
