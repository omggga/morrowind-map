import { createRef, type ComponentProps } from 'react';
import type { PlaceType, ProgressStatus } from '@morrowind-map/contracts';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '../i18n';
import { PlaceFilterControls } from './PlaceFilterControls';

const AVAILABLE_TYPES = ['settlement', 'cave', 'shop'] as const satisfies readonly PlaceType[];
const TYPE_COUNTS = new Map<PlaceType, number>([
  ['settlement', 6],
  ['cave', 4],
  ['shop', 1],
]);
const STATUS_COUNTS = new Map<ProgressStatus, number>([
  ['unvisited', 8],
  ['active', 2],
  ['visited', 1],
]);

function renderControls(
  overrides: Partial<ComponentProps<typeof PlaceFilterControls>> = {},
) {
  const props: ComponentProps<typeof PlaceFilterControls> = {
    availableTypes: AVAILABLE_TYPES,
    selectedTypes: new Set(),
    selectedStatuses: new Set(),
    typeCounts: TYPE_COUNTS,
    statusCounts: STATUS_COUNTS,
    activeAxisCount: 0,
    onToggleType: vi.fn(),
    onToggleStatus: vi.fn(),
    onClearTypes: vi.fn(),
    onClearStatuses: vi.fn(),
    onReset: vi.fn(),
    resetFocusRef: createRef<HTMLButtonElement>(),
    ...overrides,
  };

  return { ...render(<PlaceFilterControls {...props} />), props };
}

function openDrawer() {
  fireEvent.click(screen.getByText('Filters'));
}

afterEach(cleanup);
beforeAll(() => {
  i18n.addResourceBundle('en', 'translation', {
    map: {
      filters: 'Filters',
      filterSummaryOne: '1 active',
      filterSummaryMany: '{{active}} active',
      typeFilters: 'Place types',
      statusFilters: 'Progress status',
      resetFilters: 'Reset filters',
      allTypes: 'Any type',
      allStatuses: 'Any status',
    },
  }, true, true);
});
beforeEach(async () => {
  await i18n.changeLanguage('en');
});

describe('PlaceFilterControls', () => {
  it('renders only available place types with native filter groups and counts', () => {
    renderControls({ availableTypes: ['settlement', 'cave'] });

    expect(screen.getByText('Filters')).toBeInTheDocument();
    expect(screen.queryByText(/places/)).not.toBeInTheDocument();
    openDrawer();

    const typeGroup = screen.getByRole('group', { name: 'Place types' });
    expect(within(typeGroup).getByRole('button', { name: 'Any type 10' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(within(typeGroup).getByRole('button', { name: 'Settlement 6' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(within(typeGroup).getByRole('button', { name: 'Cave 4' })).toBeInTheDocument();
    expect(within(typeGroup).queryByRole('button', { name: /Shop/ })).not.toBeInTheDocument();

    const statusGroup = screen.getByRole('group', { name: 'Progress status' });
    expect(within(statusGroup).getByRole('button', { name: 'Any status 11' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(within(statusGroup).getByRole('button', { name: 'Unvisited 8' })).toBeInTheDocument();
    expect(within(statusGroup).getByRole('button', { name: 'Active 2' })).toBeInTheDocument();
    expect(within(statusGroup).getByRole('button', { name: 'Visited 1' })).toBeInTheDocument();
  });

  it('forwards type, status, and canonical Any-axis actions', () => {
    const onToggleType = vi.fn();
    const onToggleStatus = vi.fn();
    const onClearTypes = vi.fn();
    const onClearStatuses = vi.fn();
    renderControls({
      selectedTypes: new Set<PlaceType>(['settlement']),
      selectedStatuses: new Set<ProgressStatus>(['active', 'visited']),
      activeAxisCount: 2,
      onToggleType,
      onToggleStatus,
      onClearTypes,
      onClearStatuses,
    });
    openDrawer();

    expect(screen.getByRole('button', { name: 'Settlement 6' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Active 2' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cave 4' }));
    fireEvent.click(screen.getByRole('button', { name: 'Visited 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Any type 11' }));
    fireEvent.click(screen.getByRole('button', { name: 'Any status 11' }));

    expect(onToggleType).toHaveBeenCalledExactlyOnceWith('cave');
    expect(onToggleStatus).toHaveBeenCalledExactlyOnceWith('visited');
    expect(onClearTypes).toHaveBeenCalledOnce();
    expect(onClearStatuses).toHaveBeenCalledOnce();
  });

  it('disables canonical reset and exposes its button through the focus ref', () => {
    const resetFocusRef = createRef<HTMLButtonElement>();
    const onReset = vi.fn();
    const { rerender, props } = renderControls({ resetFocusRef, onReset });
    openDrawer();

    const reset = screen.getByRole('button', { name: 'Reset filters' });
    expect(reset).toBeDisabled();
    expect(resetFocusRef.current).toBe(reset);

    rerender(<PlaceFilterControls {...props} activeAxisCount={1} />);
    expect(reset).toBeEnabled();
    expect(screen.getByText('1 active')).toBeInTheDocument();
    rerender(<PlaceFilterControls {...props} activeAxisCount={2} />);
    expect(screen.getByText('2 active')).toBeInTheDocument();
    fireEvent.click(reset);
    expect(onReset).toHaveBeenCalledOnce();
  });
});
