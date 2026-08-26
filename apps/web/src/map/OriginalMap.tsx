import { useCallback, useEffect, useMemo, useRef, useState, type Ref } from 'react';
import type {
  CustomMarkerRecord,
  DatasetManifest,
  Locale,
  ProgressRecord,
  ProgressStatus,
} from '@morrowind-map/contracts';
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
import { userDatabase } from '../storage/database';
import {
  adoptLegacyDatasetSnapshot,
  ensureDatasetSnapshot,
  saveCustomMarker,
} from '../storage/userData';
import {
  CustomMarkerEditor,
  DataTools,
  PlaceProgressEditor,
  useDatasetCustomMarkers,
  useDatasetProgress,
} from '../user-data';
import {
  configureTes3Projection,
  worldToCell,
  type CellCoordinate,
  type WorldCoordinate,
} from './tes3Projection';

interface MapTitlebarProps {
  readonly dataset: DatasetManifest;
  readonly onBack: () => void;
}

interface OriginalMapProps extends MapTitlebarProps {
  readonly datasetSnapshots: Readonly<Record<string, string>>;
}

type RegionFilter = 'all' | 'vvardenfell' | 'solstheim';

type LoadState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly bundle: OriginalDatasetBundle }
  | {
      readonly status: 'needs-legacy-adoption';
      readonly bundle: OriginalDatasetBundle;
      readonly storedRecords: number;
    }
  | { readonly status: 'error'; readonly message: string };

interface CursorReadout {
  readonly world: WorldCoordinate;
  readonly cell: CellCoordinate;
}

const PROGRESS_COLORS: Readonly<Record<ProgressStatus, string>> = {
  unvisited: '#fff19b',
  active: '#ff80ff',
  visited: '#ffa040',
};
const PLACE_STYLES: Readonly<Record<ProgressStatus, Style>> = {
  unvisited: createMarkerStyle(PROGRESS_COLORS.unvisited, 5),
  active: createMarkerStyle(PROGRESS_COLORS.active, 5),
  visited: createMarkerStyle(PROGRESS_COLORS.visited, 5),
};
const SELECTED_PLACE_STYLES: Readonly<Record<ProgressStatus, Style>> = {
  unvisited: createMarkerStyle(PROGRESS_COLORS.unvisited, 7, true),
  active: createMarkerStyle(PROGRESS_COLORS.active, 7, true),
  visited: createMarkerStyle(PROGRESS_COLORS.visited, 7, true),
};
const CUSTOM_MARKER_STYLE = createMarkerStyle('#40ff40', 6);
const SELECTED_CUSTOM_MARKER_STYLE = createMarkerStyle('#40ff40', 8, true);

function createMarkerStyle(color: string, radius: number, selected = false): Style {
  return new Style({
    image: new RegularShape({
      points: 4,
      radius,
      angle: Math.PI / 4,
      fill: new Fill({ color }),
      stroke: new Stroke({ color: selected ? '#fff2b2' : '#241a0e', width: selected ? 2 : 1 }),
    }),
    zIndex: selected ? 100 + radius : radius,
  });
}

function markerRegion(
  position: readonly [number, number],
  bundle: OriginalDatasetBundle,
): string | null {
  const [x, y] = position;
  return bundle.mapAssets.rasters.find(({ extent: [minX, minY, maxX, maxY] }) =>
    x >= minX && x <= maxX && y >= minY && y <= maxY
  )?.regionId ?? null;
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

export function OriginalMap({ dataset, datasetSnapshots, onBack }: OriginalMapProps) {
  const { t } = useTranslation();
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void loadOriginalDataset(dataset, controller.signal)
      .then(async (bundle) => {
        const readiness = await ensureDatasetSnapshot(
          userDatabase,
          dataset.datasetId,
          dataset.snapshotId,
        );
        if (controller.signal.aborted) {
          return;
        }
        setLoadState(
          readiness.kind === 'ready'
            ? { status: 'ready', bundle }
            : {
                status: 'needs-legacy-adoption',
                bundle,
                storedRecords: readiness.storedRecords,
              },
        );
      })
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
          ) : loadState.status === 'needs-legacy-adoption' ? (
            <>
              <span className="load-state-code">LOCAL DATA</span>
              <h2>{t('map.legacyDataTitle')}</h2>
              <p>{t('map.legacyDataBody', { count: loadState.storedRecords })}</p>
              <button
                type="button"
                onClick={() => {
                  const bundle = loadState.bundle;
                  setLoadState({ status: 'loading' });
                  void adoptLegacyDatasetSnapshot(
                    userDatabase,
                    dataset.datasetId,
                    dataset.snapshotId,
                  )
                    .then(() => setLoadState({ status: 'ready', bundle }))
                    .catch((error: unknown) =>
                      setLoadState({ status: 'error', message: errorMessage(error) }),
                    );
                }}
              >
                {t('map.adoptLegacyData')}
              </button>
              <button type="button" onClick={onBack}>{t('map.versions')}</button>
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

  return (
    <OriginalMapReady
      dataset={dataset}
      datasetSnapshots={datasetSnapshots}
      bundle={loadState.bundle}
      onBack={onBack}
    />
  );
}

function MapTitlebar({ dataset, onBack }: MapTitlebarProps) {
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

function OriginalMapReady({ dataset, datasetSnapshots, bundle, onBack }: OriginalMapReadyProps) {
  const { t } = useTranslation();
  const targetRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const mapRef = useRef<Map | null>(null);
  const markerLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const customMarkerLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const selectedMarkerIdRef = useRef<string | null>(null);
  const customMarkerButtonRefs = useRef(new globalThis.Map<string, HTMLButtonElement>());
  const customMarkerEditorInputRef = useRef<HTMLInputElement>(null);
  const customMarkerHeadingRef = useRef<HTMLHeadingElement>(null);
  const progressByPlaceIdRef = useRef<ReadonlyMap<string, ProgressRecord>>(
    new globalThis.Map<string, ProgressRecord>(),
  );
  const placingMarkerRef = useRef(false);
  const localeRef = useRef<Locale>(localeFromManifest(dataset));
  const regionRef = useRef<RegionFilter>('all');
  const zoomRef = useRef(0);
  const [locale, setLocale] = useState<Locale>(() => localeFromManifest(dataset));
  const [query, setQuery] = useState('');
  const [region, setRegion] = useState<RegionFilter>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null);
  const [placingMarker, setPlacingMarker] = useState(false);
  const [markerError, setMarkerError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<CursorReadout | null>(null);
  const [zoom, setZoom] = useState(0);
  const progress = useDatasetProgress(dataset.datasetId);
  const customMarkers = useDatasetCustomMarkers(dataset.datasetId);
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
  const selectedMarker = selectedMarkerId === null
    ? null
    : (customMarkers.byId.get(selectedMarkerId) ?? null);
  const knownPlaceIds = useMemo(
    () => new Set(bundle.locations.places.map(({ id }) => id)),
    [bundle.locations.places],
  );
  const regionCustomMarkers = useMemo(
    () =>
      customMarkers.records.filter(
        (marker) =>
          region === 'all' || markerRegion(marker.position, bundle) === region,
      ),
    [bundle, customMarkers.records, region],
  );
  const visibleMarkerCount = useMemo(
    () =>
      regionPlaces.filter(({ place }) => place.minZoom <= zoom).length +
      regionCustomMarkers.length,
    [regionCustomMarkers.length, regionPlaces, zoom],
  );

  useEffect(() => {
    void i18n.changeLanguage(locale);
    localeRef.current = locale;
  }, [locale]);

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.key === 'Escape' && placingMarkerRef.current) {
        placingMarkerRef.current = false;
        setPlacingMarker(false);
        return;
      }
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
    selectedMarkerIdRef.current = selectedMarkerId;
    customMarkerLayerRef.current?.changed();
    if (selectedMarkerId === null) {
      return undefined;
    }
    const animationFrame = window.requestAnimationFrame(() => {
      customMarkerEditorInputRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [selectedMarkerId]);

  useEffect(() => {
    progressByPlaceIdRef.current = progress.byPlaceId;
    markerLayerRef.current?.changed();
  }, [progress.byPlaceId]);

  useEffect(() => {
    placingMarkerRef.current = placingMarker;
    targetRef.current?.classList.toggle('map-canvas--placing-marker', placingMarker);
  }, [placingMarker]);

  useEffect(() => {
    regionRef.current = region;
    markerLayerRef.current?.changed();
    customMarkerLayerRef.current?.changed();
  }, [region]);

  const createMarkerAt = useCallback(
    (position: readonly [number, number]) => {
      placingMarkerRef.current = false;
      setPlacingMarker(false);
      setMarkerError(null);
      void saveCustomMarker(userDatabase, {
        datasetId: dataset.datasetId,
        label: localeRef.current === 'ru' ? 'Личная отметка' : 'Personal marker',
        note: '',
        position,
      })
        .then((marker) => {
          setSelectedId(null);
          setSelectedMarkerId(marker.id);
        })
        .catch((error: unknown) => setMarkerError(errorMessage(error)));
    },
    [
      dataset.datasetId,
      setMarkerError,
      setPlacingMarker,
      setSelectedId,
      setSelectedMarkerId,
    ],
  );

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
        const status = progressByPlaceIdRef.current.get(placeId)?.status ?? 'unvisited';
        return placeId === selectedIdRef.current
          ? SELECTED_PLACE_STYLES[status]
          : PLACE_STYLES[status];
      },
      updateWhileAnimating: true,
      updateWhileInteracting: true,
    });
    markerLayer.setZIndex(10);
    markerLayerRef.current = markerLayer;
    const customMarkerLayer = new VectorLayer({
      source: new VectorSource(),
      style: (feature) => {
        const featureRegion = feature.get('regionId') as string | null;
        if (regionRef.current !== 'all' && featureRegion !== regionRef.current) {
          return undefined;
        }
        const markerId = feature.get('markerId') as string;
        return markerId === selectedMarkerIdRef.current
          ? SELECTED_CUSTOM_MARKER_STYLE
          : CUSTOM_MARKER_STYLE;
      },
      updateWhileAnimating: true,
      updateWhileInteracting: true,
    });
    customMarkerLayer.setZIndex(20);
    customMarkerLayerRef.current = customMarkerLayer;
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
      layers: [...rasterLayers, markerLayer, customMarkerLayer],
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
        layerFilter: (layer) => layer === markerLayer || layer === customMarkerLayer,
      });
      map.getTargetElement().classList.toggle('map-canvas--marker-hover', hit);
    });
    const clickKey = map.on('singleclick', (event) => {
      if (placingMarkerRef.current) {
        const [x = 0, y = 0] = event.coordinate;
        createMarkerAt([x, y]);
        return;
      }
      const feature = map.forEachFeatureAtPixel(event.pixel, (candidate) => candidate, {
        hitTolerance: 6,
        layerFilter: (layer) => layer === markerLayer || layer === customMarkerLayer,
      });
      if (feature) {
        const markerId = feature.get('markerId') as string | undefined;
        if (markerId) {
          setSelectedId(null);
          setSelectedMarkerId(markerId);
        } else {
          setSelectedMarkerId(null);
          setSelectedId(feature.get('placeId') as string);
        }
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
      customMarkerLayerRef.current = null;
    };
  }, [bundle, center, createMarkerAt, extent, projectionDescriptor.cellSize]);

  useEffect(() => {
    const source = customMarkerLayerRef.current?.getSource();
    if (!source) {
      return;
    }
    source.clear();
    source.addFeatures(
      customMarkers.records.map(
        (marker) =>
          new Feature({
            geometry: new Point([...marker.position]),
            markerId: marker.id,
            regionId: markerRegion(marker.position, bundle),
          }),
      ),
    );
    customMarkerLayerRef.current?.changed();
  }, [bundle, customMarkers.records]);

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
    setPlacingMarker(false);
    setSelectedMarkerId(null);
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

  const selectCustomMarker = (marker: CustomMarkerRecord) => {
    setPlacingMarker(false);
    setSelectedId(null);
    setSelectedMarkerId(marker.id);
    window.requestAnimationFrame(() => {
      customMarkerEditorInputRef.current?.focus({ preventScroll: true });
    });
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    const nextZoom = Math.max(view.getZoom() ?? 0, 5);
    if (prefersReducedMotion()) {
      view.setCenter([...marker.position]);
      view.setZoom(nextZoom);
    } else {
      view.animate({ center: [...marker.position], zoom: nextZoom, duration: 220 });
    }
  };

  const toggleMarkerPlacement = () => {
    setMarkerError(null);
    setSelectedId(null);
    setSelectedMarkerId(null);
    setPlacingMarker((current) => !current);
  };

  const closeSelectedCustomMarker = () => {
    const markerId = selectedMarkerId;
    setSelectedMarkerId(null);
    window.requestAnimationFrame(() => {
      if (markerId) {
        const returnTarget = customMarkerButtonRefs.current.get(markerId);
        (returnTarget ?? customMarkerHeadingRef.current)?.focus({ preventScroll: true });
      }
    });
  };

  const finishCustomMarkerDeletion = () => {
    setSelectedMarkerId(null);
    window.requestAnimationFrame(() => {
      customMarkerHeadingRef.current?.focus({ preventScroll: true });
    });
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

          <details className="ledger-data-tools">
            <summary>{t('map.dataTools')}</summary>
            <DataTools
              dataset={dataset}
              datasetSnapshots={datasetSnapshots}
              knownPlaceIds={knownPlaceIds}
              locale={locale}
            />
          </details>

          <div className="result-summary" aria-live="polite">
            <span>{t('map.found', { count: regionPlaces.length })}</span>
            {query ? <strong>{results.length}</strong> : null}
          </div>

          <div className="place-results">
            <section className="custom-marker-results" aria-labelledby="custom-marker-results-title">
              <header>
                <h2
                  id="custom-marker-results-title"
                  ref={customMarkerHeadingRef}
                  tabIndex={-1}
                >
                  {t('map.personalMarkers')}
                </h2>
                <strong>{regionCustomMarkers.length}</strong>
              </header>
              {regionCustomMarkers.length ? (
                <ul>
                  {regionCustomMarkers.map((marker) => (
                    <li key={marker.id}>
                      <button
                        ref={(node) => {
                          if (node) {
                            customMarkerButtonRefs.current.set(marker.id, node);
                          } else {
                            customMarkerButtonRefs.current.delete(marker.id);
                          }
                        }}
                        type="button"
                        className={
                          selectedMarkerId === marker.id
                            ? 'place-result custom-marker-result place-result--selected'
                            : 'place-result custom-marker-result'
                        }
                        aria-pressed={selectedMarkerId === marker.id}
                        onClick={() => selectCustomMarker(marker)}
                      >
                        <span className="result-marker result-marker--custom" aria-hidden="true" />
                        <span>
                          <strong>{marker.label}</strong>
                          <small>
                            X {formatCoordinate(marker.position[0], locale)} · Y{' '}
                            {formatCoordinate(marker.position[1], locale)}
                          </small>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>{t('map.noPersonalMarkers')}</p>
              )}
            </section>
            {results.length ? (
              results.map((place) => {
                const status = progress.byPlaceId.get(place.id)?.status ?? 'unvisited';
                return (
                  <button
                    key={place.id}
                    type="button"
                    className={selectedId === place.id ? 'place-result place-result--selected' : 'place-result'}
                    onClick={() => selectPlace(place)}
                  >
                    <span
                      className={`result-marker result-marker--${status}`}
                      aria-hidden="true"
                    />
                    <span>
                      <strong>{place.name}</strong>
                      <small>
                        {t(`placeType.${place.place.type}`)} ·{' '}
                        {t(place.place.regionId === 'solstheim' ? 'map.solstheim' : 'map.vvardenfell')}
                      </small>
                    </span>
                  </button>
                );
              })
            ) : (
              <p className="no-results">{t('map.noResults')}</p>
            )}
          </div>
        </aside>

        <div className="original-map-stage">
          <div
            ref={targetRef}
            className="map-canvas"
            tabIndex={0}
            aria-label={t('map.mapAria')}
            aria-describedby={placingMarker ? 'marker-placement-hint' : undefined}
            onKeyDown={(event) => {
              if (!placingMarker || (event.key !== 'Enter' && event.key !== ' ')) {
                return;
              }
              const [x = 0, y = 0] = mapRef.current?.getView().getCenter() ?? center;
              event.preventDefault();
              createMarkerAt([x, y]);
            }}
          />

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
            <button
              type="button"
              className="add-marker-tool"
              aria-label={placingMarker ? t('map.cancelMarker') : t('map.addMarker')}
              aria-pressed={placingMarker}
              onClick={toggleMarkerPlacement}
            >
              M+
            </button>
          </div>

          <div className="marker-legend" aria-label="Marker legend">
            <span><i className="legend-square" />{t('map.unvisited')}</span>
            <span><i className="legend-square legend-square--active" />{t('map.active')}</span>
            <span><i className="legend-square legend-square--visited" />{t('map.visited')}</span>
            <span><i className="legend-square legend-square--custom" />{t('map.personalMarker')}</span>
          </div>

          {placingMarker ? (
            <p id="marker-placement-hint" className="marker-placement-hint" role="status">
              {t('map.placeMarkerHint')}
            </p>
          ) : null}
          {markerError ? (
            <p className="marker-placement-error" role="alert">
              {markerError}
            </p>
          ) : null}

          {selectedPlace ? (
            <PlaceCard
              datasetId={dataset.datasetId}
              place={selectedPlace}
              locale={locale}
              progress={progress.byPlaceId.get(selectedPlace.id)}
              onClose={() => setSelectedId(null)}
            />
          ) : null}
          {selectedMarker ? (
            <CustomMarkerCard
              marker={selectedMarker}
              locale={locale}
              inputRef={customMarkerEditorInputRef}
              onClose={closeSelectedCustomMarker}
              onDeleted={finishCustomMarkerDeletion}
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
  readonly datasetId: string;
  readonly place: PlaceView;
  readonly locale: Locale;
  readonly progress: ProgressRecord | undefined;
  readonly onClose: () => void;
}

function PlaceCard({ datasetId, place, locale, progress, onClose }: PlaceCardProps) {
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
      <PlaceProgressEditor
        key={`${datasetId}\0${place.id}`}
        datasetId={datasetId}
        placeId={place.id}
        locale={locale}
        {...(progress ? { progress } : {})}
      />
    </article>
  );
}

interface CustomMarkerCardProps {
  readonly marker: CustomMarkerRecord;
  readonly locale: Locale;
  readonly inputRef: Ref<HTMLInputElement>;
  readonly onClose: () => void;
  readonly onDeleted: () => void;
}

function CustomMarkerCard({ marker, locale, inputRef, onClose, onDeleted }: CustomMarkerCardProps) {
  const { t } = useTranslation();
  return (
    <article className="place-card custom-marker-card" aria-labelledby="selected-marker-title">
      <button
        className="place-card-close"
        type="button"
        onClick={onClose}
        aria-label={t('map.closeMarker')}
      >
        ×
      </button>
      <span className="place-card-index">{t('map.personalMarker')}</span>
      <h2 id="selected-marker-title">{marker.label}</h2>
      <p className="custom-marker-coordinate">
        X {formatCoordinate(marker.position[0], locale)} · Y{' '}
        {formatCoordinate(marker.position[1], locale)}
      </p>
      <CustomMarkerEditor
        key={marker.id}
        marker={marker}
        locale={locale}
        inputRef={inputRef}
        onDeleted={onDeleted}
      />
    </article>
  );
}
