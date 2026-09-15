# ReqTrackManager documentation website

Built with [Docusaurus](https://docusaurus.io/). See [../development.md#documentation-website](../development.md#documentation-website) for how to preview it locally (`npm start`, `npm run build`/`npm run serve`, or the `docs` service in the dev/test Docker Compose stack) and how dependency changes are synced.

Deployment is **not** `docusaurus deploy`/the `gh-pages` branch — `.github/workflows/ci.yml`'s `docs-deploy` job builds this site and publishes it to GitHub Pages via `actions/deploy-pages` whenever `main` is pushed, gated on GitHub Pages being enabled in the repo's Settings → Pages (source: "GitHub Actions").
