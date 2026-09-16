import type { MapKey } from '@morrowind-map/contracts';
import type { PlaceView } from '../data/placeSearch';
import { placeWikiUrl } from '../data/placeWiki';
import type { TransportStop } from './types';

export function transportWikiUrl(mapKey: MapKey, stop: TransportStop, places: readonly PlaceView[]): string | null {
  const normalize = (name: string) => name.replace(/^Solstheim,\s*/, '').trim().toLowerCase();
  const names = new Set([normalize(stop.name), ...(stop.interior ? [normalize(stop.interior)] : [])]);
  const distance = (place: PlaceView) => Math.hypot(
    place.place.mapPosition[0] - stop.position[0], place.place.mapPosition[1] - stop.position[1],
  );
  const match = places.filter((place) => place.place.regionId === stop.regionId &&
    [place.name, ...place.aliases].some((name) => names.has(normalize(name))))
    .sort((left, right) => distance(left) - distance(right))[0];
  // Use the same curated page overrides as normal place cards, including mod pages.
  const regionMap: Readonly<Record<string, MapKey>> = {
    vvardenfell: 'original', solstheim: 'original', 'tr-mainland': 'tamriel-rebuilt',
    skyrim: 'home-of-nords', cyrodiil: 'project-cyrodiil',
  };
  return placeWikiUrl(regionMap[stop.regionId] ?? mapKey, stop.regionId,
    match?.name ?? stop.name, match?.id ?? stop.id);
}
