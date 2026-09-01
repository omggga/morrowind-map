import type { ProgressStatus } from '@morrowind-map/contracts';

export const MARKER_KINDS = [
  'unvisited',
  'active',
  'visited',
  'custom',
] as const;

export type MarkerKind = ProgressStatus | 'custom';

export type MarkerShape = 'hollow-square';

interface MarkerSemantic {
  readonly color: string;
  readonly shape: MarkerShape;
  readonly path: string;
  readonly fillRule: 'evenodd';
}

const THIN_HOLLOW_SQUARE_PATH = 'M1 1H11V11H1ZM2 2V10H10V2Z';

export const MARKER_SEMANTICS: Readonly<Record<MarkerKind, MarkerSemantic>> = {
  unvisited: {
    color: '#f6e27d',
    shape: 'hollow-square',
    path: THIN_HOLLOW_SQUARE_PATH,
    fillRule: 'evenodd',
  },
  active: {
    color: '#e88bea',
    shape: 'hollow-square',
    path: THIN_HOLLOW_SQUARE_PATH,
    fillRule: 'evenodd',
  },
  visited: {
    color: '#e9a15b',
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
