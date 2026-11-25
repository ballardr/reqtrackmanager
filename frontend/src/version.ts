/**
 * This bundle's own build identity (semantic version, commit SHA and build timestamp), substituted into
 * `import.meta.env.VITE_*` at `npm run build` time from `frontend/Dockerfile`'s build ARGs. Placeholder values apply
 * to a local `npm run dev`/`vite build`, which sets none of these.
 */
export const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "dev";
export const GIT_SHA = import.meta.env.VITE_GIT_SHA ?? "unknown";
export const BUILD_DATE = import.meta.env.VITE_BUILD_DATE ?? "unknown";
