import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { DataTools } from './DataTools';

afterEach(cleanup);

describe('DataTools', () => {
  it('exposes portable JSON backup actions without the retired MIM importer', () => {
    render(
      <DataTools
        datasetId="poison-song-26.08"
        datasetSnapshots={{ 'poison-song-26.08': 'tr:poison-song-26.08:test' }}
        knownPlaceIds={new Set(['poison-song-26.08.place-test'])}
        locale="en"
      />,
    );

    expect(screen.getByRole('button', { name: 'Download JSON backup' })).toBeEnabled();
    expect(screen.getByLabelText('Import JSON backup')).toHaveAttribute('type', 'file');
    expect(screen.queryByText(/MIM/i)).not.toBeInTheDocument();
  });
});
