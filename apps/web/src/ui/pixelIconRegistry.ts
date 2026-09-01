export const PIXEL_ICON_NAMES = [
  'archive',
  'back',
  'open',
  'zoom-in',
  'zoom-out',
  'fit-map',
  'marker-add',
  'close',
] as const;

export type PixelIconName = (typeof PIXEL_ICON_NAMES)[number];
