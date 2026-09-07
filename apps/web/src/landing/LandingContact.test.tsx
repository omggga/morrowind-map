import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { LandingContact } from './LandingContact';

afterEach(cleanup);

describe('LandingContact', () => {
  it('opens accessible contact links and closes back to its trigger', async () => {
    render(<LandingContact />);

    const trigger = screen.getByRole('button', { name: 'Contact information' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('complementary', { name: 'Contact information' }))
      .not.toBeInTheDocument();

    fireEvent.click(trigger);

    const panel = screen.getByRole('complementary', { name: 'Contact information' });
    await waitFor(() => expect(panel).toHaveFocus());
    expect(trigger).toHaveAttribute('aria-expanded', 'true');

    const email = screen.getByRole('link', { name: 'murashkin.alex@proton.me' });
    expect(email).toHaveAttribute('href', 'mailto:murashkin.alex@proton.me');
    expect(email).toHaveAttribute('target', '_blank');
    expect(email).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(email).toHaveAttribute('rel', expect.stringContaining('noreferrer'));

    const github = screen.getByRole('link', { name: 'github.com/omggga/morrowind-map' });
    expect(github).toHaveAttribute('href', 'https://github.com/omggga/morrowind-map/');
    expect(github).toHaveAttribute('target', '_blank');
    expect(github).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(github).toHaveAttribute('rel', expect.stringContaining('noreferrer'));

    fireEvent.keyDown(panel, { key: 'Escape' });

    await waitFor(() => expect(panel).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('button', { name: 'Close contact information' }));

    expect(screen.queryByRole('complementary', { name: 'Contact information' }))
      .not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
