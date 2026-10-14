/// <reference types="vite/client" />

/**
 * Injected by `vite.config.ts` (`define`) from `chemml_version.py` so the UI
 * never carries its own copy of the platform version (spec task P0-04).
 */
declare const __CHEMML_VERSION__: string;
