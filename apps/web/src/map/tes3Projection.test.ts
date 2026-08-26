import { describe, expect, it } from 'vitest';
import {
  TES3_CELL_SIZE,
  TES3_PROJECTION_CODE,
  buildCellGrid,
  configureTes3Projection,
  worldToCell,
} from './tes3Projection';

describe('TES3 projection helpers', () => {
  it('registers a custom world projection with the supplied extent', () => {
    const projection = configureTes3Projection([-16_384, -8_192, 24_576, 16_384]);

    expect(projection.getCode()).toBe(TES3_PROJECTION_CODE);
    expect(projection.getExtent()).toEqual([-16_384, -8_192, 24_576, 16_384]);
  });

  it('uses floor semantics at positive and negative cell boundaries', () => {
    expect(worldToCell([0, 0])).toEqual([0, 0]);
    expect(worldToCell([TES3_CELL_SIZE, TES3_CELL_SIZE])).toEqual([1, 1]);
    expect(worldToCell([-0.01, -TES3_CELL_SIZE])).toEqual([-1, -1]);
    expect(worldToCell([-TES3_CELL_SIZE - 1, TES3_CELL_SIZE - 1])).toEqual([-2, 0]);
  });

  it('builds one line per cell boundary and marks both world axes', () => {
    const grid = buildCellGrid([-8_192, -8_192, 8_192, 8_192]);

    expect(grid).toHaveLength(6);
    expect(grid.filter(({ axis }) => axis)).toHaveLength(2);
    expect(grid).toContainEqual({
      axis: true,
      coordinates: [
        [0, -8_192],
        [0, 8_192],
      ],
    });
  });

  it('rejects an invalid cell size', () => {
    expect(() => worldToCell([0, 0], 0)).toThrow(RangeError);
    expect(() => buildCellGrid([0, 0, 1, 1], Number.NaN)).toThrow(RangeError);
  });
});
