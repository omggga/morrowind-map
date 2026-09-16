import Feature from 'ol/Feature.js';
import type Map from 'ol/Map.js';
import Point from 'ol/geom/Point.js';
import LineString from 'ol/geom/LineString.js';
import VectorLayer from 'ol/layer/Vector.js';
import VectorSource from 'ol/source/Vector.js';
import CircleStyle from 'ol/style/Circle.js';
import RegularShape from 'ol/style/RegularShape.js';
import Fill from 'ol/style/Fill.js';
import Stroke from 'ol/style/Stroke.js';
import Style from 'ol/style/Style.js';
import Text from 'ol/style/Text.js';
import { TRANSPORT_MODES, type TransportCatalog, type TransportMode, type TransportRoute } from './types';

export interface TransportDisplay {
  readonly catalog: TransportCatalog;
  readonly modes: readonly TransportMode[];
  readonly selectedStopId: string | null;
  readonly regionId: string;
}

export function visibleTransportRoutes(display: TransportDisplay): TransportRoute[] {
  const stops = new globalThis.Map(display.catalog.stops.map((stop) => [stop.id, stop]));
  return display.catalog.routes.filter((route) => display.modes.includes(route.mode) &&
    (display.regionId === 'all' || stops.get(route.from)?.regionId === display.regionId ||
      stops.get(route.to)?.regionId === display.regionId));
}

export function transportStopAtPixel(map: Map, pixel: number[]): string | null {
  return map.forEachFeatureAtPixel(pixel, (feature) => feature.get('transportStopId') as string, {
    layerFilter: (layer) => layer.get('transportStops') === true,
    hitTolerance: window.matchMedia('(pointer: coarse)').matches ? 12 : 5,
  }) ?? null;
}

function localService(route: TransportRoute): boolean {
  return /gondola|palanquin/i.test(route.subtype);
}

export function createTransportLayers(map: Map) {
  const lines = new VectorSource<Feature<LineString>>();
  const stops = new VectorSource<Feature<Point>>();
  const lineLayer = new VectorLayer({ source: lines });
  const stopLayer = new VectorLayer({ source: stops, declutter: 'transport-stops' });
  lineLayer.setZIndex(5);
  stopLayer.setZIndex(12);
  stopLayer.set('transportStops', true);
  map.addLayer(lineLayer);
  map.addLayer(stopLayer);

  return {
    update(display: TransportDisplay) {
      lines.clear();
      stops.clear();
      const stopById = new globalThis.Map(display.catalog.stops.map((stop) => [stop.id, stop]));
      const routes = visibleTransportRoutes(display);
      const routeKey = (route: TransportRoute, reverse = false) =>
        `${route.mode}:${reverse ? route.to : route.from}:${reverse ? route.from : route.to}:${route.subtype}:${route.conditions.join('|')}`;
      const keys = new Set(routes.map((route) => routeKey(route)));
      const drawn = new Set<string>();
      const stopModes = new globalThis.Map<string, Set<TransportMode>>();
      const localStops = new Set<string>();
      const intercityStops = new Set<string>();
      for (const route of routes) {
        for (const id of [route.from, route.to]) {
          const modes = stopModes.get(id) ?? new Set<TransportMode>();
          modes.add(route.mode);
          stopModes.set(id, modes);
          (localService(route) ? localStops : intercityStops).add(id);
        }
        const from = stopById.get(route.from)!;
        const to = stopById.get(route.to)!;
        if (from.external || to.external) continue;
        const selected = display.selectedStopId === route.from;
        const reciprocal = keys.has(routeKey(route, true));
        if (display.selectedStopId === null && drawn.has(routeKey(route, true))) continue;
        if (display.selectedStopId !== null && !selected && route.to === display.selectedStopId && reciprocal) continue;
        drawn.add(routeKey(route));
        const geometry = new LineString([[...from.position], [...to.position]]);
        const feature = new Feature(geometry);
        const mode = TRANSPORT_MODES[route.mode];
        const dimmed = display.selectedStopId !== null && !selected;
        const opacity = dimmed ? '45' : 'FF';
        const styles = [
          new Style({ stroke: new Stroke({ color: `${mode.color}${opacity}`, width: selected ? 2 : 1.25, lineDash: mode.dash, lineCap: 'round' }) }),
        ];
        if (selected || !reciprocal) {
          styles.push(new Style({
            geometry: new Point(geometry.getCoordinateAt(0.62)),
            image: new RegularShape({
              points: 3, radius: selected ? 5 : 4,
              rotation: Math.PI / 2 - Math.atan2(to.position[1] - from.position[1], to.position[0] - from.position[0]),
              rotateWithView: true,
              fill: new Fill({ color: `${mode.color}${opacity}` }),
            }),
          }));
        }
        feature.setStyle(() => {
          const zoom = map.getView().getZoom() ?? 0;
          if (!selected && ((localService(route) && zoom < 6) || (route.mode === 'guild' && zoom < 2))) return undefined;
          return styles;
        });
        lines.addFeature(feature);
      }
      const neighbors = new Set(routes.filter((r) => r.from === display.selectedStopId).map((r) => r.to));
      for (const [id, modes] of stopModes) {
        const stop = stopById.get(id)!;
        if (stop.external) continue;
        const selected = id === display.selectedStopId;
        const highlighted = selected || neighbors.has(id);
        const color = modes.size === 1 ? TRANSPORT_MODES[[...modes][0]!].color : '#FFFFFF';
        const mode = [...modes][0]!;
        const radius = selected ? 8 : 5;
        const fill = new Fill({ color: selected ? color : '#15151B' });
        const stroke = new Stroke({ color, width: 2 });
        const image = mode === 'water' || modes.size > 1
          ? new CircleStyle({ radius, fill, stroke })
          : new RegularShape({ points: mode === 'guild' ? 3 : 4, radius: radius + 1, angle: mode === 'land' ? Math.PI / 4 : 0, fill, stroke });
        const feature = new Feature({ geometry: new Point([...stop.position]), transportStopId: id });
        feature.setStyle(() => {
          const zoom = map.getView().getZoom() ?? 0;
          if (!highlighted && localStops.has(id) && !intercityStops.has(id) && zoom < 6) return undefined;
          return new Style({
            image,
            text: highlighted || zoom >= 4 ? new Text({
              text: stop.name,
              font: `${highlighted ? '600' : '500'} 12px "Atkinson Hyperlegible Next Variable", sans-serif`,
              offsetY: 17, fill: new Fill({ color: '#FFFFFF' }),
              stroke: new Stroke({ color: '#101116', width: 4 }),
              declutterMode: selected ? 'none' : 'declutter',
            }) : undefined,
            zIndex: selected ? 3 : 1,
          });
        });
        stops.addFeature(feature);
      }
    },
    dispose() {
      map.removeLayer(lineLayer);
      map.removeLayer(stopLayer);
      lines.clear();
      stops.clear();
    },
  };
}
