import type { TilePyramid } from '@morrowind-map/contracts';
import ImageTile from 'ol/ImageTile.js';
import type Tile from 'ol/Tile.js';
import TileState from 'ol/TileState.js';
import { createTes3Resolutions } from './sparseTiles';

export const BASEMAP_MAX_OVERSCALE = 1.1;
export const BASEMAP_CONTRAST_FACTOR = 102 / 108;
export const BASEMAP_BRIGHTNESS_FACTOR = 1.1;

export function createOverscaledViewResolutions(
  pyramid: TilePyramid,
  scale = BASEMAP_MAX_OVERSCALE,
): number[] {
  const resolutions = createTes3Resolutions(pyramid);
  const finestResolution = resolutions.at(-1);

  if (finestResolution === undefined || !Number.isFinite(scale) || scale <= 1) {
    return resolutions;
  }

  return [...resolutions, finestResolution / scale];
}

export function makeRenderedPixelsOpaque(pixels: Uint8ClampedArray): void {
  for (let alphaIndex = 3; alphaIndex < pixels.length; alphaIndex += 4) {
    if (pixels[alphaIndex] !== 0) {
      pixels[alphaIndex] = 255;
    }
  }
}

export function loadOpaqueImageTile(tile: Tile, src: string): void {
  const imageTile = tile as ImageTile;
  const image = new Image();

  image.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d', { willReadFrequently: true });

    if (!context) {
      imageTile.setImage(image);
      return;
    }

    try {
      context.drawImage(image, 0, 0);
      const frame = context.getImageData(0, 0, canvas.width, canvas.height);
      makeRenderedPixelsOpaque(frame.data);
      context.putImageData(frame, 0, 0);
      imageTile.setImage(canvas);
    } catch {
      imageTile.setImage(image);
    }
  };
  image.onerror = () => imageTile.setState(TileState.ERROR);
  image.src = src;
}
