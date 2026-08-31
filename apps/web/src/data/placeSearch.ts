import type {
  Locale,
  PlaceLocaleCatalog,
  PlaceRecord,
  PlaceType,
} from '@morrowind-map/contracts';
import Fuse from 'fuse.js';

export interface PlaceView {
  readonly id: string;
  readonly place: PlaceRecord;
  readonly locale: Locale;
  readonly name: string;
  readonly aliases: readonly string[];
  readonly searchableType: PlaceType;
}

function namesByPlace(catalog: PlaceLocaleCatalog) {
  return new Map(catalog.places.map((place) => [place.placeId, place]));
}

export function buildPlaceViews(
  places: readonly PlaceRecord[],
  catalogs: readonly PlaceLocaleCatalog[],
  locale: Locale,
): PlaceView[] {
  const selectedCatalog = catalogs.find((catalog) => catalog.locale === locale);
  if (!selectedCatalog) {
    throw new Error(`Missing ${locale} locale catalog`);
  }
  const primary = namesByPlace(selectedCatalog);
  return places.map((place) => {
    const primaryName = primary.get(place.id);
    if (!primaryName) {
      throw new Error(`Missing localized name for ${place.id}`);
    }
    return {
      id: place.id,
      place,
      locale,
      name: primaryName.name,
      aliases: primaryName.aliases,
      searchableType: place.type,
    };
  });
}

export class PlaceSearch {
  readonly #places: readonly PlaceView[];
  readonly #index: Fuse<PlaceView>;

  constructor(places: readonly PlaceView[]) {
    this.#places = places;
    this.#index = new Fuse([...places], {
      keys: [
        { name: 'name', weight: 1 },
        { name: 'aliases', weight: 0.58 },
        { name: 'searchableType', weight: 0.25 },
        { name: 'place.sources.plugin', weight: 0.12 },
      ],
      ignoreLocation: true,
      minMatchCharLength: 2,
      threshold: 0.32,
    });
  }

  search(query: string, limit = 40): PlaceView[] {
    const normalized = query.trim();
    if (!normalized) {
      return [...this.#places].slice(0, limit);
    }
    return this.#index.search(normalized, { limit }).map(({ item }) => item);
  }
}
