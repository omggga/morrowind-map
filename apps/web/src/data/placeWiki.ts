import type { MapKey } from '@morrowind-map/contracts';
import wikiLinks from './placeWikiTitles.json';

const WIKI_PREFIXES = {
  original: 'Morrowind:',
  'tamriel-rebuilt': 'Tamriel_Rebuilt:',
  'project-cyrodiil': 'Project_Tamriel:Cyrodiil/',
  'home-of-nords': 'Project_Tamriel:Skyrim/',
  'azurian-isles': null,
} satisfies Record<MapKey, string | null>;

const WIKI_TITLES: Readonly<Record<string, string>> = wikiLinks.titles;

export function placeWikiUrl(mapKey: MapKey, regionId: string, name: string, placeId: string): string | null {
  const prefix = mapKey === 'tamriel-rebuilt' &&
    (regionId === 'vvardenfell' || regionId === 'solstheim')
    ? WIKI_PREFIXES.original
    : WIKI_PREFIXES[mapKey];
  if (prefix === null) return null;

  const encode = (value: string) => encodeURIComponent(value.replace(/ /g, '_')).replace(/'/g, '%27');
  const wikiName = WIKI_TITLES[placeId];
  if (wikiName) {
    const [title, ...fragment] = wikiName.split('#');
    const path = encode(title!).replace(/%3A/g, ':').replace(/%2F/g, '/');
    const anchor = fragment.length ? `#${encode(fragment.join('#'))}` : '';
    return `https://en.uesp.net/wiki/${path}${anchor}`;
  }

  return `https://en.uesp.net/wiki/${prefix}${encode(name.trim().replace(/\s+/g, ' '))}`;
}
