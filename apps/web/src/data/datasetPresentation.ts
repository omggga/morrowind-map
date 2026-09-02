import type { DatasetManifest } from '@morrowind-map/contracts';

const DATASET_KIND: Record<DatasetManifest['mapKey'], string> = {
  original: 'Classic',
  'tamriel-rebuilt': 'Tamriel Rebuilt',
};

export interface DatasetPresentation {
  readonly kind: string;
  readonly title: string;
}

export function presentDataset(manifest: DatasetManifest): DatasetPresentation {
  return {
    kind: DATASET_KIND[manifest.mapKey],
    title: manifest.mapKey === 'original'
      ? 'Morrowind Game of the Year'
      : `Tamriel Rebuilt — ${manifest.release.name}`,
  };
}
