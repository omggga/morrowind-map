import Projection from 'ol/proj/Projection.js';
import { addProjection } from 'ol/proj.js';

export const TES3_PROJECTION_CODE = 'TES3:WORLD';
export const TES3_CELL_SIZE = 8192;

const tes3Projection = new Projection({
  code: TES3_PROJECTION_CODE,
  units: 'm',
});

addProjection(tes3Projection);

export type CellCoordinate = readonly [x: number, y: number];
export type WorldCoordinate = readonly [x: number, y: number];
export type WorldExtent = readonly [
  minX: number,
  minY: number,
  maxX: number,
  maxY: number,
];

export interface GridSegment {
  readonly axis: boolean;
  readonly coordinates: readonly [WorldCoordinate, WorldCoordinate];
}

export function configureTes3Projection(extent: WorldExtent): Projection {
  tes3Projection.setExtent([...extent]);
  return tes3Projection;
}

export function worldToCell(
  coordinate: WorldCoordinate,
  cellSize = TES3_CELL_SIZE,
): CellCoordinate {
  if (!Number.isFinite(cellSize) || cellSize <= 0) {
    throw new RangeError('TES3 cell size must be a positive finite number');
  }

  return [
    Math.floor(coordinate[0] / cellSize),
    Math.floor(coordinate[1] / cellSize),
  ];
}

export function buildCellGrid(
  extent: WorldExtent,
  cellSize = TES3_CELL_SIZE,
): GridSegment[] {
  if (!Number.isFinite(cellSize) || cellSize <= 0) {
    throw new RangeError('TES3 cell size must be a positive finite number');
  }

  const [minX, minY, maxX, maxY] = extent;
  const segments: GridSegment[] = [];

  for (let x = Math.ceil(minX / cellSize) * cellSize; x <= maxX; x += cellSize) {
    segments.push({
      axis: x === 0,
      coordinates: [
        [x, minY],
        [x, maxY],
      ],
    });
  }

  for (let y = Math.ceil(minY / cellSize) * cellSize; y <= maxY; y += cellSize) {
    segments.push({
      axis: y === 0,
      coordinates: [
        [minX, y],
        [maxX, y],
      ],
    });
  }

  return segments;
}

export function formatWorldCoordinate(value: number): string {
  return Math.round(value).toLocaleString('en-US');
}
