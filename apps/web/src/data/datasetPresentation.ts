import type { DatasetManifest } from '@morrowind-map/contracts';

export interface DatasetPresentation {
  readonly title: string;
}

export function presentDataset(manifest: DatasetManifest): DatasetPresentation {
  return {
    title: manifest.mapKey === 'original'
      ? 'Morrowind Game of the Year'
      : `Tamriel Rebuilt — ${manifest.release.name}`,
  };
}
