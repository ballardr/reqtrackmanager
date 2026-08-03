FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine

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
RUN chmod +x /docker/env-config-entrypoint.sh \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid
USER nginx

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD wget -qO- http://localhost:3000/health || exit 1

ENTRYPOINT ["/docker/env-config-entrypoint.sh"]
