/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  /** Build identity, substituted at `npm run build` time — see frontend/Dockerfile. */
  readonly VITE_APP_VERSION?: string;
  readonly VITE_GIT_SHA?: string;
  readonly VITE_BUILD_DATE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  /** Runtime config injected by docker/env-config-entrypoint.sh at container startup. */
  __ENV__?: { VITE_API_BASE_URL?: string };
}
