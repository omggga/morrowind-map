import { defineConfig } from '@playwright/test';

const port = 4174;
const baseURL = `http://127.0.0.1:${port}`;

const sharedUse = {
  baseURL,
  browserName: 'chromium' as const,
  headless: true,
  locale: 'en-US',
  timezoneId: 'UTC',
  colorScheme: 'dark' as const,
  reducedMotion: 'reduce' as const,
  serviceWorkers: 'block' as const,
  deviceScaleFactor: 1,
  trace: 'retain-on-failure' as const,
  screenshot: 'only-on-failure' as const,
  video: 'off' as const,
  launchOptions: {
    args: ['--force-color-profile=srgb'],
  },
};

function viewportProject(
  name: string,
  width: number,
  height: number,
  hasTouch: boolean,
) {
  return {
    name,
    testMatch: '**/*.visual.spec.ts',
    use: {
      ...sharedUse,
      viewport: { width, height },
      screen: { width, height },
      hasTouch,
      isMobile: hasTouch,
    },
  };
}

export default defineConfig({
  testDir: './tests/ui',
  outputDir: './test-results/ui',
  snapshotPathTemplate:
    '{testDir}/__screenshots__/{platform}/{projectName}/{testFileBaseName}/{arg}{ext}',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 45_000,
  expect: {
    timeout: 10_000,
    toHaveScreenshot: {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      threshold: 0.1,
      maxDiffPixels: 0,
    },
  },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report/ui', open: 'never' }],
  ],
  projects: [
    viewportProject(
      'desktop-1280x720',
      1280,
      720,
      false,
    ),
    viewportProject(
      'portrait-390x844',
      390,
      844,
      true,
    ),
    viewportProject(
      'portrait-320x568',
      320,
      568,
      true,
    ),
    viewportProject(
      'landscape-844x390',
      844,
      390,
      true,
    ),
    viewportProject(
      'landscape-667x375',
      667,
      375,
      true,
    ),
  ],
  webServer: {
    command:
      `pnpm --filter @morrowind-map/web exec vite --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
