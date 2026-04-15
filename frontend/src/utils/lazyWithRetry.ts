import React from 'react';

function isChunkLoadError(error: unknown): boolean {
  const message =
    error instanceof Error ? error.message : typeof error === 'string' ? error : '';

  return /Failed to fetch dynamically imported module/i.test(message) ||
    /Importing a module script failed/i.test(message) ||
    /ChunkLoadError/i.test(message);
}

export function lazyWithRetry<T extends React.ComponentType<unknown>>(
  importer: () => Promise<{ default: T }>,
  key: string,
) {
  return React.lazy(async () => {
    const storageKey = `lazy-retry:${key}`;

    try {
      const module = await importer();
      if (typeof window !== 'undefined') {
        window.sessionStorage.removeItem(storageKey);
      }
      return module;
    } catch (error) {
      if (
        typeof window !== 'undefined' &&
        isChunkLoadError(error) &&
        !window.sessionStorage.getItem(storageKey)
      ) {
        window.sessionStorage.setItem(storageKey, '1');
        window.location.reload();
        return new Promise<never>(() => {});
      }

      if (typeof window !== 'undefined') {
        window.sessionStorage.removeItem(storageKey);
      }
      throw error;
    }
  });
}
