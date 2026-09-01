import type { ProgressStatus } from '@morrowind-map/contracts';

export const MARKER_KINDS = [
  'unvisited',
  'active',
  'visited',
  'custom',
] as const;

export type MarkerKind = ProgressStatus | 'custom';

export type MarkerShape =
  | 'hollow-square'
  | 'hollow-diamond'
  | 'checked-square'
  | 'cross';

interface MarkerSemantic {
  readonly color: string;
  readonly shape: MarkerShape;
  readonly path: string;
  readonly cutoutPath?: string;
  readonly fillRule?: 'evenodd';
}

export const MARKER_SEMANTICS: Readonly<Record<MarkerKind, MarkerSemantic>> = {
  unvisited: {
    color: '#f6e27d',
    shape: 'hollow-square',
    path: 'M1 1H11V11H1ZM3 3V9H9V3Z',
    fillRule: 'evenodd',
  },
  active: {
    color: '#e88bea',
    shape: 'hollow-diamond',
    path: 'M6 0L12 6L6 12L0 6ZM6 3L3 6L6 9L9 6Z',
    fillRule: 'evenodd',
  },
  visited: {
    color: '#e9a15b',
    shape: 'checked-square',
    path: 'M1 1H11V11H1Z',
    cutoutPath: 'M3 6H5V8H7V6H9V4H11V8H9V10H5V8H3Z',
  },
  custom: {
    color: '#78db78',
    shape: 'cross',
    path: 'M4 0H8V4H12V8H8V12H4V8H0V4H4Z',
  },
};
