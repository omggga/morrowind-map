import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/alegreya/wght.css';
import '@fontsource-variable/atkinson-hyperlegible-next/wght.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import displayFontUrl from '@fontsource-variable/alegreya/files/alegreya-latin-wght-normal.woff2?url';
import uiFontUrl from '@fontsource-variable/atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-normal.woff2?url';
import dataFontUrl from '@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2?url';
import 'ol/ol.css';
import { App } from './App';
import './i18n';
import './styles.css';

function preloadFont(href: string): void {
  const link = document.createElement('link');
  link.rel = 'preload';
  link.as = 'font';
  link.type = 'font/woff2';
  link.crossOrigin = 'anonymous';
  link.href = href;
  document.head.append(link);
}

preloadFont(displayFontUrl);
preloadFont(uiFontUrl);
preloadFont(dataFontUrl);

const rootElement = document.querySelector<HTMLDivElement>('#root');

if (!rootElement) {
  throw new Error('Root element #root was not found');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
