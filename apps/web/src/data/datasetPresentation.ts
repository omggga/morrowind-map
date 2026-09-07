import type { DatasetManifest } from '@morrowind-map/contracts';

const MAP_TITLES = {
  original: 'Morrowind Game of the Year',
  'tamriel-rebuilt': 'Tamriel Rebuilt',
  'project-cyrodiil': 'Project Cyrodiil',
  'home-of-nords': 'Skyrim: Home of the Nords',
} satisfies Record<DatasetManifest['mapKey'], string>;

const MOD_URLS = {
  original: null,
  'tamriel-rebuilt': 'https://www.nexusmods.com/morrowind/mods/42145',
  'project-cyrodiil': 'https://www.nexusmods.com/morrowind/mods/44922',
  'home-of-nords': 'https://www.nexusmods.com/morrowind/mods/44921',
} satisfies Record<DatasetManifest['mapKey'], string | null>;

export interface DatasetPresentation {
  readonly title: string;
  readonly modUrl: string | null;
}

export function presentDataset(manifest: DatasetManifest): DatasetPresentation {
  return {
    title: manifest.mapKey === 'original'
      ? 'Morrowind Game of the Year'
      : `${MAP_TITLES[manifest.mapKey]} — ${manifest.release.name}`,
    modUrl: MOD_URLS[manifest.mapKey],
  };
}
