import { describe, expect, it } from 'vitest';
import { MARKER_KINDS, MARKER_SEMANTICS } from './markerSemantics';

describe('marker semantics', () => {
  it('assigns every marker kind a stable, non-color visual cue', () => {
    expect(MARKER_KINDS).toEqual(['unvisited', 'active', 'visited', 'custom']);
    expect(
      Object.fromEntries(
        MARKER_KINDS.map((kind) => [kind, MARKER_SEMANTICS[kind].shape]),
      ),
    ).toEqual({
      unvisited: 'hollow-square',
      active: 'hollow-diamond',
      visited: 'checked-square',
      custom: 'cross',
    });

    const geometries = MARKER_KINDS.map((kind) => {
      const semantic = MARKER_SEMANTICS[kind];
      return `${semantic.path}\0${'cutoutPath' in semantic ? semantic.cutoutPath : ''}`;
    });

    expect(new Set(geometries).size).toBe(MARKER_KINDS.length);
  });

  it('keeps the four MIM marker colors explicit and distinct', () => {
    const colors = MARKER_KINDS.map((kind) => MARKER_SEMANTICS[kind].color);

    expect(colors).toEqual(['#f6e27d', '#e88bea', '#e9a15b', '#78db78']);
    expect(new Set(colors).size).toBe(MARKER_KINDS.length);
  });
});
