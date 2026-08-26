import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: [
      'apps/web/src/**/*.test.{ts,tsx}',
      'packages/contracts/src/**/*.test.ts',
    ],
    setupFiles: ['./apps/web/src/test/setup.ts'],
    restoreMocks: true,
  },
});
