export type TransportMode = 'land' | 'water' | 'guild';

export const TRANSPORT_MODE_ORDER: readonly TransportMode[] = ['land', 'water', 'guild'];

// Patterns and stop shapes remain distinct even when hues cannot be distinguished.
export const TRANSPORT_MODES = {
  land: { label: 'Land transport', color: '#D6FF63', dash: [], shape: 'square' },
  water: { label: 'Water transport', color: '#55D8FF', dash: [12, 7], shape: 'circle' },
  guild: { label: 'Guild guides', color: '#FF80C8', dash: [2, 7], shape: 'triangle' },
} satisfies Record<TransportMode, {
  label: string; color: string; dash: number[]; shape: 'square' | 'circle' | 'triangle';
}>;

export interface TransportStop {
  readonly id: string;
  readonly name: string;
  readonly position: readonly [number, number];
  readonly regionId: string;
  readonly interior?: string;
  readonly external?: boolean;
}

export interface TransportRoute {
  readonly id: string;
  readonly from: string;
  readonly to: string;
  readonly mode: TransportMode;
  readonly subtype: string;
  readonly provider: string;
  readonly conditions: readonly string[];
  readonly source: string;
}

export interface TransportCatalog {
  readonly schemaVersion: 1;
  readonly datasetId: string;
  readonly snapshotId: string;
  readonly sourcePlugins: readonly { readonly name: string; readonly sha256: string }[];
  readonly stops: readonly TransportStop[];
  readonly routes: readonly TransportRoute[];
  readonly review: { readonly excluded: readonly string[]; readonly notes: readonly string[] };
}

export function transportModes(values: readonly string[] | undefined): TransportMode[] {
  return TRANSPORT_MODE_ORDER.filter((mode) => values?.includes(mode));
}
