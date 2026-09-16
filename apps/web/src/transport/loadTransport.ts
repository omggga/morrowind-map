import type { DatasetManifest } from '@morrowind-map/contracts';
import { TRANSPORT_MODE_ORDER, type TransportCatalog } from './types';

const catalogs = import.meta.glob<unknown>('./catalogs/*.json', { import: 'default' });
const files: Readonly<Record<string, string>> = {
  original: 'original',
  'tamriel-rebuilt': 'tr',
  'home-of-nords': 'sky',
  'project-cyrodiil': 'cyr',
};

export function hasTransport(dataset: DatasetManifest): boolean {
  return dataset.mapKey in files;
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function validateTransport(value: unknown, datasetId: string, snapshotId: string): TransportCatalog {
  if (!object(value) || value.schemaVersion !== 1 || value.datasetId !== datasetId ||
      value.snapshotId !== snapshotId || !Array.isArray(value.stops) || !Array.isArray(value.routes) ||
      !Array.isArray(value.sourcePlugins) || !object(value.review) ||
      !Array.isArray(value.review.excluded) || !Array.isArray(value.review.notes)) {
    throw new Error('Transport data does not match this map snapshot.');
  }
  const stopIds = new Set<string>();
  for (const stop of value.stops as unknown[]) {
    if (!object(stop) || typeof stop.id !== 'string' || !stop.id || stopIds.has(stop.id) ||
        typeof stop.name !== 'string' || typeof stop.regionId !== 'string' ||
        !Array.isArray(stop.position) || stop.position.length !== 2 ||
        !(stop.position as unknown[]).every((n) => typeof n === 'number' && Number.isFinite(n)) ||
        (stop.external !== undefined && typeof stop.external !== 'boolean') ||
        (stop.interior !== undefined && typeof stop.interior !== 'string')) {
      throw new Error('Invalid transport stop.');
    }
    stopIds.add(stop.id);
  }
  const routeIds = new Set<string>();
  for (const route of value.routes as unknown[]) {
    if (!object(route) || typeof route.id !== 'string' || !route.id || routeIds.has(route.id) ||
        typeof route.from !== 'string' || typeof route.to !== 'string' ||
        !stopIds.has(route.from) || !stopIds.has(route.to) || route.from === route.to ||
        !(TRANSPORT_MODE_ORDER as readonly unknown[]).includes(route.mode) ||
        typeof route.provider !== 'string' || typeof route.subtype !== 'string' ||
        typeof route.source !== 'string' || !Array.isArray(route.conditions) ||
        !(route.conditions as unknown[]).every((condition) => typeof condition === 'string')) {
      throw new Error('Invalid transport connection.');
    }
    routeIds.add(route.id);
  }
  return value as unknown as TransportCatalog;
}

export async function loadTransport(dataset: DatasetManifest): Promise<TransportCatalog> {
  const load = catalogs[`./catalogs/${files[dataset.mapKey]}.json`];
  if (!load) throw new Error('Transport is not available for this map.');
  return validateTransport(await load(), dataset.datasetId, dataset.snapshotId);
}
