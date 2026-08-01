/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  /** Runtime config injected by docker/env-config-entrypoint.sh at container startup. */
  __ENV__?: { VITE_API_BASE_URL?: string };
}
