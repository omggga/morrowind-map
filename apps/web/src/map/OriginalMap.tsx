import { useEffect, useMemo, useRef, useState } from 'react';
import type { DatasetManifest, Locale } from '@morrowind-map/contracts';
import Feature from 'ol/Feature.js';
import Map from 'ol/Map.js';
import View from 'ol/View.js';
import Point from 'ol/geom/Point.js';
import ImageLayer from 'ol/layer/Image.js';
import VectorLayer from 'ol/layer/Vector.js';
import { unByKey } from 'ol/Observable.js';
import ImageStatic from 'ol/source/ImageStatic.js';
import VectorSource from 'ol/source/Vector.js';
import Fill from 'ol/style/Fill.js';
import RegularShape from 'ol/style/RegularShape.js';
import Stroke from 'ol/style/Stroke.js';
import Style from 'ol/style/Style.js';
import { useTranslation } from 'react-i18next';
import { loadOriginalDataset, type OriginalDatasetBundle } from '../data/loadOriginalDataset';
import { buildPlaceViews, PlaceSearch, type PlaceView } from '../data/placeSearch';
import { i18n } from '../i18n';
import {
  configureTes3Projection,
  worldToCell,
  type CellCoordinate,
  type WorldCoordinate,
} from './tes3Projection';

interface OriginalMapProps {
  readonly dataset: DatasetManifest;
  readonly onBack: () => void;
}

type RegionFilter = 'all' | 'vvardenfell' | 'solstheim';

type LoadState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly bundle: OriginalDatasetBundle }
  | { readonly status: 'error'; readonly message: string };

interface CursorReadout {
  readonly world: WorldCoordinate;
  readonly cell: CellCoordinate;
}

const UNVISITED_STYLE = createMarkerStyle('#fff19b', 5);
const SELECTED_STYLE = createMarkerStyle('#ff80ff', 7);

function createMarkerStyle(color: string, radius: number): Style {
  return new Style({
    image: new RegularShape({
      points: 4,
      radius,
      angle: Math.PI / 4,
      fill: new Fill({ color }),
      stroke: new Stroke({ color: '#241a0e', width: 1 }),
    }),
    zIndex: radius,
  });
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown Original dataset error';
}

function localeFromManifest(dataset: DatasetManifest): Locale {
  return dataset.localization.defaultLocale === 'en' ? 'en' : 'ru';
}

function formatCoordinate(value: number, locale: Locale): string {
  return Math.round(value).toLocaleString(locale === 'ru' ? 'ru-RU' : 'en-US');
}

export function OriginalMap({ dataset, onBack }: OriginalMapProps) {
  const { t } = useTranslation();
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void loadOriginalDataset(dataset, controller.signal)
      .then((bundle) => setLoadState({ status: 'ready', bundle }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadState({ status: 'error', message: errorMessage(error) });
        }
      });
    return () => controller.abort();
  }, [dataset, loadAttempt]);

  if (loadState.status !== 'ready') {
    return (
      <main className="map-screen original-map-screen" aria-labelledby="map-title">
        <MapTitlebar dataset={dataset} onBack={onBack} />
        <section className="original-load-state" role={loadState.status === 'error' ? 'alert' : 'status'}>
          {loadState.status === 'loading' ? (
            <>
              <span className="load-indicator" aria-hidden="true" />
              <p>{t('map.loading')}</p>
            </>
          ) : (
            <>
              <span className="load-state-code">DATA ERROR</span>
              <h2>{t('map.loadError')}</h2>
              <p>{loadState.message}</p>
              <button
                type="button"
                onClick={() => {
                  setLoadState({ status: 'loading' });
                  setLoadAttempt((attempt) => attempt + 1);
                }}
              >
                {t('map.retry')}
              </button>
            </>
          )}
        </section>
      </main>
    );
  }

  return <OriginalMapReady dataset={dataset} bundle={loadState.bundle} onBack={onBack} />;
}

function MapTitlebar({ dataset, onBack }: OriginalMapProps) {
  const { t } = useTranslation();
  const title = i18n.resolvedLanguage?.startsWith('ru')
    ? (dataset.title.ru ?? dataset.title.en)
    : dataset.title.en;
  return (
    <header className="window-titlebar map-titlebar">
      <button className="back-button" type="button" onClick={onBack}>
        <span aria-hidden="true">←</span>
        {t('map.versions')}
      </button>
      <div className="map-title-copy">
        <span className="titlebar-kicker">ORIGINAL / TES3:WORLD</span>
        <h1 id="map-title">{title}</h1>
      </div>
      <span className="titlebar-state">{t('map.local')}</span>
    </header>
  );
}

interface OriginalMapReadyProps extends OriginalMapProps {
  readonly bundle: OriginalDatasetBundle;
}

function OriginalMapReady({ dataset, bundle, onBack }: OriginalMapReadyProps) {
  const { t } = useTranslation();
  const targetRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const mapRef = useRef<Map | null>(null);
  const markerLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const regionRef = useRef<RegionFilter>('all');
  const zoomRef = useRef(0);
  const [locale, setLocale] = useState<Locale>(() => localeFromManifest(dataset));
  const [query, setQuery] = useState('');
  const [region, setRegion] = useState<RegionFilter>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cursor, setCursor] = useState<CursorReadout | null>(null);
  const [zoom, setZoom] = useState(0);
  const projectionDescriptor = dataset.map.projection;
  const extent = useMemo<[number, number, number, number]>(() => {
    const [minX, minY, maxX, maxY] = projectionDescriptor.extent;
    return [minX, minY, maxX, maxY];
  }, [projectionDescriptor.extent]);
  const center = useMemo<[number, number]>(() => {
    const [x, y] = projectionDescriptor.center;
    return [x, y];
  }, [projectionDescriptor.center]);

  const places = useMemo(
    () =>
      buildPlaceViews(bundle.locations.places, bundle.locales.en, bundle.locales.ru, locale).sort(
        (left, right) => left.name.localeCompare(right.name, locale),
      ),
    [bundle, locale],
  );
  const regionPlaces = useMemo(
    () => places.filter(({ place }) => region === 'all' || place.regionId === region),
    [places, region],
  );
  const placeSearch = useMemo(() => new PlaceSearch(regionPlaces), [regionPlaces]);
  const results = useMemo(() => placeSearch.search(query, 80), [placeSearch, query]);
  const selectedPlace = useMemo(
    () => places.find(({ id }) => id === selectedId) ?? null,
    [places, selectedId],
  );
  const visibleMarkerCount = useMemo(
    () => regionPlaces.filter(({ place }) => place.minZoom <= zoom).length,
    [regionPlaces, zoom],
  );

  useEffect(() => {
    void i18n.changeLanguage(locale);
  }, [locale]);

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        event.key !== '/' ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        (target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
      ) {
        return;
      }
      event.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener('keydown', focusSearch);
    return () => window.removeEventListener('keydown', focusSearch);
  }, []);

  useEffect(() => {
    selectedIdRef.current = selectedId;
    markerLayerRef.current?.changed();
  }, [selectedId]);

  useEffect(() => {
    regionRef.current = region;
    markerLayerRef.current?.changed();
  }, [region]);

  useEffect(() => {
    if (!targetRef.current) {
      return undefined;
    }

    const projection = configureTes3Projection(extent);
    const rasterLayers = bundle.mapAssets.rasters.map(
      (raster) =>
        new ImageLayer({
          source: new ImageStatic({
            url: raster.imageUrl,
            imageExtent: [...raster.extent],
            projection,
            interpolate: true,
          }),
        }),
    );
    const features = bundle.locations.places.map(
      (place) =>
        new Feature({
          geometry: new Point([...place.mapPosition]),
          placeId: place.id,
          regionId: place.regionId,
          minZoom: place.minZoom,
        }),
    );
    const markerLayer = new VectorLayer({
      source: new VectorSource({ features }),
      style: (feature) => {
        const placeRegion = feature.get('regionId') as string;
        const minimumZoom = feature.get('minZoom') as number;
        const placeId = feature.get('placeId') as string;
        if (
          minimumZoom > zoomRef.current ||
          (regionRef.current !== 'all' && placeRegion !== regionRef.current)
        ) {
          return undefined;
        }
        return placeId === selectedIdRef.current ? SELECTED_STYLE : UNVISITED_STYLE;
      },
      updateWhileAnimating: true,
      updateWhileInteracting: true,
    });
    markerLayer.setZIndex(10);
    markerLayerRef.current = markerLayer;
    const view = new View({
      projection,
      center,
      zoom: 1,
      minZoom: 0,
      maxZoom: 12,
      extent,
      showFullExtent: true,
      constrainOnlyCenter: true,
    });
    const map = new Map({
      target: targetRef.current,
      layers: [...rasterLayers, markerLayer],
      view,
      controls: [],
    });
    mapRef.current = map;
    view.fit(extent, { duration: 0, maxZoom: 4, padding: [44, 44, 44, 44] });
    zoomRef.current = view.getZoom() ?? 0;
    setZoom(zoomRef.current);
    markerLayer.changed();

    const pointerMoveKey = map.on('pointermove', (event) => {
      if (event.dragging) {
        return;
      }
      const [x = 0, y = 0] = event.coordinate;
      const world: WorldCoordinate = [x, y];
      setCursor({ world, cell: worldToCell(world, projectionDescriptor.cellSize) });
      const hit = map.hasFeatureAtPixel(event.pixel, {
        hitTolerance: 5,
        layerFilter: (layer) => layer === markerLayer,
      });
      map.getTargetElement().classList.toggle('map-canvas--marker-hover', hit);
    });
    const clickKey = map.on('singleclick', (event) => {
      const feature = map.forEachFeatureAtPixel(event.pixel, (candidate) => candidate, {
        hitTolerance: 6,
        layerFilter: (layer) => layer === markerLayer,
      });
      if (feature) {
        setSelectedId(feature.get('placeId') as string);
      }
    });
    const resolutionKey = view.on('change:resolution', () => {
      zoomRef.current = view.getZoom() ?? 0;
      setZoom(zoomRef.current);
      markerLayer.changed();
    });
    const viewport = map.getViewport();
    const clearCursor = () => {
      setCursor(null);
      map.getTargetElement().classList.remove('map-canvas--marker-hover');
    };
    viewport.addEventListener('pointerleave', clearCursor);

    return () => {
      unByKey(pointerMoveKey);
      unByKey(clickKey);
      unByKey(resolutionKey);
      viewport.removeEventListener('pointerleave', clearCursor);
      map.setTarget(undefined);
      mapRef.current = null;
      markerLayerRef.current = null;
    };
  }, [bundle, center, extent, projectionDescriptor.cellSize]);

  const changeZoom = (delta: number) => {
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    const current = view.getZoom() ?? 0;
    const next = Math.max(view.getMinZoom(), Math.min(view.getMaxZoom(), current + delta));
    if (prefersReducedMotion()) {
      view.setZoom(next);
    } else {
      view.animate({ zoom: next, duration: 120 });
    }
  };

  const fitExtent = (nextExtent: readonly [number, number, number, number]) => {
    mapRef.current?.getView().fit([...nextExtent], {
      duration: prefersReducedMotion() ? 0 : 180,
      maxZoom: 4,
      padding: [48, 48, 48, 48],
    });
  };

  const selectRegion = (nextRegion: RegionFilter) => {
    setRegion(nextRegion);
    if (nextRegion === 'all') {
      fitExtent(extent);
      return;
    }
    const raster = bundle.mapAssets.rasters.find(({ regionId }) => regionId === nextRegion);
    if (raster) {
      fitExtent(raster.extent);
    }
  };

  const selectPlace = (place: PlaceView) => {
    setSelectedId(place.id);
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    const nextZoom = Math.max(view.getZoom() ?? 0, place.place.minZoom + 1, 5);
    if (prefersReducedMotion()) {
      view.setCenter([...place.place.mapPosition]);
      view.setZoom(nextZoom);
    } else {
      view.animate({ center: [...place.place.mapPosition], zoom: nextZoom, duration: 220 });
    }
  };

  return (
    <main className="map-screen original-map-screen" aria-labelledby="map-title">
      <MapTitlebar dataset={dataset} onBack={onBack} />

      <section className="original-workspace">
        <aside className="map-ledger" aria-label={t('map.searchLabel')}>
          <div className="ledger-heading">
            <span>INDEX / 001–{places.length.toLocaleString('en-US')}</span>
            <div className="locale-switch" aria-label="Language">
              {(['en', 'ru'] as const).map((language) => (
                <button
                  key={language}
                  type="button"
                  aria-pressed={locale === language}
                  onClick={() => setLocale(language)}
                >
                  {language.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <label className="place-search">
            <span>{t('map.searchLabel')}</span>
            <span className="search-field">
              <input
                ref={searchRef}
                type="search"
                value={query}
                placeholder={t('map.searchPlaceholder')}
                onChange={(event) => setQuery(event.currentTarget.value)}
              />
              <kbd aria-hidden="true">/</kbd>
            </span>
          </label>

          <fieldset className="region-filter">
            <legend>{t('map.regions')}</legend>
            {(['all', 'vvardenfell', 'solstheim'] as const).map((regionId) => (
              <button
                key={regionId}
                type="button"
                aria-pressed={region === regionId}
                onClick={() => selectRegion(regionId)}
              >
                {t(
                  regionId === 'all'
                    ? 'map.allRegions'
                    : regionId === 'vvardenfell'
                      ? 'map.vvardenfell'
                      : 'map.solstheim',
                )}
              </button>
            ))}
          </fieldset>

          <div className="result-summary" aria-live="polite">
            <span>{t('map.found', { count: regionPlaces.length })}</span>
            {query ? <strong>{results.length}</strong> : null}
          </div>

          <div className="place-results">
            {results.length ? (
              results.map((place) => (
                <button
                  key={place.id}
                  type="button"
                  className={selectedId === place.id ? 'place-result place-result--selected' : 'place-result'}
                  onClick={() => selectPlace(place)}
                >
                  <span className="result-marker" aria-hidden="true" />
                  <span>
                    <strong>{place.name}</strong>
                    <small>
                      {t(`placeType.${place.place.type}`)} ·{' '}
                      {t(place.place.regionId === 'solstheim' ? 'map.solstheim' : 'map.vvardenfell')}
                    </small>
                  </span>
                </button>
              ))
            ) : (
              <p className="no-results">{t('map.noResults')}</p>
            )}
          </div>
        </aside>

        <div className="original-map-stage">
          <div ref={targetRef} className="map-canvas" tabIndex={0} aria-label={t('map.mapAria')} />

          <div className="map-tools" aria-label={t('map.zoom')}>
            <button type="button" onClick={() => changeZoom(1)} aria-label={t('map.zoomIn')}>
              +
            </button>
            <button type="button" onClick={() => selectRegion('all')} aria-label={t('map.showWholeWorld')}>
              □
            </button>
            <button type="button" onClick={() => changeZoom(-1)} aria-label={t('map.zoomOut')}>
              −
            </button>
          </div>

          <div className="marker-legend" aria-label="Marker legend">
            <span><i className="legend-square" />{t('map.unvisited')}</span>
            <span><i className="legend-square legend-square--selected" />{t('map.selected')}</span>
          </div>

          {selectedPlace ? (
            <PlaceCard
              place={selectedPlace}
              locale={locale}
              onClose={() => setSelectedId(null)}
            />
          ) : null}
        </div>
      </section>

      <footer className="map-statusbar" aria-label="Map status">
        <span>
          X&nbsp;<strong>{cursor ? formatCoordinate(cursor.world[0], locale) : '—'}</strong>
        </span>
        <span>
          Y&nbsp;<strong>{cursor ? formatCoordinate(cursor.world[1], locale) : '—'}</strong>
        </span>
        <span>
          CELL&nbsp;<strong>{cursor ? `${cursor.cell[0]}, ${cursor.cell[1]}` : '—, —'}</strong>
        </span>
        <span>{t('map.placesVisible', { count: visibleMarkerCount })}</span>
        <span className="statusbar-zoom">
          {t('map.zoom')}&nbsp;<strong>{zoom.toFixed(2)}</strong>
        </span>
      </footer>
    </main>
  );
}

interface PlaceCardProps {
  readonly place: PlaceView;
  readonly locale: Locale;
  readonly onClose: () => void;
}

function PlaceCard({ place, locale, onClose }: PlaceCardProps) {
  const { t } = useTranslation();
  const plugins = [...new Set(place.place.sources.map(({ plugin }) => plugin))].join(', ');
  const regionName = t(place.place.regionId === 'solstheim' ? 'map.solstheim' : 'map.vvardenfell');
  return (
    <article className="place-card" aria-labelledby="selected-place-title">
      <button className="place-card-close" type="button" onClick={onClose} aria-label={t('map.closeCard')}>
        ×
      </button>
      <span className="place-card-index">{t('map.cardIndex')}</span>
      <h2 id="selected-place-title">{place.name}</h2>
      {place.alternateName !== place.name ? (
        <p className="alternate-name">
          <span>{t('map.alternateName')}</span>
          {place.alternateName}
        </p>
      ) : null}
      <dl>
        <div>
          <dt>{t('map.type')}</dt>
          <dd>{t(`placeType.${place.place.type}`)}</dd>
        </div>
        <div>
          <dt>{t('map.region')}</dt>
          <dd>{regionName}</dd>
        </div>
        <div>
          <dt>{t('map.cell')}</dt>
          <dd>{place.place.exteriorCell.join(', ')}</dd>
        </div>
        <div>
          <dt>{t('map.coordinates')}</dt>
          <dd>
            {formatCoordinate(place.place.mapPosition[0], locale)} :{' '}
            {formatCoordinate(place.place.mapPosition[1], locale)}
          </dd>
        </div>
        <div>
          <dt>{t('map.entrances')}</dt>
          <dd>{place.place.entrances.length}</dd>
        </div>
        <div>
          <dt>{t('map.source')}</dt>
          <dd>{plugins}</dd>
        </div>
      </dl>
    </article>
  );
}
