# Local preview image for docs/website/ (the dev/test Compose stack's `docs`
# service — see tests/container/docker-compose.yml). This is a dev-only
# preview tool, not a production image `docker-build`'s CI job builds or
# pushes, so it's a much simpler two-stage build than frontend/Dockerfile's
# nginx-based one: `docusaurus serve` (Node, not nginx) serves the exact
# static production build GitHub Pages will, which `npm start`'s dev server
# would not.
FROM node:24-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:24-alpine

WORKDIR /app
COPY --from=build /app /app

EXPOSE 3001

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD wget -qO- http://localhost:3001/reqtrackmanager/ || exit 1

CMD ["npm", "run", "serve", "--", "--host", "0.0.0.0", "--port", "3001", "--no-open"]
