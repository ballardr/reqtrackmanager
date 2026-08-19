/**
 * This bundle's own build identity — semantic version, commit SHA, and
 * build timestamp, substituted into `import.meta.env.VITE_*` at `npm run
 * build` time (see `frontend/Dockerfile`'s build ARGs and the
 * `docker-build` CI job, which already computes a GitVersion SemVer and
 * tags images with it but previously had no way to surface that from
 * inside the running app). Falls back to placeholder values for a local
 * `npm run dev`/`vite build`, which sets none of these.
 */
export const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "dev";
export const GIT_SHA = import.meta.env.VITE_GIT_SHA ?? "unknown";
export const BUILD_DATE = import.meta.env.VITE_BUILD_DATE ?? "unknown";
