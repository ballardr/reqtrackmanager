# Documentation Website (Docusaurus + GitHub Pages) — Implementation Plan

This document is the persistent, session-resumable implementation plan for building a public documentation website for ReqTrackManager with Docusaurus, deployed to GitHub Pages as a job in the existing GitHub Actions pipeline (`.github/workflows/ci.yml`). It follows the same phased, resumable structure as `docs/plans/compliance-module-plan.md` and `docs/plans/platform-review-2026-09-plan.md` — read cold, by a session with no memory of this conversation.

**If you are starting a session against this plan, read "Status / Resume Here" below first.**

---

## Status / Resume Here

**Last updated:** 2026-09-15 (Phase 8 complete).

**Overall progress:** 8 / 10 phases complete.

| # | Phase | Status |
|---|-------|--------|
| 1 | Docs folder tidy (`docs/plans/`) + Docusaurus scaffold (`docs/website/`) + local Docker Compose preview service + CI deploy wiring | [x] Complete |
| 2 | Introduction + Concepts section | [x] Complete |
| 3 | Installation & Deployment chapter | [x] Complete |
| 4 | Core Features section | [x] Complete |
| 5 | Workflows section | [x] Complete |
| 6 | Modules section (own top-level nav) | [x] Complete |
| 7 | API & Integrations section (REST API, SSO, SCIM, AI assistants/MCP) | [x] Complete |
| 8 | Enterprise & Security section | [x] Complete |
| 9 | Reference + Contributing section | [ ] Not started |
| 10 | Polish, cross-linking, search, broken-link gate, final QA — including a visual QA pass | [ ] Not started |

**Instructions for whoever picks up the next phase:** implement exactly one phase, leave the repo passing its tests and in a clean state, add a `docs/decisions.md` entry (tagged **Decided by: User** or **Decided by: Agent** for every design call per `CLAUDE.md`'s documentation-governance rule), then come back to this file and tick its checkbox and update "Last updated." Do not cascade into the next phase automatically. Content phases (2–9) should each end with `npm run build` in `docs/website/` passing with zero broken-link errors (`onBrokenLinks: 'throw'`, set in Phase 1) before being marked done — a content phase that leaves dangling links for a later phase to fix is not complete.

---

## Origin

The user asked for a full documentation website — one page per ReqTrackManager screen and workflow, organised into concepts / core features / workflows, plus installation/deployment as its own chapter — built with Docusaurus (**Decided by: User**, explicit preference) and deployed to GitHub Pages via the existing GitHub Actions pipeline (**Decided by: User**). They also asked for modules to have their own top-level pages rather than being buried, and offered to let the agent tidy `docs/` at the same time (suggesting a `docs/plans/` directory) and to choose the website's location/name from `docs/<subdir>` or a root directory, with candidate names `pages`, `www`, `website`, or another name of the agent's choosing. They asked for this to be done "as a planned session" with a plan document in the style of `docs/plans/compliance-module-plan.md` / the platform-review and React-19 plans.

Before any phase started, the user reviewed the first draft of this plan and asked for four additions, folded directly into the sections below rather than tracked as a separate revision (nothing had been implemented yet): (1) dedicated API-use/integration pages — the original draft only had a thin "point at the live OpenAPI schema" reference page, with no guide to actually calling the REST API; (2) every page should carry pictures, diagrams, or screenshots, made to look good, with an explicit prompt to reconsider Mermaid's default styling or use another tool if that serves the "look nice" goal better; (3) a discussion of the project's own use cases, not just its feature list; (4) the local Docker Compose dev stack should build and serve the docs site itself, so it can be reviewed locally without a real GitHub Pages deploy.

---

## Open decisions made while scoping this plan

- **Site location: `docs/website/`, Docusaurus's own content folder at `docs/website/docs/`.** — **Decided by: Agent**, within the user's explicit "docs subdirectory or root directory, name up to you" latitude. Reasoning: this repo already treats `docs/` as the home for everything documentation-related (product docs, SOC 2 policies, UX audit, plans); a root-level `website/` or `pages/` directory would sit awkwardly next to `backend/`, `frontend/`, `mcp-server/` as if it were a fourth deployable service, which it isn't. `website` (not `pages`, which collides in meaning with GitHub Pages itself and with this app's own "pages" terminology for `frontend/src/pages/`, or `www`, which implies a production domain this project doesn't have) reads unambiguously as "the Docusaurus project." If the user prefers a different name or root-level placement, this is a one-time `git mv` plus a `base`/paths update in `docusaurus.config.ts` and the CI job's `working-directory` — flag this open if the user pushes back after seeing Phase 1.
- **Docs folder tidy scope: only files that are themselves session plans / unbuilt proposals move to `docs/plans/`.** — **Decided by: Agent**, the specific scope under the user's general "feel free to tidy, maybe a plans directory" latitude (**Decided by: User** for the concept). Moving: `compliance-module-plan.md`, `platform-review-2026-09-plan.md`, `react19-eslint10-upgrade-plan.md`, `future-modules-2026-09-overview.md` (an unbuilt module-proposal document, not current-state documentation), `Compliance_Module_Requirements.md` (the requirements input the compliance plan was built from), and this plan itself (authored directly at `docs/plans/docs-website-plan.md`). **Not** moving: `requirements.md` (explicitly authoritative, CLAUDE.md forbids agent edits to it, and it isn't a "plan" in this sense), `decisions.md`, `solution-architecture.md`, `modules.md`, `compliance-module.md` (current-state reference for the shipped module, distinct from the historical build-log `compliance-module-plan.md`), `deployment.md`, `development.md`, `user-guide.md`, `e2e-workflows.md`, `mcp-server.md`, `enterprise-integration.md`, `ux-style-guide.md`, `ux-audit-2026-08.md` (an audit *report*, not a plan, and `CLAUDE.md`'s UX-adherence section cites it as load-bearing for roadmap-checking; moving it would mean editing that CLAUDE.md section too, out of proportion to the tidy the user asked for), or `soc2/`. `docs/figures/` and `docs/screenshots/` are asset directories, not documents — left in place.
- **`future-modules-2026-09-overview.md`'s content (10 proposed, unbuilt modules) is out of scope for the public site.** — **Decided by: Agent.** The Modules section (Phase 6) documents the module *system* and the one module that's actually shipped (Compliance); a "Roadmap" note may link to the internal plan doc for anyone who wants it, but the site should not carry full pages describing features that don't exist yet, matching this repo's own "document what's real" character (see `README.md`'s "Known limitations" section, and `docs/soc2/`'s stated preference for candid gaps over aspirational claims).
- **Workflows section groups the 26 `docs/e2e-workflows.md` scenarios and 34 `frontend/src/pages/*.tsx` screens into ~13 task-oriented pages, not 26+34 separate stub files.** — **Decided by: Agent.** The user's instruction was "each and every page and workflow should have a page" — read as *every page and workflow must be documented and reachable from its own place in the site*, not literally one file per source artifact; a 60-entry flat list would itself violate `docs/ux-style-guide.md`'s own anti-fragmentation principle (naming things by what a reader is trying to do, not by internal source-code boundaries). The **Content Inventory** table below is the acceptance checklist: every frontend page and every e2e-workflow scenario is mapped to exactly one site page, so coverage is auditable phase-by-phase. If the user wants strict 1:1 pages instead, say so before Phase 5 and this table is a ready-made file list to split apart.
- **Search: `@easyops-cn/docusaurus-search-local`, not Algolia DocSearch.** — **Decided by: Agent.** Algolia DocSearch needs an external account/API key and indexes a *publicly deployed* site — friction for a self-hostable, offline-buildable product whose own `README.md` already emphasizes no baked-in external dependencies. The local-search plugin builds a search index at `npm run build` time with no external service or key.
- **New CI job(s) in the existing `ci.yml`, not a separate `docs.yml` workflow.** — **Decided by: Agent**, matching the user's "as part of the GitHub action pipeline" wording and this repo's existing single-workflow-file convention (`ci.yml`'s own header comment enumerates all jobs in one place). Two jobs: `docs` (build + link-check, every push and PR — fast, no Docker) and `docs-deploy` (needs: `[docs]`, `if: github.ref == 'refs/heads/main' && github.event_name == 'push'`, uses `actions/upload-pages-artifact` + `actions/deploy-pages`), mirroring the existing `docker-build` job's push-only-on-main gating.
- **GitHub Pages must be enabled in the repository's own Settings → Pages (source: "GitHub Actions") before `docs-deploy` can succeed — this is a repo-admin action outside git/CI that the agent cannot perform.** Flag this explicitly to the user once Phase 1 lands; until it's enabled, `docs-deploy` will fail with a clear "Pages not enabled" error, which is expected and not a bug in the job itself.
- **A dedicated "API & Integrations" section (Phase 7), not just a pointer page.** — **Decided by: User** (explicit follow-up ask). The original draft treated the REST API as a one-line pointer at the live Swagger UI; that leaves no actual guide for someone scripting against the API or wiring up SSO/SCIM/MCP. SSO/SCIM/MCP content that was originally split across "Enterprise & Security" and "AI Assistant Integration" moves into this one section instead — all three are ways something *external* talks to a ReqTrackManager instance, which is a more useful grouping for a reader than "security" vs. "AI" as the dividing line. "Enterprise & Security" (renumbered Phase 8) keeps the *posture* content (encryption/secrets, SOC 2) that isn't itself an integration a reader would set up.
- **Diagrams: themed Mermaid as the default, hand-authored static SVG for a handful of showcase diagrams — not a wholesale switch away from Mermaid.** — **Decided by: Agent**, in response to the user's "make these look nice... may need a style guide or another library" prompt. Reasoning: this repo already has a real precedent for both approaches — `docs/solution-architecture.md`/`docs/modules.md` use plain, unthemed Mermaid (functional but visually flat, Docusaurus's default palette), while `docs/figures/architecture/*.svg` (`Requirement_Capture.svg`, `Requirements_structure.svg`, `project_structure.svg`) are polished, hand-styled diagrams already used in `docs/solution-architecture.md` today. Switching every diagram to a design tool would lose Mermaid's real advantage for this content — diagrams-as-text, diffable in PRs, cheap to keep in sync with a changing data model — and CLAUDE.md already establishes a repo-wide Mermaid-by-default preference for documentation. So: (a) enable `@docusaurus/theme-mermaid` with a **custom theme** (`themeVariables` in `docusaurus.config.ts`, derived from `logo.svg`'s own palette, applied consistently for both light and dark mode) so every Mermaid diagram on the site shares one deliberate look instead of the library default — this is the "style guide" the user suggested, expressed as one shared config rather than a prose document; (b) for the small number of genuinely illustrative/showcase diagrams (the Introduction page's product-overview graphic, the Architecture overview page's top-level system diagram), reuse the existing `docs/figures/architecture/*.svg` assets directly rather than re-deriving them as Mermaid, and author any *new* showcase-quality diagram the same hand-styled-SVG way rather than fighting Mermaid's layout engine for something it isn't good at. Every other diagram (flowcharts, sequence diagrams, ER diagrams embedded inline in a Concepts/Core-Features/Reference page) stays Mermaid, themed. Revisit with the user after Phase 1's theme lands if the themed-Mermaid result still doesn't look "nice" enough.
- **Screenshots: a documented, repeatable standard, not ad hoc captures per page.** — **Decided by: Agent.** Fixed browser viewport (1440×900, matching this repo's existing `docs/screenshots/*.png` — confirmed in Phase 1 via `file docs/screenshots/*.png`: all nine are 1440 wide; `change-request-detail.png` is 1234 tall, the rest 900, i.e. same 1440-wide viewport, taller page content on that one screen rather than a different capture setup), always captured against the seeded demo dataset (`backend/scripts/seed_demo_data.py`, per `docs/development.md#demo-data` — the same dataset `README.md`'s own screenshots use, so site and README stay visually consistent), stored under `docs/website/static/img/screenshots/`, reusing the existing `docs/screenshots/*.png` files by copy (not re-capture) wherever a page's subject already has one. Every new screenshot needs real alt text (accessibility, and this repo's UX style guide already holds the app itself to that bar) and a short one-line caption, not surrounding "what this shows/why it matters" prose — matching `CLAUDE.md`'s own screenshot-captioning rule for `README.md`, extended here to the site.
- **Every Concepts, Core Features, Workflows, and Modules page needs at least one screenshot or diagram — this is a phase-completion bar, not a nice-to-have.** — **Decided by: Agent**, operationalizing the user's "there should be pictures, diagrams and screenshots" instruction into something each content phase's verification step can actually check off.
- **Phase 6 gets a dedicated third-party/federated module page, split out from a single "Building your own module" page.** — **Decided by: User** (explicit follow-up ask: add a phase, or fold into an existing one, on how to develop/integrate third-party modules). The original Phase 6 draft bundled Tier A (in-repo, compiled-in — how the shipped Compliance module itself is built) together with Tier B/Tier C (remote/federated — a genuinely external module the site operator didn't write) under one "Building your own module" page adapted wholesale from `docs/modules.md`'s remaining sections. A reader who actually wants to build or integrate a third-party module needs `docs/modules.md`'s Tier C module-author guide and Tier C operator guide as their own page, not buried inside a page whose primary worked example (the `ModuleDefinition` contract, the build checklist) is written for an in-repo/Tier A contributor. Splitting into two pages — *Building your own module* (Tier A contract, module-contributed RBAC, module-contributed MCP tools, the build checklist) and *Third-party and federated modules* (Tier B/C: what changes for a module you don't compile in, the module-author guide, the operator/security-review guide) — also lets the new page cross-link cleanly with Phase 3's already-shipped *Scaling and adding modules* page (`docs/website/docs/installation-deployment/scaling-and-modules.md`), which already documents the operator-side mounting/`EXTRA_MODULES_PATH`/Tier C bundle-mounting steps and already links forward to `../modules/index.md` in anticipation of this content. That link currently resolves to the Phase 6 placeholder page and must be repointed at the new page's real slug as part of Phase 6, not left pointing at the Modules section's *Overview*.
- **The docs site gets its own service in `tests/container/docker-compose.yml` (the local dev/eval stack), not the root production `docker-compose.yml`.** — **Decided by: User** for the core ask (build and serve the docs site locally for review); **Decided by: Agent** for which of the two Compose stacks it belongs in. This repo treats the two stacks as deliberately separate (`tests/container/`'s own header comment: "NOT the production stack"; `CLAUDE.md`/decisions.md repeatedly warn against confusing them) — a docs *preview* tool for people working on this repo belongs with the dev/eval stack that already exists for exactly that purpose, alongside `frontend`/`backend`/`mcp-server`. The production stack's whole point is modeling a real deployment behind real secrets; the real, public docs site is what GitHub Pages serves once Phase 1's `docs-deploy` job runs, so a second static-docs container in the production stack would just be redundant surface area with no deployment served by it. If the user wants a docs preview in the production stack too (e.g. to self-host the docs alongside a private deployment instead of relying on GitHub Pages), say so and this is a small addition to Phase 1.

---

## Content inventory (coverage checklist for Phases 2–9)

Every `frontend/src/pages/*.tsx` screen and every `docs/e2e-workflows.md` scenario, mapped to its destination site page. Compliance-module frontend surfaces (`frontend/src/modules/compliance/`) are covered separately in Phase 6, not here.

| Source (page and/or e2e-workflows.md #) | Destination site page (Phase) |
|---|---|
| `LoginPage`, `OrgLoginPage`, `OidcCompletePage`; e2e #7 SSO login | Workflows → *Signing in* (Phase 5) |
| `SignupPage` | Workflows → *Signing in* (self-signup subsection) (Phase 5) |
| `PreferencesPage`; e2e #22 | Workflows → *Preferences and help* (Phase 5) |
| `HelpPage`; e2e #22 | Workflows → *Preferences and help* (Phase 5) |
| `OrgListPage`; e2e #2, #3 | Workflows → *Organisations and projects* (Phase 5) |
| `ProjectListPage`, `FavouritesPage`; e2e #4, #25 | Workflows → *Organisations and projects* (Phase 5) |
| `ProjectOverviewPage` | Workflows → *Organisations and projects* (Phase 5) |
| `RequirementsPage`, `RequirementDetailPage`; e2e #6, #21, #23 | Workflows → *Authoring and reviewing requirements* (Phase 5) |
| `ChangeRequestsPage`, `ChangeRequestDetailPage`; e2e #5, #9 | Workflows → *Change requests* (Phase 5) |
| `MyReviewsDuePage`, `ProjectReviewsDuePage`; e2e #8, #10 | Workflows → *Stages, baselining, and reviews* (Phase 5) |
| `ProjectActionsPage`, `ActionDetailPage` | Workflows → *Requirement actions* (Phase 5) |
| `ProjectFilesPage`, `ProjectHistoryPage`; e2e #18, #19, #26 | Workflows → *Files, comments, and history* (Phase 5) |
| `ReportsPage`; e2e #13, #20 | Workflows → *Reporting and CSV import/export* (Phase 5) |
| `NotificationsPage`; e2e #17 | Workflows → *Notifications* (Phase 5) |
| `OrgAdminPage`, `OrgOverviewPage`; e2e #12 (org half), #14, #24 (org half) | Workflows → *Administering an organisation* (Phase 5) |
| `ProjectAdminPage`; e2e #11, #12 (project half), #24 (project half) | Workflows → *Administering a project* (Phase 5) |
| `ServerManagementPage`, `ServerOrganisationsPage`; e2e #1, #16, #24 (server half) | Workflows → *Server administration* (Phase 5) |
| e2e #15 (2FA enrollment) | Workflows → *Two-factor authentication* (Phase 5) |
| e2e #6 "attempts to bypass the lifecycle" | folded into *Authoring and reviewing requirements* as a "what's enforced, and why" callout (Phase 5), also referenced from Concepts → *Requirement lifecycle and locking* (Phase 2) |

**Verification for Phase 5:** every row above has a corresponding `## `/`### ` anchor in its destination page before Phase 5 is marked done; every `frontend/src/pages/*.tsx` file and every `docs/e2e-workflows.md` `### N.` heading appears in this table (re-run `find frontend/src/pages -name '*Page.tsx'` and `grep '^### [0-9]' docs/e2e-workflows.md` against the table if either source file has changed since this plan was written).

---

## Site structure (sidebar, top to bottom)

1. **Introduction** (subpages: *Overview*, *Use cases*) — what ReqTrackManager is, who it's for, key screenshots, and now a dedicated look at who actually uses a tool like this and why, per the user's follow-up ask (Phase 2).
2. **Installation & Deployment** (one sidebar category / chapter, several subpages) — per the user's instruction, this is the one section allowed to be a multi-page chapter rather than a single page, sitting at the same tree depth as the sections below.
3. **Concepts** (subpages)
4. **Core Features** (subpages)
5. **Workflows** (subpages, per the Content Inventory above)
6. **Modules** (subpages — its own top-level entry, not nested under Core Features; includes a dedicated page on developing/integrating third-party (Tier B/C) modules, distinct from the in-repo Tier A build guide)
7. **API & Integrations** (subpages) — REST API usage, authentication, SSO/OIDC, SCIM, AI-assistant/MCP access; everything that's a way for something *outside* the web UI to talk to ReqTrackManager, per the user's follow-up ask.
8. **Enterprise & Security** (subpages) — posture content: encryption/secrets, SOC 2.
9. **Reference** (subpages) — architecture, glossary, contributing.

---

## Phase 1 — Docs folder tidy + Docusaurus scaffold + local preview service + CI deploy wiring

### 1a. Tidy `docs/`

- Create `docs/plans/` (already created as part of writing this plan).
- `git mv` into `docs/plans/`: `compliance-module-plan.md`, `platform-review-2026-09-plan.md`, `react19-eslint10-upgrade-plan.md`, `future-modules-2026-09-overview.md`, `Compliance_Module_Requirements.md`.
- Fix every reference repo-wide. Known reference counts as of this plan (re-`grep` before relying on these — they will have shifted):
  - `compliance-module-plan.md`: `CLAUDE.md` (3), `docs/modules.md` (8), `docs/mcp-server.md` (2), `docs/compliance-module.md` (1), `docs/development.md` (1), `docs/soc2/trust-services-criteria-mapping.md` (1), `docs/ux-style-guide.md` (5), `docs/solution-architecture.md` (16), `docs/soc2/policies/vendor-and-subprocessor-management-policy.md` (2), `docs/soc2/policies/access-control-policy.md` (5), `docs/decisions.md` (106), plus the other three plan docs referencing each other.
  - `platform-review-2026-09-plan.md`: `docs/decisions.md` (17), the two other plan docs.
  - `react19-eslint10-upgrade-plan.md`: `docs/decisions.md` (14).
  - `future-modules-2026-09-overview.md`: `docs/ux-style-guide.md` (1), `docs/decisions.md` (1).
  - `Compliance_Module_Requirements.md`: `docs/compliance-module.md` (3), `docs/decisions.md` (4).
  - Rule: a reference written as `docs/<file>.md` (repo-root-relative — `README.md`, `CLAUDE.md`) becomes `docs/plans/<file>.md`; a reference written bare or as `<file>.md` from inside another `docs/*.md` file becomes `plans/<file>.md`; a reference from one moved file to another moved file (all now siblings in `docs/plans/`) stays bare.
  - Do this with a scripted pass (e.g. `grep -rl` per filename, then a scoped `sed` per reference style above), then verify with a second `grep -rn` for each of the five bare filenames repo-wide (excluding `.git`, `node_modules`, `graphify-out`) confirming every remaining hit is already correctly prefixed.
- Update `README.md` if it links any of the five moved files directly (spot-check; it currently does not appear to).
- Do **not** touch `docs/requirements.md`, `docs/decisions.md`'s own content (only its links to the moved files), or anything under `docs/soc2/` beyond fixing the link paths identified above.

### 1b. Scaffold Docusaurus at `docs/website/`

- `npx create-docusaurus@latest docs/website classic --typescript` (TypeScript, matching `frontend/`'s convention) run under Node 24 (add `docs/website/.nvmrc` containing `24`, matching `frontend/.nvmrc`/`mcp-server`'s own pin per `CLAUDE.md`'s Node-lockstep rule — extend that rule's scope to include this new project).
- `docusaurus.config.ts`: site title "ReqTrackManager", tagline from `README.md`'s own one-line description, `url`/`baseUrl` set for GitHub Pages project-site hosting (`https://<org>.github.io/reqtrackmanager/`, `baseUrl: '/reqtrackmanager/'` — confirm the actual GitHub org/repo slug from `git remote -v` rather than assuming), `organizationName`/`projectName` matching the real GitHub repo, `onBrokenLinks: 'throw'`, `onBrokenAnchors: 'throw'` (fail the build, and therefore CI, on any dangling internal link — this is the mechanism that makes "every page exists and is linked" actually enforced rather than aspirational).
- Remove the default `blog/` plugin and its nav entry — this is documentation, not a blog. Remove default tutorial/placeholder docs content.
- Set up the sidebar categories from "Site structure" above in `sidebars.ts`, each initially containing one placeholder page (e.g. "Coming in Phase N") so the site builds and navigates correctly before any real content exists — this makes Phase 1 independently verifiable without depending on content phases.
- Add `@easyops-cn/docusaurus-search-local` per the decision above, configured for `hashed: true` (stable URLs) and English only (no i18n in this plan — matches `frontend/`'s own single-locale-for-now state per `docs/decisions.md`'s i18n note).
- Repo logo: reuse `logo.svg` (repo root) as the site favicon/navbar logo rather than authoring a new one.
- Visual style setup (per "Open decisions" above): add `@docusaurus/theme-mermaid` (`markdown.mermaid: true` in `docusaurus.config.ts`), define a custom `themeConfig.mermaid.theme`/`themeVariables` derived from `logo.svg`'s palette for both light and dark mode, and confirm at least one ported Mermaid diagram (borrow one from `docs/solution-architecture.md` as a smoke test) renders with the custom theme in `npm run serve`. Measure `docs/screenshots/*.png`'s actual pixel dimensions (`file docs/screenshots/*.png` or equivalent) and record the real figure in this plan (replacing the assumed "1440×900" above) so later phases capture new screenshots at a matching size. Create `docs/website/static/img/screenshots/` and copy (not move — the originals stay put for `README.md`'s own use) the existing `docs/screenshots/*.png` into it.
- `docs/website/package.json`: scripts `start`, `build`, `serve`, `typecheck` (Docusaurus's default `tsc --noEmit`), and a `docs/website/scripts/sync-lockfile.sh` mirroring `frontend/scripts/sync-lockfile.sh` (Node-major guard, clean `npm ci` reinstall) — reuse rather than reinvent, per this repo's own component-reuse principle. Do **not** wire `docs/website/`'s lockfile into the existing `.githooks/pre-commit` hook's `frontend/(package.json|package-lock.json)` path filter as part of this phase — extend that filter to also match `docs/website/` in the same change, since the hook exists specifically to catch this class of lockfile drift and a second Node project with no coverage is exactly the gap it was built to close.
- `README.md`: add a line noting the docs site exists and linking it (once Phase 1's CI job produces a real URL, use that; until then, note it's built from `docs/website/`).
- `docs/development.md`: add a short subsection on building/previewing the docs site locally (`cd docs/website && npm install && npm start`), matching this file's existing role as the pointer for "how do I run things locally."

### 1c. Local Docker Compose preview service (`tests/container/docker-compose.yml`)

- `docs/website/Dockerfile`: a simple two-stage build, distinct from `frontend/Dockerfile`'s nginx-based pattern since this is a dev-only preview tool, not a production image pushed by `ci.yml`'s `docker-build` job — `FROM node:24-alpine AS build`, `npm ci` + `npm run build`, then a second `node:24-alpine` stage that copies `build/` and runs Docusaurus's own `npm run serve -- --host 0.0.0.0 --port 3001 --no-open` (the official Docusaurus way to serve a real production build locally — exercises the same static output the GitHub Pages deploy will, unlike `npm start`'s dev server). `EXPOSE 3001`, a `HEALTHCHECK` hitting `/` matching the pattern every other service in this compose file already uses.
- Add a `docs` service to `tests/container/docker-compose.yml`: `build: { context: ../../docs/website }`, `ports: ["3001:3001"]`, healthcheck as above. No `depends_on` — the docs site is fully static and independent of `db`/`backend`/anything else in the stack, unlike every other service here. Add an explanatory header comment matching this file's existing per-service style (e.g. why 3001, why no `depends_on`, that it's dev/eval-only per the decision above).
- `docs/development.md`'s "Quick start" section (already extended once in Phase 1b to mention building the docs site) gets one more line: **Docs site preview**: http://localhost:3001, alongside the existing Frontend/Backend/MailHog/MinIO URL list.
- Root `docker-compose.yml` (production) is deliberately left untouched per the decision above.

### 1d. CI wiring (`.github/workflows/ci.yml`)

- Update the header comment's job list (currently five jobs, `frontend`/`backend-tests`/`e2e-tests`/`publish-badges`/`docker-build`) to add the two new jobs, matching that comment block's existing per-job explanatory style.
- New job `docs`: `runs-on: ubuntu-latest`, `defaults.run.working-directory: docs/website`, `actions/checkout@v7`, `actions/setup-node@v7` with `node-version: "24"` (matching the two existing `setup-node` call sites at the time of writing), `npm ci`, `npm run typecheck`, `npm run build` (this is what actually exercises `onBrokenLinks`/`onBrokenAnchors`). Runs on every push and PR, no `needs:` — independent of and parallel with the other jobs, since it shares no state with them.
- New job `docs-deploy`: `needs: [docs]`, `if: github.event_name == 'push' && github.ref == 'refs/heads/main'` (mirrors `docker-build`'s push-vs-PR gating pattern), `permissions: { pages: write, id-token: write }` (the workflow-level `permissions: { contents: read }` block needs a job-level override here, same pattern as `docker-build`'s `packages: write` override), `environment: { name: github-pages, url: ${{ steps.deployment.outputs.page_url }} }`. Steps: checkout, setup-node, `npm ci` + `npm run build` again (a separate job has a separate runner/workspace — don't try to pass the build artifact from `docs` via `actions/upload-artifact`/`download-artifact` purely to save a ~1min rebuild; simplicity here matches `docker-build`'s own "small amount of duplicated build time... in exchange for not needing a third shared job" reasoning, quoted from that job's own comment), `actions/configure-pages@v5`, `actions/upload-pages-artifact@v3` (path: `docs/website/build`), `actions/deploy-pages@v4`.
- Confirm exact current major versions of `actions/checkout`, `actions/setup-node` (both already `v7` per the greps above) and look up current `actions/configure-pages`/`actions/upload-pages-artifact`/`actions/deploy-pages` majors before pinning (do not guess versions).

**Verification:**
- `cd docs/website && npm install && npm run typecheck && npm run build` — clean, zero broken-link/anchor errors, `build/` produced.
- `npm run serve` and click through the placeholder nav to confirm every sidebar category/page renders and local search returns results for at least one indexed term.
- Confirm `docs/plans/`'s five moved files' cross-references: `grep -rn` each bare filename repo-wide (excluding `.git`, `node_modules`, `graphify-out`) and confirm every hit is prefixed correctly; spot-check 5–10 rendered links (in `CLAUDE.md`'s prose, in `docs/decisions.md`'s historical entries, in `docs/modules.md`) by opening the linked file at the given relative path.
- `cd tests/container && docker compose up --build -d docs` (per this repo's own "rebuild+recreate before testing, compose doesn't bind-mount source" rule): confirm the container reaches healthy and http://localhost:3001 serves the real built site (placeholder-content sidebar from 1b navigable, search working) — bringing up just this one service (`docker compose up --build -d docs` names it explicitly) is enough to verify it in isolation without needing `db`/`backend`/etc. healthy first, since it has no `depends_on`.
- `act` (per `docs/development.md`'s existing "Testing the pipeline locally with `act`" section) or a real push to a branch/PR to confirm the new `docs` job runs; `docs-deploy` cannot be verified end-to-end until GitHub Pages is enabled in repo settings (flag to user — see "Open decisions" above) and this lands on `main`.
- `docs/decisions.md` entry recording the location/name/tidy-scope/search-plugin/CI-structure decisions above, each tagged.

---

## Phase 2 — Introduction + Concepts section

**Sources:** `README.md` (top-level description, "requirements workflow"/"built for how teams actually work"/"enterprise-ready" sections), `docs/solution-architecture.md` (Purpose, Architectural Goals, High-Level Solution Overview), `docs/decisions.md` (identity-vs-version split, RBAC model, temporal data model — for *why*, not implementation detail), `docs/user-guide.md`.

**Pages:**
- *Overview* (`intro.md`) — what ReqTrackManager is, who it's for, the elevator pitch from `README.md`'s opening paragraph, 2–3 of the existing `docs/screenshots/*.png` (reuse, don't recapture), a "where to go next" set of links into Installation and Workflows.
- *Use cases* — concrete scenarios, not a restatement of the feature list: e.g. a hardware/firmware team needing real requirement identity and traceability without IBM DOORS' cost (the framing `README.md`'s own opening paragraph already uses); a regulated-software team (medical device, automotive, aerospace) needing baselines and an auditable change-request trail; a team outgrowing a shared spreadsheet where nobody trusts the "latest" tab by the second review cycle; a team that needs a compliance framework (ISO/IEC, etc.) tracked against its actual requirements, once the Compliance module is enabled; a multi-project engineering organisation needing project-level access control instead of one shared document. Ground each scenario in a feature this plan actually documents elsewhere and link to it (Workflows/Core Features/Modules) rather than describing hypothetical capability.
- Concepts → *Organisations and projects* — the org/project containment model, project hierarchy (parent/child), roles at each level (pointer to Core Features → RBAC for the full detail, this page stays conceptual).
- Concepts → *Requirements, versions, and the lifecycle* — identity vs. version split (`docs/decisions.md`'s "Identity vs. version split" entry, explained plainly), draft → reviewed → approved → completed, locking once approved, why change requests exist.
- Concepts → *Change requests and baselines* — what a baseline is, why it exists ("what did we commit to, answerable months later"), the change-request-only-once-locked rule.
- Concepts → *Roles, groups, and access control* — org roles, project roles, project groups, the "org admin ≠ automatic content access" distinction (a real, easily-misunderstood design decision worth surfacing at the concepts level).
- Concepts → *Custom fields, terminology, and templates* — how a team's own vocabulary/tracked attributes show up without a fork, and how templates carry that into new projects.
- Concepts → *Discussions, notifications, and audit* — threaded discussion vs. the change log, in-app/email notification model, what gets audit-logged and why.

**Verification:** `npm run build` clean; every Concepts page cross-links to at least one Core Features or Workflows page (no orphaned conceptual page with nowhere to act on what it just explained); every page in this phase (Overview, Use cases, and all Concepts pages) carries at least one screenshot or themed Mermaid diagram per the visual-style decisions above — a plausible one for most Concepts pages is a small Mermaid diagram of the entity relationship being explained (e.g. identity-vs-version, org/project containment).

---

## Phase 3 — Installation & Deployment chapter

**Sources:** `docs/deployment.md` (primary), `docs/development.md` (local/eval stack), `README.md`'s "Production deployment"/"Configuration" sections.

**Pages (one chapter, several subpages — the one section allowed this shape per the user's instruction):**
- *Overview* — the two-Compose-stack model (`docker-compose.yml` production vs. `tests/container/docker-compose.yml` dev/eval), which one to use when.
- *Quick start (local / evaluation)* — adapted from `docs/development.md`'s "Quick start" + "Demo data" sections.
- *Production deployment* — required secrets, `docker compose up --build -d`, the components list (MinIO, OIDC/SSO-per-org, MCP server) from `README.md`.
- *Configuration reference* — the full environment-variable table from `docs/deployment.md`.
- *Storage, database, and migrations* — `docs/deployment.md`'s Storage backend / Database / Migrations subsections.
- *TLS, reverse proxy, and same-origin deployment* — from `docs/deployment.md`.
- *Observability* — Prometheus metrics, health checks, the Loki/Tempo/Grafana Alloy stack, pointer to `observability/` in the repo.
- *Scaling and adding modules* — `docs/deployment.md`'s "Adding an external module"/"Adding a Tier C module"/"Scaling beyond a single backend replica" subsections.
- *Troubleshooting* — from `docs/deployment.md`.

**Verification:** every environment variable named in `docs/deployment.md`'s config table appears in the *Configuration reference* page (diff the two); the *Overview* page carries the two-Compose-stack diagram (reuse/adapt `docs/figures/architecture/project_structure.svg` or a themed Mermaid `flowchart`, per the visual-style decisions above — whichever renders more clearly for "which stack, when," not necessarily the most literal port of the source doc's own diagram); `npm run build` clean.

---

## Phase 4 — Core Features section

**Sources:** `docs/user-guide.md`, `docs/solution-architecture.md`'s Component Architecture, `README.md`.

**Pages** (one per major feature area — practical "how this works and what it does" pages, distinct from Concepts' "why" framing and Workflows' "how do I, as a user, do X" framing):
- Requirements management (fields, components/categories, ordering, linking/traceability, CSV import/export)
- Change requests (submission, tasks, advisory stakeholder voting, approve/reject)
- Stages and baselining
- Requirement actions
- Reports and export (PDF/CSV, branding templates, Markdown/WYSIWYG intro/chapters/appendices)
- Notifications and email (in-app, email, digest, per-type preferences, unsubscribe)
- File attachments and shared resources
- Search, filtering, and view-mode persistence
- Two-factor authentication
- Personal access tokens
- Project templates
- Zip export/import (project and organisation backup/migration)

**Verification:** every bullet under `README.md`'s "The requirements workflow" and "Built for how teams actually work" sections is covered by at least one Core Features page; every page in this section carries at least one screenshot of the relevant UI (captured fresh against the demo dataset per the screenshot standard above, since most of these don't already have a `docs/screenshots/*.png` counterpart) or a themed Mermaid diagram where the feature is better explained as a flow than a screenshot (e.g. the notification digest/unsubscribe flow, the zip export/import round-trip); `npm run build` clean.

---

## Phase 5 — Workflows section

Build exactly the pages listed in the **Content Inventory** table above. Each page is a task-oriented how-to (numbered steps, a screenshot of each key screen state, links back to the relevant Concepts/Core Features pages for the "why"). Source material: `docs/e2e-workflows.md`'s persona/workflow descriptions (describes *what's tested*, so translate into *what a user does*, not test-suite language), `docs/user-guide.md`, and the actual running app (spin up `tests/container/`'s stack with demo data per `docs/development.md` and click through each workflow while writing its page, rather than writing purely from the test descriptions — the two can drift).

**Verification:** the Content Inventory table's own verification step (every source page/workflow has a destination anchor); every Workflows page carries at least one screenshot per major step/screen it walks through (this section is the most screenshot-heavy in the site by nature — it's literally "how to use this screen" — so the bar here is real coverage of each step, not just one token image per page); `npm run build` clean.

---

## Phase 6 — Modules section (own top-level nav entry)

**Sources:** `docs/modules.md` (the module system itself), `docs/compliance-module.md` (the shipped Compliance module).

**Pages:**
- *Overview* — why modules exist, entitlement vs. enablement, the registry, adapted from `docs/modules.md`'s own "Why modules exist"/"Core concepts, at a glance" sections (this can stay closer to the source doc's own framing — it's already written for a reader outside this repo, per that file's own stated audience).
- *Compliance module* — enabling it, roles, standards lifecycle, assessment, evidence, approval/sign-off, scheduled reviews, cross-standard mapping, reporting — adapted from `docs/compliance-module.md` in full (that doc is short, 131 lines; likely close to a direct port with light editing for site tone).
- *Building your own module* — the `ModuleDefinition` contract, the registry/gating model (entitlement × enablement), Tier A frontend integration (installed, compiled into the core image — how the shipped Compliance module itself is built), module-contributed RBAC, module-contributed MCP tools, the "building a new module" checklist — adapted from `docs/modules.md`'s registry/gating/contract/RBAC/MCP-tools/checklist sections. Written for someone contributing a module that ships *inside* this repo (or a fork of it).
- *Third-party and federated modules* — Tier B (remote) and Tier C (federated / Module Federation, no rebuild of either image), what's different for a module you don't compile in: the Tier C module-author guide (what a third-party module bundle must expose — `remote_entry_url`, its own `module.py`/`MODULE_DEFINITION`, the trust boundary it runs inside) and the Tier C operator guide (what a deployment operator vetting and installing someone else's module needs to check before enabling it — no sandbox, same origin/DOM/cookies as the rest of the app) — adapted from `docs/modules.md`'s "Tier C: module-author guide" and "Tier C: operator guide" sections. Cross-links both directions with Phase 3's already-shipped *Scaling and adding modules* page (`docs/website/docs/installation-deployment/scaling-and-modules.md`), which covers the same Tier C material from the deployment-mechanics angle (mounting `EXTRA_MODULES_PATH`, mounting the frontend bundle, `docker compose up -d`) — this page is the "should you, and what must the module provide" companion to that page's "how to actually wire it in." As part of this page landing, repoint that existing page's `[Building your own module](../modules/index.md)` link at this page's real slug.
- *Roadmap* (short page) — one paragraph noting more modules are planned, no feature-by-feature detail, no link into the internal `docs/plans/future-modules-2026-09-overview.md` (that file is a pre-decision working document, not something to surface to external readers of a public site) — Decided by: Agent, revisit with the user if a link is wanted after all.

**Verification:** `npm run build` clean (including confirming the repointed link from `installation-deployment/scaling-and-modules.md` resolves); spot-check the *Compliance module* page against the live app's actual Compliance-enabled UI (per `CLAUDE.md`'s "verify reachable and readable output" standard — a documented feature must actually match what's in the app, not just what an older doc says); *Overview* reuses/adapts `docs/modules.md`'s own registry-flowchart Mermaid diagram (themed per Phase 1), and *Compliance module* carries fresh screenshots of the Compliance-enabled UI (standards list, assessment view, a report) rather than relying on diagrams alone, since this page's subject is a concrete feature, not an abstract mechanism; *Third-party and federated modules* carries a themed Mermaid diagram of the Tier C trust boundary (same-origin/DOM/cookies, no sandbox) since there's no single UI screen that shows this.

---

## Phase 7 — API & Integrations section

Everything that's a way for something *outside* the web UI to talk to a ReqTrackManager instance — the REST API directly, SSO/SCIM for identity, and AI assistants via MCP. Added in response to the user's explicit follow-up ask for real API-use documentation, not just a pointer at Swagger.

**Sources:** live backend (`/openapi.json`, `/docs`) plus `backend/app/routers/*.py` for ground truth, `docs/mcp-server.md` (mature, already written for external readers — near-direct port for its pages), `docs/enterprise-integration.md`.

**Pages:**
- *REST API overview* — base URL/versioning (`/api/v1/...`), request/response conventions, pagination, error format; a short note that `/docs` (Swagger UI) and `/openapi.json` on any running instance are the canonical, always-current schema, so this page explains concepts rather than trying to statically mirror a live-generated schema (which would drift immediately) — this replaces the thin "API reference" pointer page from the original draft.
- *Authenticating* — session tokens vs. Personal Access Tokens, how to create a PAT (**Preferences → Personal Access Tokens**), scoping to specific organisations/projects, the `Authorization: Bearer <token>` header — adapted from `docs/mcp-server.md`'s own "Getting a token"/"Authentication model" sections, which already explain this correctly for MCP and apply unchanged to calling the REST API directly.
- *Common API tasks* — a handful of worked examples (`curl`/short script) against real endpoints: list requirements for a project, create a requirement, list change requests, pull a report — written and run against a real running instance (the dev/eval stack with demo data), not invented from route names alone.
- *Single sign-on (OIDC/SSO)* — per-organisation identity providers, adapted from `docs/enterprise-integration.md`'s "What was built: OIDC login" section.
- *SCIM provisioning* — adapted from `docs/enterprise-integration.md`'s "Built: SCIM provisioning" section.
- *AI assistants (MCP)* — *Overview*, *Setting up Claude Code*, *Setting up VS Code (Copilot Chat)*, *Setting up Microsoft Copilot Studio*, *Generic / other MCP clients*, *Deploying for remote clients*, *Known limitations* — following `docs/mcp-server.md`'s existing heading structure closely; its "Authentication model"/"Getting a token" content is covered once, on the *Authenticating* page above, and cross-linked from here rather than duplicated.
- *Extending with modules* — one short page, pointer only: a module can contribute its own REST endpoints and MCP tools (per `docs/modules.md`); links to Modules → *Building your own module* (Phase 6) for the real content rather than repeating it.

**Verification:** `npm run build` clean; every code sample/config snippet (including everything ported from `docs/mcp-server.md`) re-run or re-checked against the current `mcp-server/`/`backend/app/routers/` code — don't assume a source doc is still accurate, per `CLAUDE.md`'s general instruction to verify before recommending; *Authenticating* and *Common API tasks* each carry at least one screenshot of the relevant UI (the PAT creation screen; a Swagger UI "Try it out" call, or a terminal screenshot of the worked `curl` example's real output) — this section leans more on code samples and terminal/UI screenshots than Mermaid diagrams, which is appropriate to its subject.

---

## Phase 8 — Enterprise & Security section

Posture content — what ReqTrackManager does to protect data and what's been done to demonstrate that — distinct from Phase 7's integration how-tos.

**Sources:** `docs/soc2/` (policies + `trust-services-criteria-mapping.md`), `README.md`'s "Enterprise-ready" section, `docs/decisions.md`'s encryption-related entries.

**Pages:**
- Encryption and secrets handling — application-layer encryption for OIDC client secrets, SMTP passwords, TOTP secrets; distinct-key-from-JWT-signing design.
- Two-factor auth and personal access tokens, security angle — cross-link to Core Features' own PAT/2FA how-to pages (Phase 4) rather than duplicating; this page's angle is *why* these exist and what they protect against.
- SOC 2 compliance posture — a candid summary (mirroring `docs/soc2/`'s own "document real gaps" character per `CLAUDE.md`) of the adopted policy set and known gaps, linking to `docs/soc2/` in the repo for the full policies rather than reproducing them verbatim on the public site.

**Verification:** `npm run build` clean; confirm no Restricted-classified detail (secrets, actual key material, internal-only gap specifics beyond what `docs/soc2/`'s own README already treats as public-appropriate) leaks onto the public site — re-read `docs/soc2/policies/data-classification-and-confidentiality-policy.md` before writing this phase's content, per `CLAUDE.md`'s rule to consult the relevant policy before a change touching this area; the encryption page carries a themed Mermaid diagram of the key/secret relationships (JWT signing key vs. `APP_SECRET_ENCRYPTION_KEY`, what each protects) rather than a screenshot, since there's no UI surface to show for this content.

---

## Phase 9 — Reference + Contributing section

**Sources:** `docs/solution-architecture.md`, `docs/decisions.md` (pointer, not reproduction — it's a 5700+-line internal log, not site content), backend OpenAPI (`/openapi.json`, per `docs/development.md`), `docs/development.md`'s contributor workflow.

**Pages:**
- Architecture overview (adapted, diagram-preserving per `CLAUDE.md`'s Mermaid-diagram preference — `docs/solution-architecture.md` likely already has Mermaid source to reuse) — validate every reused Mermaid diagram renders in Docusaurus's own Mermaid support (`@docusaurus/theme-mermaid`) with Phase 1's custom theme applied, before/instead of assuming source-doc syntax ports unchanged; lead with a reused/adapted `docs/figures/architecture/project_structure.svg`-style showcase diagram per the visual-style decision above, Mermaid diagrams for the detailed sub-views.
- Glossary — short, pulls terminology introduced across Concepts pages into one alphabetical reference.
- Contributing — short pointer page: local dev setup, test suites, linting, CI — links to `docs/development.md` in the repo rather than duplicating it (matching this repo's own existing README convention of "short section + pointer" for development workflow, per `CLAUDE.md`'s README-requirements section).

**Verification:** `npm run build` clean; every Mermaid diagram renders (visually check in `npm run serve`, not just "build didn't error").

---

## Phase 10 — Polish, cross-linking, search, broken-link gate, final QA

- Visual QA pass, specifically for the additions above: every Concepts/Core Features/Workflows/Modules/API & Integrations page has at least one image or diagram (spot-audit against the per-phase bars set in Phases 2, 4–8); every image has real alt text; every Mermaid diagram renders with the Phase 1 custom theme in both light and dark mode; the handful of reused/hand-authored showcase SVGs (Introduction, Architecture overview) display crisply at typical page widths (no upscaled/blurry raster fallback).
- Full click-through of every sidebar page (`npm run serve`), checking for: broken images, unstyled/overflowing wide tables or code blocks (per `CLAUDE.md`'s general responsive-content expectations, applied here even though this isn't an Artifact), dark/light theme correctness (Docusaurus's default theme switcher — confirm it isn't broken by any custom CSS added in earlier phases).
- Confirm local search indexes and returns sensible results for a sample of terms drawn from each top-level section.
- Repo-wide final check: `README.md` links the deployed site (once `docs-deploy` has run at least once on `main` and a real Pages URL exists); no remaining docs/plans reference-fixing debt from Phase 1.
- Close this plan's status table, final `docs/decisions.md` summary entry.

---

## Notes for whoever resumes a phase

- One phase per session, same discipline as `docs/plans/compliance-module-plan.md`: implement, verify per that phase's bar above (`npm run build` clean with `onBrokenLinks: 'throw'` is the non-negotiable minimum for every content phase), record the `docs/decisions.md` entry, tick the status table, stop.
- Write content from the actual current app/docs state, not purely by porting old prose — several source docs (`docs/mcp-server.md`, `docs/compliance-module.md`) are already written for an external audience and should port closely, but `docs/decisions.md`/`docs/solution-architecture.md`/`docs/e2e-workflows.md` are written for a different audience (implementers, test authors) and need real translation, not copy-paste.
- `docs/website/` gets its own `.nvmrc`/lockfile-sync script mirroring `frontend/`'s — always use it after any `docs/website/package.json` change, never a bare `npm install`, same reasoning as `CLAUDE.md`'s existing frontend-dependency-changes rule.
- Re-run the Content Inventory table's verification grep before Phase 5 if a lot of time has passed since this plan was written — new frontend pages or e2e-workflow scenarios added by other work in the meantime need their own row.
