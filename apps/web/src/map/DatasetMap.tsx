import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type Ref,
} from 'react';
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
import TileLayer from 'ol/layer/Tile.js';
import VectorLayer from 'ol/layer/Vector.js';
import { unByKey } from 'ol/Observable.js';
import type Tile from 'ol/Tile.js';
import ImageStatic from 'ol/source/ImageStatic.js';
import VectorSource from 'ol/source/Vector.js';
import XYZ from 'ol/source/XYZ.js';
import Fill from 'ol/style/Fill.js';
import RegularShape from 'ol/style/RegularShape.js';
import Stroke from 'ol/style/Stroke.js';
import Style from 'ol/style/Style.js';
import { useTranslation } from 'react-i18next';
import {
  DatasetAssetsMissingError,
  loadDataset,
  type DatasetBundle,
} from '../data/loadDataset';
import { buildPlaceViews, PlaceSearch, type PlaceView } from '../data/placeSearch';
import type { MapUrlState, MapUrlView } from '../navigation/mapUrlState';
import { normalizeMapUrlState } from '../navigation/normalizeMapUrlState';
import { userDatabase } from '../storage/database';
import {
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
  BASEMAP_BRIGHTNESS_FACTOR,
  BASEMAP_CONTRAST_FACTOR,
  createOverscaledViewResolutions,
  loadOpaqueImageTile,
  requiresRuntimeBasemapAdjustment,
} from './basemapPresentation';
import {
  SparseTileCoverageIndex,
  createSparseTileUrlFunction,
  createTes3TileGrid,
} from './sparseTiles';
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

interface DatasetMapProps extends MapTitlebarProps {
  readonly datasetSnapshots: Readonly<Record<string, string>>;
  readonly navigationState: MapUrlState;
  readonly navigationRevision: number;
  readonly onNavigationChange: (
    state: MapUrlState,
    mode: 'push' | 'replace',
  ) => void;
}

type RegionFilter = string;

type LoadState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly bundle: DatasetBundle }
  | { readonly status: 'missing'; readonly message: string }
  | { readonly status: 'error'; readonly message: string };

interface BasemapRuntimeState {
  readonly pending: number;
  readonly failures: number;
  readonly missing: boolean;
}

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
const BASEMAP_PRESENTATION_STYLE = {
  '--basemap-brightness': String(BASEMAP_BRIGHTNESS_FACTOR),
  '--basemap-contrast': String(BASEMAP_CONTRAST_FACTOR),
} as CSSProperties;

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
  bundle: DatasetBundle,
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
  return error instanceof Error ? error.message : 'Unknown dataset error';
}

function regionTitle(dataset: DatasetManifest, regionId: string): string {
  const region = dataset.regions.find(({ id }) => id === regionId);
  return region?.title.en ?? regionId;
}

function regionExtent(
  bundle: DatasetBundle,
  regionId: string,
  worldExtent: readonly [number, number, number, number],
  cellSize: number,
): readonly [number, number, number, number] | null {
  const rasterExtents = bundle.mapAssets.rasters
    .filter((raster) => raster.regionId === regionId)
    .map(({ extent }) => extent);
  if (rasterExtents.length > 0) {
    return [
      Math.min(...rasterExtents.map(([minX]) => minX)),
      Math.min(...rasterExtents.map(([, minY]) => minY)),
      Math.max(...rasterExtents.map(([, , maxX]) => maxX)),
      Math.max(...rasterExtents.map(([, , , maxY]) => maxY)),
    ];
  }

  const positions = bundle.locations.places
    .filter((place) => place.regionId === regionId)
    .map(({ mapPosition }) => mapPosition);
  if (positions.length === 0) {
    return null;
  }
  const padding = cellSize * 2;
  const [worldMinX, worldMinY, worldMaxX, worldMaxY] = worldExtent;
  return [
    Math.max(worldMinX, Math.min(...positions.map(([x]) => x)) - padding),
    Math.max(worldMinY, Math.min(...positions.map(([, y]) => y)) - padding),
    Math.min(worldMaxX, Math.max(...positions.map(([x]) => x)) + padding),
    Math.min(worldMaxY, Math.max(...positions.map(([, y]) => y)) + padding),
  ];
}

function formatCoordinate(value: number): string {
  return Math.round(value).toLocaleString('en-US');
}

function navigationStatesMatch(
  left: MapUrlState,
  right: MapUrlState,
  coordinateTolerance = 0,
  zoomTolerance = 0,
): boolean {
  return left.datasetId === right.datasetId &&
    left.regionId === right.regionId &&
    left.placeId === right.placeId &&
    (left.view === right.view ||
      (left.view !== null &&
        right.view !== null &&
        Math.abs(left.view.center[0] - right.view.center[0]) <= coordinateTolerance &&
        Math.abs(left.view.center[1] - right.view.center[1]) <= coordinateTolerance &&
        Math.abs(left.view.zoom - right.view.zoom) <= zoomTolerance));
}

export function DatasetMap({
  dataset,
  datasetSnapshots,
  navigationState,
  navigationRevision,
  onNavigationChange,
  onBack,
}: DatasetMapProps) {
  const { t } = useTranslation();
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void loadDataset(dataset, controller.signal)
      .then(async (bundle) => {
        await ensureDatasetSnapshot(
          userDatabase,
          dataset.datasetId,
          dataset.snapshotId,
        );
        if (controller.signal.aborted) {
          return;
        }
        setLoadState({ status: 'ready', bundle });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadState(
            error instanceof DatasetAssetsMissingError
              ? { status: 'missing', message: error.message }
              : { status: 'error', message: errorMessage(error) },
          );
        }
      });
    return () => controller.abort();
  }, [dataset, loadAttempt]);

  if (loadState.status !== 'ready') {
    return (
      <main className="map-screen dataset-map-screen" aria-labelledby="map-title">
        <MapTitlebar dataset={dataset} onBack={onBack} />
        <section className="dataset-load-state" role={loadState.status === 'error' ? 'alert' : 'status'}>
          {loadState.status === 'loading' ? (
            <>
              <span className="load-indicator" aria-hidden="true" />
              <p>{t('map.loading')}</p>
            </>
          ) : loadState.status === 'missing' ? (
            <>
              <span className="load-state-code">DATA MISSING</span>
              <h2>{t('map.missingData')}</h2>
              <p>{loadState.message}</p>
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
    <DatasetMapReady
      dataset={dataset}
      datasetSnapshots={datasetSnapshots}
      bundle={loadState.bundle}
      navigationState={navigationState}
      navigationRevision={navigationRevision}
      onNavigationChange={onNavigationChange}
      onBack={onBack}
    />
  );
}

function MapTitlebar({ dataset, onBack }: MapTitlebarProps) {
  const { t } = useTranslation();
  return (
    <header className="window-titlebar map-titlebar">
      <button className="back-button" type="button" onClick={onBack}>
        <span aria-hidden="true">←</span>
        {t('map.versions')}
      </button>
      <div className="map-title-copy">
        <span className="titlebar-kicker">{dataset.mapKey.toUpperCase()} / TES3:WORLD</span>
        <h1 id="map-title">{dataset.title.en}</h1>
      </div>
      <span className="titlebar-state">{t('map.local')}</span>
    </header>
  );
}

interface DatasetMapReadyProps extends DatasetMapProps {
  readonly bundle: DatasetBundle;
}

function DatasetMapReady({
  dataset,
  datasetSnapshots,
  bundle,
  navigationState,
  navigationRevision,
  onNavigationChange,
  onBack,
}: DatasetMapReadyProps) {
  const { t } = useTranslation();
  const locale: Locale = 'en';
  const targetRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const mapRef = useRef<Map | null>(null);
  const failedTilesRef = useRef(new Set<Tile>());
  const markerLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const customMarkerLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const customMarkerButtonRefs = useRef(new globalThis.Map<string, HTMLButtonElement>());
  const customMarkerEditorInputRef = useRef<HTMLInputElement>(null);
  const customMarkerHeadingRef = useRef<HTMLHeadingElement>(null);
  const progressByPlaceIdRef = useRef<ReadonlyMap<string, ProgressRecord>>(
    new globalThis.Map<string, ProgressRecord>(),
  );
  const placingMarkerRef = useRef(false);
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
  const availableRegionIds = useMemo(() => {
    const placeRegions = new Set(bundle.locations.places.map(({ regionId }) => regionId));
    return dataset.regions
      .filter(
        ({ id, kind, status }) =>
          kind === 'exterior' && status === 'available' && placeRegions.has(id),
      )
      .map(({ id }) => id);
  }, [bundle.locations.places, dataset.regions]);

  const places = useMemo(
    () =>
      buildPlaceViews(bundle.locations.places, [...bundle.locales.values()], locale).sort(
        (left, right) => left.name.localeCompare(right.name, locale),
      ),
    [bundle, locale],
  );
  const primaryPyramid = bundle.mapAssets.tilePyramids?.[0];
  const viewResolutions = useMemo(
    () => primaryPyramid ? createOverscaledViewResolutions(primaryPyramid) : undefined,
    [primaryPyramid],
  );
  const minimumZoom = primaryPyramid?.minZoom ?? 0;
  const maximumZoom = viewResolutions ? viewResolutions.length - 1 : 12;
  const placeRegions = useMemo(
    () => new globalThis.Map(places.map(({ id, place }) => [id, place.regionId])),
    [places],
  );
  const normalizedNavigationState = useMemo(
    () => normalizeMapUrlState(navigationState, {
      datasetId: dataset.datasetId,
      availableRegionIds: new Set(availableRegionIds),
      placeRegions,
      extent,
      minimumZoom,
      maximumZoom,
    }),
    [
      availableRegionIds,
      dataset.datasetId,
      extent,
      maximumZoom,
      minimumZoom,
      navigationState,
      placeRegions,
    ],
  );
  const initialNavigationRef = useRef(normalizedNavigationState);
  const navigationStateRef = useRef(normalizedNavigationState);
  const selfAuthoredNavigationRef = useRef<MapUrlState | null>(null);
  const handledNavigationRevisionRef = useRef(navigationRevision);
  const hasHandledInitialNavigationRef = useRef(false);
  const selectedIdRef = useRef<string | null>(normalizedNavigationState.placeId);
  const selectedMarkerIdRef = useRef<string | null>(null);
  const regionRef = useRef<RegionFilter>(normalizedNavigationState.regionId);
  const zoomRef = useRef(normalizedNavigationState.view?.zoom ?? 0);
  const [query, setQuery] = useState('');
  const [region, setRegion] = useState<RegionFilter>(normalizedNavigationState.regionId);
  const [selectedId, setSelectedId] = useState<string | null>(
    normalizedNavigationState.placeId,
  );
  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null);
  const [placingMarker, setPlacingMarker] = useState(false);
  const [markerError, setMarkerError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<CursorReadout | null>(null);
  const [viewState, setViewState] = useState<MapUrlView | null>(normalizedNavigationState.view);
  const [zoom, setZoom] = useState(normalizedNavigationState.view?.zoom ?? 0);
  const [basemapState, setBasemapState] = useState<BasemapRuntimeState>({
    pending: 0,
    failures: 0,
    missing: false,
  });
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
        (marker) => {
          const markerRegionId = markerRegion(marker.position, bundle);
          return region === 'all' || markerRegionId === null || markerRegionId === region;
        },
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

  const commitNavigation = useCallback(
    (nextState: MapUrlState, mode: 'push' | 'replace') => {
      navigationStateRef.current = nextState;
      selfAuthoredNavigationRef.current = nextState;
      onNavigationChange(nextState, mode);
    },
    [onNavigationChange],
  );

  const createMarkerAt = useCallback(
    (position: readonly [number, number]) => {
      placingMarkerRef.current = false;
      setPlacingMarker(false);
      setMarkerError(null);
      void saveCustomMarker(userDatabase, {
        datasetId: dataset.datasetId,
        label: 'Personal marker',
        note: '',
        position,
        })
        .then((marker) => {
          setSelectedId(null);
          setSelectedMarkerId(marker.id);
          if (navigationStateRef.current.placeId !== null) {
            commitNavigation(
              { ...navigationStateRef.current, placeId: null },
              'push',
            );
          }
        })
        .catch((error: unknown) => setMarkerError(errorMessage(error)));
    },
    [
      dataset.datasetId,
      commitNavigation,
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

    const failedTiles = failedTilesRef.current;
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
    const pyramidContexts = (bundle.mapAssets.tilePyramids ?? []).map((pyramid) => {
      const coverage = bundle.tileCoverages.get(pyramid.id);
      if (!coverage) {
        throw new Error(`Missing validated coverage for ${pyramid.id}`);
      }
      const tileGrid = createTes3TileGrid(pyramid);
      const coverageIndex = new SparseTileCoverageIndex(coverage);
      const runtimeAdjustment = requiresRuntimeBasemapAdjustment(pyramid);
      const source = new XYZ({
        projection,
        tileGrid,
        tileUrlFunction: createSparseTileUrlFunction(pyramid, coverage),
        ...(runtimeAdjustment ? { tileLoadFunction: loadOpaqueImageTile } : {}),
        wrapX: false,
        interpolate: true,
        transition: 0,
      });
      const layer = new TileLayer({
        className: runtimeAdjustment
          ? 'ol-layer dataset-basemap-layer dataset-basemap-layer--runtime-adjusted'
          : 'ol-layer dataset-basemap-layer',
        source,
        extent: [...pyramid.extent],
      });
      return { coverageIndex, layer, pyramid, source, tileGrid };
    });
    const tileSources = pyramidContexts.map(({ source }) => source);
    failedTiles.clear();
    setBasemapState({ pending: 0, failures: 0, missing: false });
    const tileEventKeys = tileSources.flatMap((source) => [
      source.on('tileloadstart', () => {
        setBasemapState((current) => ({ ...current, pending: current.pending + 1 }));
      }),
      source.on('tileloadend', (event) => {
        failedTiles.delete(event.tile);
        setBasemapState((current) => ({
          ...current,
          pending: Math.max(0, current.pending - 1),
        }));
      }),
      source.on('tileloaderror', (event) => {
        failedTiles.add(event.tile);
        setBasemapState((current) => ({
          ...current,
          pending: Math.max(0, current.pending - 1),
          failures: current.failures + 1,
        }));
      }),
    ]);
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
        if (
          regionRef.current !== 'all' &&
          featureRegion !== null &&
          featureRegion !== regionRef.current
        ) {
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
    const initialNavigation = initialNavigationRef.current;
    const initialPlace = initialNavigation.placeId === null
      ? null
      : places.find(({ id }) => id === initialNavigation.placeId) ?? null;
    const initialView = initialNavigation.view ?? (
      initialPlace === null
        ? null
        : {
            center: initialPlace.place.mapPosition,
            zoom: Math.min(
              maximumZoom,
              Math.max(minimumZoom, initialPlace.place.minZoom + 1, 5),
            ),
          }
    );
    const view = new View({
      projection,
      center: initialView ? [...initialView.center] : center,
      zoom: initialView?.zoom ?? 1,
      minZoom: minimumZoom,
      maxZoom: maximumZoom,
      ...(viewResolutions ? { resolutions: viewResolutions } : {}),
      extent,
      showFullExtent: true,
      constrainOnlyCenter: true,
    });
    const map = new Map({
      target: targetRef.current,
      layers: [
        ...rasterLayers,
        ...pyramidContexts.map(({ layer }) => layer),
        markerLayer,
        customMarkerLayer,
      ],
      view,
      controls: [],
    });
    mapRef.current = map;
    if (initialView === null) {
      const initialExtent = initialNavigation.regionId === 'all'
        ? extent
        : regionExtent(
            bundle,
            initialNavigation.regionId,
            extent,
            projectionDescriptor.cellSize,
          ) ?? extent;
      view.fit([...initialExtent], {
        duration: 0,
        maxZoom: Math.min(4, view.getMaxZoom()),
        padding: [44, 44, 44, 44],
      });
    }
    zoomRef.current = view.getZoom() ?? 0;
    setZoom(zoomRef.current);
    markerLayer.changed();

    const updateCoverageAtCenter = () => {
      const viewCenter = view.getCenter();
      const resolution = view.getResolution();
      if (!viewCenter || resolution === undefined || pyramidContexts.length === 0) {
        setBasemapState((current) => ({ ...current, missing: false }));
        return;
      }
      const covered = pyramidContexts.some(({ coverageIndex, pyramid, tileGrid }) => {
        const z = tileGrid.getZForResolution(resolution);
        if (z < pyramid.minZoom || z > pyramid.maxZoom) {
          return false;
        }
        return coverageIndex.has(tileGrid.getTileCoordForCoordAndZ(viewCenter, z));
      });
      setBasemapState((current) => ({ ...current, missing: !covered }));
    };
    updateCoverageAtCenter();

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
          if (navigationStateRef.current.placeId !== null) {
            commitNavigation(
              { ...navigationStateRef.current, placeId: null },
              'push',
            );
          }
        } else {
          const placeId = feature.get('placeId') as string;
          setSelectedMarkerId(null);
          setSelectedId(placeId);
          selectedIdRef.current = placeId;
          commitNavigation(
            { ...navigationStateRef.current, placeId },
            'push',
          );
        }
      }
    });
    const resolutionKey = view.on('change:resolution', () => {
      zoomRef.current = view.getZoom() ?? 0;
      setZoom(zoomRef.current);
      markerLayer.changed();
    });
    const updateNavigationFromView = () => {
      const currentCenter = view.getCenter();
      const currentZoom = view.getZoom();
      if (!currentCenter || currentZoom === undefined) {
        return;
      }
      const [currentX = 0, currentY = 0] = currentCenter;
      const nextView: MapUrlView = {
        center: [currentX, currentY],
        zoom: currentZoom,
      };
      setViewState(nextView);
      commitNavigation(
        {
          ...navigationStateRef.current,
          datasetId: dataset.datasetId,
          view: nextView,
        },
        'replace',
      );
    };
    const handleMoveEnd = () => {
      updateCoverageAtCenter();
      updateNavigationFromView();
    };
    const moveEndKey = map.on('moveend', handleMoveEnd);
    updateNavigationFromView();
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
      unByKey(moveEndKey);
      unByKey(tileEventKeys);
      viewport.removeEventListener('pointerleave', clearCursor);
      map.setTarget(undefined);
      mapRef.current = null;
      failedTiles.clear();
      markerLayerRef.current = null;
      customMarkerLayerRef.current = null;
    };
  }, [
    bundle,
    center,
    commitNavigation,
    createMarkerAt,
    dataset.datasetId,
    extent,
    maximumZoom,
    minimumZoom,
    places,
    projectionDescriptor.cellSize,
    viewResolutions,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    if (!hasHandledInitialNavigationRef.current) {
      hasHandledInitialNavigationRef.current = true;
      return;
    }

    const isExternalPop = handledNavigationRevisionRef.current !== navigationRevision;
    handledNavigationRevisionRef.current = navigationRevision;
    const selfAuthored = selfAuthoredNavigationRef.current;
    const isSelfAuthored = !isExternalPop && selfAuthored !== null && navigationStatesMatch(
      selfAuthored,
      normalizedNavigationState,
      1,
      0.01,
    );
    selfAuthoredNavigationRef.current = null;
    navigationStateRef.current = normalizedNavigationState;
    regionRef.current = normalizedNavigationState.regionId;
    selectedIdRef.current = normalizedNavigationState.placeId;
    setRegion(normalizedNavigationState.regionId);
    setSelectedId(normalizedNavigationState.placeId);

    if (
      isExternalPop ||
      !navigationStatesMatch(navigationState, normalizedNavigationState)
    ) {
      onNavigationChange(normalizedNavigationState, 'replace');
    }
    if (isSelfAuthored) {
      return;
    }

    setSelectedMarkerId(null);
    setPlacingMarker(false);
    const view = map.getView();
    view.cancelAnimations();
    if (normalizedNavigationState.view !== null) {
      const requestedView = normalizedNavigationState.view;
      const currentCenter = view.getCenter();
      const currentZoom = view.getZoom();
      const [currentX = 0, currentY = 0] = currentCenter ?? [];
      if (
        !currentCenter ||
        Math.abs(currentX - requestedView.center[0]) > 1 ||
        Math.abs(currentY - requestedView.center[1]) > 1
      ) {
        view.setCenter([...requestedView.center]);
      }
      if (currentZoom === undefined || Math.abs(currentZoom - requestedView.zoom) > 0.01) {
        view.setZoom(requestedView.zoom);
      }
      return;
    }

    const requestedPlace = normalizedNavigationState.placeId === null
      ? null
      : places.find(({ id }) => id === normalizedNavigationState.placeId) ?? null;
    if (requestedPlace) {
      view.setCenter([...requestedPlace.place.mapPosition]);
      view.setZoom(Math.min(
        view.getMaxZoom(),
        Math.max(view.getMinZoom(), requestedPlace.place.minZoom + 1, 5),
      ));
      return;
    }
    const requestedExtent = normalizedNavigationState.regionId === 'all'
      ? extent
      : regionExtent(
          bundle,
          normalizedNavigationState.regionId,
          extent,
          projectionDescriptor.cellSize,
        ) ?? extent;
    view.fit([...requestedExtent], {
      duration: 0,
      maxZoom: Math.min(4, view.getMaxZoom()),
      padding: [48, 48, 48, 48],
    });
  }, [
    bundle,
    extent,
    navigationState,
    navigationRevision,
    normalizedNavigationState,
    onNavigationChange,
    places,
    projectionDescriptor.cellSize,
  ]);

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
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    view.fit([...nextExtent], {
      duration: prefersReducedMotion() ? 0 : 180,
      maxZoom: Math.min(4, view.getMaxZoom()),
      padding: [48, 48, 48, 48],
    });
  };

  const navigationWithCurrentView = (): MapUrlState => {
    const view = mapRef.current?.getView();
    const currentCenter = view?.getCenter();
    const currentZoom = view?.getZoom();
    const [currentX = 0, currentY = 0] = currentCenter ?? [];
    return {
      ...navigationStateRef.current,
      datasetId: dataset.datasetId,
      view: currentCenter && currentZoom !== undefined
        ? { center: [currentX, currentY], zoom: currentZoom }
        : navigationStateRef.current.view,
    };
  };

  const selectRegion = (nextRegion: RegionFilter) => {
    const nextPlaceId = selectedPlace !== null &&
        nextRegion !== 'all' &&
        selectedPlace.place.regionId !== nextRegion
      ? null
      : selectedId;
    regionRef.current = nextRegion;
    selectedIdRef.current = nextPlaceId;
    setRegion(nextRegion);
    setSelectedId(nextPlaceId);
    commitNavigation(
      {
        ...navigationWithCurrentView(),
        regionId: nextRegion,
        placeId: nextPlaceId,
      },
      'push',
    );
    if (nextRegion === 'all') {
      fitExtent(extent);
      return;
    }
    const nextExtent = regionExtent(
      bundle,
      nextRegion,
      extent,
      projectionDescriptor.cellSize,
    );
    if (nextExtent) {
      fitExtent(nextExtent);
    }
  };

  const selectPlace = (place: PlaceView) => {
    setPlacingMarker(false);
    setSelectedMarkerId(null);
    setSelectedId(place.id);
    selectedIdRef.current = place.id;
    commitNavigation(
      { ...navigationWithCurrentView(), placeId: place.id },
      'push',
    );
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    const nextZoom = Math.min(
      view.getMaxZoom(),
      Math.max(view.getZoom() ?? 0, place.place.minZoom + 1, 5),
    );
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
    selectedIdRef.current = null;
    if (navigationStateRef.current.placeId !== null) {
      commitNavigation(
        { ...navigationWithCurrentView(), placeId: null },
        'push',
      );
    }
    window.requestAnimationFrame(() => {
      customMarkerEditorInputRef.current?.focus({ preventScroll: true });
    });
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    const nextZoom = Math.min(view.getMaxZoom(), Math.max(view.getZoom() ?? 0, 5));
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
    selectedIdRef.current = null;
    if (navigationStateRef.current.placeId !== null) {
      commitNavigation(
        { ...navigationWithCurrentView(), placeId: null },
        'push',
      );
    }
    setPlacingMarker((current) => !current);
  };

  const closeSelectedPlace = () => {
    setSelectedId(null);
    selectedIdRef.current = null;
    commitNavigation(
      { ...navigationWithCurrentView(), placeId: null },
      'push',
    );
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

  const retryBasemap = () => {
    setBasemapState((current) => ({ ...current, failures: 0, pending: 0 }));
    const failedTiles = [...failedTilesRef.current];
    failedTilesRef.current.clear();
    failedTiles.forEach((tile) => tile.load());
  };

  return (
    <main className="map-screen dataset-map-screen" aria-labelledby="map-title">
      <MapTitlebar dataset={dataset} onBack={onBack} />

      <section className="dataset-workspace">
        <aside className="map-ledger" aria-label={t('map.searchLabel')}>
          <div className="ledger-heading">
            <span>INDEX / 001–{places.length.toLocaleString('en-US')}</span>
            <span className="locale-badge">EN</span>
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
            {(['all', ...availableRegionIds] as const).map((regionId) => (
              <button
                key={regionId}
                type="button"
                aria-pressed={region === regionId}
                onClick={() => selectRegion(regionId)}
              >
                {regionId === 'all'
                  ? t('map.allRegions')
                  : regionTitle(dataset, regionId)}
              </button>
            ))}
          </fieldset>

          <details className="ledger-data-tools">
            <summary>{t('map.dataTools')}</summary>
            <DataTools
              datasetId={dataset.datasetId}
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
                            X {formatCoordinate(marker.position[0])} · Y{' '}
                            {formatCoordinate(marker.position[1])}
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
                        {regionTitle(dataset, place.place.regionId)}
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

        <div className="dataset-map-stage">
          <div
            ref={targetRef}
            className="map-canvas"
            style={BASEMAP_PRESENTATION_STYLE}
            tabIndex={0}
            data-view-x={viewState?.center[0]}
            data-view-y={viewState?.center[1]}
            data-view-z={viewState?.zoom}
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

          {basemapState.failures > 0 ? (
            <div className="basemap-state basemap-state--error" role="alert">
              <span>{t('map.basemapError', { count: basemapState.failures })}</span>
              <button type="button" onClick={retryBasemap}>{t('map.retry')}</button>
            </div>
          ) : basemapState.pending > 0 ? (
            <p className="basemap-state" role="status">
              {t('map.basemapLoading', { count: basemapState.pending })}
            </p>
          ) : basemapState.missing ? (
            <p className="basemap-state basemap-state--missing" role="status">
              {t('map.basemapMissing')}
            </p>
          ) : null}

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
              regionName={regionTitle(dataset, selectedPlace.place.regionId)}
              progress={progress.byPlaceId.get(selectedPlace.id)}
              onClose={closeSelectedPlace}
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
          X&nbsp;<strong>{cursor ? formatCoordinate(cursor.world[0]) : '—'}</strong>
        </span>
        <span>
          Y&nbsp;<strong>{cursor ? formatCoordinate(cursor.world[1]) : '—'}</strong>
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
  readonly regionName: string;
  readonly progress: ProgressRecord | undefined;
  readonly onClose: () => void;
}

function PlaceCard({ datasetId, place, locale, regionName, progress, onClose }: PlaceCardProps) {
  const { t } = useTranslation();
  const plugins = [...new Set(place.place.sources.map(({ plugin }) => plugin))].join(', ');
  return (
    <article className="place-card" aria-labelledby="selected-place-title">
      <button className="place-card-close" type="button" onClick={onClose} aria-label={t('map.closeCard')}>
        ×
      </button>
      <span className="place-card-index">{t('map.cardIndex')}</span>
      <h2 id="selected-place-title">{place.name}</h2>
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
            {formatCoordinate(place.place.mapPosition[0])} :{' '}
            {formatCoordinate(place.place.mapPosition[1])}
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
        X {formatCoordinate(marker.position[0])} · Y{' '}
        {formatCoordinate(marker.position[1])}
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
