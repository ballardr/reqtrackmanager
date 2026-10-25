FROM node:24-alpine AS build

# Build identity, baked into the bundle at build time (Vite substitutes
# `import.meta.env.VITE_*` when the build runs, unlike VITE_API_BASE_URL
# below, which is loosely-coupled runtime config injected by
# docker/env-config-entrypoint.sh at container *startup* instead — version
# is a property of the image itself, not the deployment target, so it
# belongs with the other build-time constants, not that runtime mechanism).
# Supplied via --build-arg by the docker-build CI job (same GitVersion
# SemVer/commit SHA used to tag this image); defaults keep a plain local
# `docker build` working with placeholder values instead of failing.
ARG APP_VERSION=dev
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ENV VITE_APP_VERSION=${APP_VERSION} \
    VITE_GIT_SHA=${GIT_SHA} \
    VITE_BUILD_DATE=${BUILD_DATE}

WORKDIR /app
# `npm ci`, not `npm install`: install exactly what the lockfile pins (and fail when it is out of step with
# package.json) so the image never builds from versions nobody reviewed.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.30-alpine

# Pull in Alpine security fixes released after the base image was built, so the
# CI vulnerability gate (HIGH/CRITICAL with a fix available) does not fail on a
# patched-but-not-yet-rebuilt base layer.
RUN apk upgrade --no-cache

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/env-config-entrypoint.sh /docker/env-config-entrypoint.sh

# Hardening review: ran as root with no reason to. The official nginx
# alpine image already ships an unprivileged `nginx` user (this listens on
# 3000, not 80, so there's no need to bind a privileged port as root
# first) — it just isn't used by default. `env-config-entrypoint.sh`
# writes env-config.js into the html directory at container *startup*
# (not build time), so that directory, plus nginx's own runtime
# dirs (cache/pid), need to be writable by that user, not just readable.
# The stock nginx.conf sets `user nginx;`, which nginx warns about on every start
# once the master process is itself unprivileged (USER nginx below), so it is removed.
RUN chmod +x /docker/env-config-entrypoint.sh \
    && sed -i '/^user /d' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid

# Tier C ("federated" / Module Federation) frontend modules — reserved,
# normally-empty directory `nginx.conf`'s `/external-modules/` location
# serves from. Created here (not left for an operator's bind-mount to
# create implicitly) so the location always resolves even for a deployment
# that never mounts anything into it — a missing directory would otherwise
# make every request under this path fail at the filesystem level rather
# than nginx's own clean, intended 404. An operator bind-mounting their own
# built remote(s) here (see docs/deployment.md) mounts *over* this empty
# directory, not instead of creating it.
RUN mkdir -p /usr/share/nginx/external-modules \
    && chown nginx:nginx /usr/share/nginx/external-modules
USER nginx

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=10 \
    CMD wget -qO- http://127.0.0.1:3000/health || exit 1

ENTRYPOINT ["/docker/env-config-entrypoint.sh"]
