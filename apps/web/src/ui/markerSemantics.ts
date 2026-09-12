import type { ProgressStatus } from '@morrowind-map/contracts';

export const MARKER_KINDS = [
  'unvisited',
  'active',
  'visited',
  'custom',
] as const;

export type MarkerKind = ProgressStatus | 'custom';

export type MarkerShape = 'hollow-square' | 'hollow-diamond' | 'hollow-circle' | 'hollow-triangle';

interface MarkerSemantic {
  readonly color: string;
  readonly shape: MarkerShape;
  readonly path: string;
  readonly fillRule: 'evenodd';
}

const THIN_HOLLOW_SQUARE_PATH = 'M1 1H11V11H1ZM2 2V10H10V2Z';

export function markerColor(kind: MarkerKind, colorblind = false): string {
  return markerAppearance(kind, colorblind).color;
}

export function markerAppearance(kind: MarkerKind, colorblind = false): MarkerSemantic {
  return (colorblind ? COLORBLIND_MARKER_SEMANTICS : MARKER_SEMANTICS)[kind];
}

export const MARKER_SEMANTICS: Readonly<Record<MarkerKind, MarkerSemantic>> = {
  unvisited: {
    color: '#f4f1e8',
    shape: 'hollow-square',
    path: THIN_HOLLOW_SQUARE_PATH,
    fillRule: 'evenodd',
  },
  active: {
    color: '#c59aff',
    shape: 'hollow-square',
    path: THIN_HOLLOW_SQUARE_PATH,
    fillRule: 'evenodd',
  },
  visited: {
    color: '#ff9d45',
    shape: 'hollow-square',
    path: THIN_HOLLOW_SQUARE_PATH,
    fillRule: 'evenodd',
  },
  custom: {
    color: '#78db78',
    shape: 'hollow-square',
    path: THIN_HOLLOW_SQUARE_PATH,
    fillRule: 'evenodd',
  },
};

// Colors from Masataka Okabe and Kei Ito's Color Universal Design palette,
// paired with distinct shapes so color is not the only way to identify a status.
// https://jfly.uni-koeln.de/color/index.html
const COLORBLIND_MARKER_SEMANTICS: Readonly<Record<MarkerKind, MarkerSemantic>> = {
  unvisited: MARKER_SEMANTICS.unvisited,
  active: {
    color: '#56b4e9',
    shape: 'hollow-diamond',
    path: 'M6 0L12 6 6 12 0 6ZM6 1.7 1.7 6 6 10.3 10.3 6Z',
    fillRule: 'evenodd',
  },
  visited: {
    color: '#e69f00',
    shape: 'hollow-circle',
    path: 'M6 1a5 5 0 1 0 0 10a5 5 0 1 0 0-10ZM6 2a4 4 0 1 1 0 8a4 4 0 1 1 0-8Z',
    fillRule: 'evenodd',
  },
  custom: {
    color: '#cc79a7',
    shape: 'hollow-triangle',
    path: 'M6 0L12 11H0ZM6 2.2 2 10h8Z',
    fillRule: 'evenodd',
  },
};
