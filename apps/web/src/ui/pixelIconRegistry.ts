export const PIXEL_ICON_NAMES = [
  'back',
  'import',
  'export',
  'close',
  'mail',
  'github',
  'link',
] as const;

export type PixelIconName = (typeof PIXEL_ICON_NAMES)[number];
