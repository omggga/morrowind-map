import { useEffect, useMemo, useRef, useState } from 'react';
import type { DatasetManifest } from '@morrowind-map/contracts';
import Feature from 'ol/Feature.js';
import Map from 'ol/Map.js';
import View from 'ol/View.js';
import LineString from 'ol/geom/LineString.js';
import Point from 'ol/geom/Point.js';
import VectorLayer from 'ol/layer/Vector.js';
import VectorSource from 'ol/source/Vector.js';
import { unByKey } from 'ol/Observable.js';
import CircleStyle from 'ol/style/Circle.js';
import Fill from 'ol/style/Fill.js';
import Stroke from 'ol/style/Stroke.js';
import Style from 'ol/style/Style.js';
import {
  buildCellGrid,
  configureTes3Projection,
  formatWorldCoordinate,
  worldToCell,
  type CellCoordinate,
  type WorldCoordinate,
} from './tes3Projection';
import { OriginalMap } from './OriginalMap';

interface Tes3MapProps {
  readonly dataset: DatasetManifest;
  readonly datasetSnapshots: Readonly<Record<string, string>>;
  readonly onBack: () => void;
}

interface CursorReadout {
  readonly world: WorldCoordinate;
  readonly cell: CellCoordinate;
}

const CELL_STYLE = new Style({
  stroke: new Stroke({ color: 'rgba(169, 149, 88, 0.22)', width: 1 }),
});

const AXIS_STYLE = new Style({
  stroke: new Stroke({ color: 'rgba(219, 200, 137, 0.72)', width: 1.5 }),
});

const ORIGIN_STYLE = new Style({
  image: new CircleStyle({
    radius: 6,
    fill: new Fill({ color: '#171914' }),
    stroke: new Stroke({ color: '#f0df9b', width: 2 }),
  }),
});

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

export function Tes3Map({ dataset, datasetSnapshots, onBack }: Tes3MapProps) {
  if (dataset.mapKey === 'original') {
    return (
      <OriginalMap
        dataset={dataset}
        datasetSnapshots={datasetSnapshots}
        onBack={onBack}
      />
    );
  }

  return (
    <Tes3PlaceholderMap
      dataset={dataset}
      datasetSnapshots={datasetSnapshots}
      onBack={onBack}
    />
  );
}

function Tes3PlaceholderMap({ dataset, onBack }: Tes3MapProps) {
  const targetRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const [cursor, setCursor] = useState<CursorReadout | null>(null);
  const [zoom, setZoom] = useState(0);
  const projection = dataset.map.projection;
  const extent = useMemo<[number, number, number, number]>(() => {
    const [minX, minY, maxX, maxY] = projection.extent;
    return [minX, minY, maxX, maxY];
  }, [projection.extent]);
  const center = useMemo<[number, number]>(() => {
    const [x, y] = projection.center;
    return [x, y];
  }, [projection.center]);
  const title = dataset.title.ru ?? dataset.title.en;

  useEffect(() => {
    if (!targetRef.current) {
      return undefined;
    }

    const gridFeatures = buildCellGrid(extent, projection.cellSize).map(
      ({ axis, coordinates }) =>
        new Feature({
          geometry: new LineString(coordinates.map((point) => [...point])),
          gridKind: axis ? 'axis' : 'cell',
        }),
    );
    const originFeature = new Feature({ geometry: new Point([0, 0]), gridKind: 'origin' });
    const gridLayer = new VectorLayer({
      source: new VectorSource({ features: [...gridFeatures, originFeature] }),
      style: (feature) => {
        const kind = feature.get('gridKind') as string;
        return kind === 'origin' ? ORIGIN_STYLE : kind === 'axis' ? AXIS_STYLE : CELL_STYLE;
      },
      updateWhileAnimating: true,
    });
    const view = new View({
      projection: configureTes3Projection(extent),
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
      layers: [gridLayer],
      view,
      controls: [],
    });
    mapRef.current = map;
    targetRef.current.focus({ preventScroll: true });

    const pointerMoveKey = map.on('pointermove', (event) => {
      if (event.dragging) {
        return;
      }

      const [x = 0, y = 0] = event.coordinate;
      const world: WorldCoordinate = [x, y];
      setCursor({
        world,
        cell: worldToCell(world, projection.cellSize),
      });
    });
    const resolutionKey = view.on('change:resolution', () => {
      setZoom(view.getZoom() ?? 0);
    });
    view.fit(extent, {
      duration: 0,
      maxZoom: 4,
      padding: [72, 52, 72, 52],
    });
    const viewport = map.getViewport();
    const clearCursor = () => setCursor(null);
    viewport.addEventListener('pointerleave', clearCursor);

    return () => {
      unByKey(pointerMoveKey);
      unByKey(resolutionKey);
      viewport.removeEventListener('pointerleave', clearCursor);
      map.setTarget(undefined);
      mapRef.current = null;
    };
  }, [center, extent, projection.cellSize]);

  const changeZoom = (delta: number) => {
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }

    const currentZoom = view.getZoom() ?? 0;
    const nextZoom = Math.max(view.getMinZoom(), Math.min(view.getMaxZoom(), currentZoom + delta));

    if (prefersReducedMotion()) {
      view.setZoom(nextZoom);
    } else {
      view.animate({ zoom: nextZoom, duration: 120 });
    }
  };

  const resetView = () => {
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }

    view.fit(extent, {
      duration: prefersReducedMotion() ? 0 : 160,
      maxZoom: 4,
      padding: [72, 52, 72, 52],
    });
  };

  return (
    <main className="map-screen" aria-labelledby="map-title">
      <header className="window-titlebar map-titlebar">
        <button className="back-button" type="button" onClick={onBack}>
          <span aria-hidden="true">←</span>
          Версии
        </button>
        <div className="map-title-copy">
          <span className="titlebar-kicker">TES3:WORLD</span>
          <h1 id="map-title">{title}</h1>
        </div>
        <span className="titlebar-state">LOCAL</span>
      </header>

      <section className="map-workspace" aria-label={`Карта ${title}`}>
        <div
          ref={targetRef}
          className="map-canvas"
          tabIndex={0}
          aria-label="Интерактивная карта. Используйте мышь или клавиатуру для перемещения и масштаба."
        />

        <div className="map-tools" aria-label="Масштаб карты">
          <button type="button" onClick={() => changeZoom(1)} aria-label="Приблизить">
            +
          </button>
          <button type="button" onClick={resetView} aria-label="Показать весь мир">
            □
          </button>
          <button type="button" onClick={() => changeZoom(-1)} aria-label="Отдалить">
            −
          </button>
        </div>

        <aside className="origin-legend" aria-label="Обозначения сетки">
          <span className="origin-symbol" aria-hidden="true" />
          <span>Начало координат</span>
          <strong>0 : 0</strong>
        </aside>

        <p className="empty-map-note">
          <span>РАСТР НЕ ПОДКЛЮЧЁН</span>
          Координатный слой готов
        </p>
      </section>

      <footer className="map-statusbar" aria-label="Координаты курсора">
        <span>
          X&nbsp;<strong>{cursor ? formatWorldCoordinate(cursor.world[0]) : '—'}</strong>
        </span>
        <span>
          Y&nbsp;<strong>{cursor ? formatWorldCoordinate(cursor.world[1]) : '—'}</strong>
        </span>
        <span>
          CELL&nbsp;
          <strong>{cursor ? `${cursor.cell[0]}, ${cursor.cell[1]}` : '—, —'}</strong>
        </span>
        <span className="statusbar-zoom">
          ZOOM&nbsp;<strong>{zoom.toFixed(2)}</strong>
        </span>
      </footer>
    </main>
  );
}
