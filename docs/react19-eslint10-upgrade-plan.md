# Vite 8 + React 19.3.0 Upgrade, then ESLint 9→10 Migration — Implementation Plan

This document is the persistent, session-resumable implementation plan for upgrading the frontend's core toolchain (Vite, React) and finishing a previously-blocked ESLint 9→10 migration. It follows the same phased, resumable structure as `docs/compliance-module-plan.md` and `docs/platform-review-2026-09-plan.md` — read cold, by a session with no memory of this conversation.

**If you are starting a session against this plan, read "Status / Resume Here" below first.**

---

## Status / Resume Here

**Last updated:** 2026-09-14 (Phase 2 complete; next session starts fresh at Phase 3, per this plan's own discipline of not cascading into the next phase automatically).

**Overall progress:** 2 / 5 phases complete.

| # | Phase | Status |
|---|-------|--------|
| 1 | Vite 6 → 8.3.0 (Rolldown bundler swap) + `@vitejs/plugin-react` 4 → 5.2.0 | [x] Done — see `docs/decisions.md`'s "React 19/ESLint 10 upgrade plan, Phase 1" entry |
| 2 | React 18 → 19.3.0 runtime bump (`react`/`react-dom`/`@types/react`/`@types/react-dom`) | [x] Done — see `docs/decisions.md`'s "React 19/ESLint 10 upgrade plan, Phase 2" entry |
| 3 | ESLint 10 + `eslint-plugin-react-hooks` 7.1.1 migration, batch A (core files) | [ ] Not started |
| 4 | ESLint migration batch B (compliance module) + `react-hooks/refs` investigation | [ ] Not started |
| 5 | Final sweep and close-out | [ ] Not started |

**Instructions for whoever picks up the next phase:** implement exactly one phase, leave the repo passing its tests and in a clean state, add a `docs/decisions.md` entry (tagged **Decided by: User** or **Decided by: Agent** for every design call per `CLAUDE.md`'s documentation-governance rule), then come back to this file and tick its checkbox and update "Last updated." Do not cascade into the next phase automatically.

---

## Origin

`docs/decisions.md`'s 2026-09-14 entry ("ESLint 9→10 migration attempted: blocked on React 19's `useEffectEvent`") recorded that bumping `eslint`/`eslint-plugin-react-hooks` to support ESLint 10 pulls in React-Compiler-derived lint rules (`react-hooks/set-state-in-effect`, `react-hooks/refs`) that flag 76 sites across ~52 files — almost all the app's standard `useEffect(() => { reload(); }, [deps])` data-fetch pattern. Those rules' only clean fix is React 19's `useEffectEvent` hook, unavailable on this app's pinned React `^18.3.1`. The user chose to scope a React 19 upgrade first (**Decided by: User**), then asked to start that planning and — since it touches ~50+ files across several dependency bumps — asked for a resumable phased plan doc like `docs/compliance-module-plan.md`/`docs/platform-review-2026-09-plan.md` (**Decided by: User**). Mid-planning, the user also asked to fold in the also-overdue Vite upgrade (pinned `^6.4.3` at the time; `latest` was `8.3.0`), and after reviewing the tradeoff between stopping at Vite 7 versus going to Vite 8, chose Vite 8 (**Decided by: User**).

---

## Research already done (informs every phase below)

- Full repo audit found **zero** React-19-breaking patterns already in use in `frontend/src`: no PropTypes, no function-component `defaultProps`, no string refs, no class components/legacy lifecycles, no legacy Context API, no `react-dom/test-utils` imports; `main.tsx` already uses `react-dom/client`'s `createRoot`. Only things to spot-check post-bump: two `useId()` sites (`components/UserAutocomplete.tsx`, `components/Tabs.stories.tsx`), two `forwardRef` components (`components/FileUploadTrigger.tsx`, `components/CsvImportWizard.tsx`), and `src/modules/federatedLoader.ts`'s `__RTM_FEDERATED_SHARED_SCOPE__` window contract (shares a react/react-dom instance with a future remote module).
- `npm view <pkg> peerDependencies` confirmed every real frontend dependency already declares React 19 support: `react-router-dom@7.18.2` (`>=18`), `recharts@3.10.1` (`^19.0.0` explicit), `@storybook/react-vite@10.5.5`/`storybook@10.5.5` (`^19.0.0` explicit), `@testing-library/react` (transitive via `@storybook/addon-vitest`, `^19.0.0`), `lucide-react@0.446.0` (`^19.0.0-rc`). `@types/react@19.3.0`/`@types/react-dom@19.3.0` exist on npm and match each other. `react@19.3.0`/`react-dom@19.3.0` confirmed as the real current `latest` dist-tag.
- Confirmed via web search (multiple consistent sources) that `useEffectEvent` stabilized as a plain, non-experimental export in React 19.2 and remains stable in 19.3 — the real fix mechanism the deferred lint rules expect, not a workaround.
- **Vite**: `frontend/vite.config.ts` read in full — only `plugins: [react()]`, server/preview host/port, and a Vitest `test.projects` block for Storybook interaction tests (`@storybook/addon-vitest`'s `storybookTest` plugin, browser mode via `@vitest/browser-playwright`/Chromium) plus root-level `coverage`/`reporters`. No `build.rollupOptions`, no custom `esbuild` block, no AMD/SystemJS output, no `transformIndexHtml` hook — none of Vite 7 or 8's actual breaking-change surface is touched by this config.
  - **Vite 8** (`8.3.0`, current `latest`, stable since ~March 2026): replaces Rollup+esbuild with Rolldown (Rust-based) as the *only*, non-optional bundler. `build.rollupOptions` → `build.rolldownOptions` (old name kept as a deprecated compat shim), `esbuild` config block → `oxc`, a few uncommon Rollup hooks removed (`shouldTransformCachedModule`, `resolveImportMeta`, `renderDynamicImport`, `resolveFileUrl` — none used here), AMD/SystemJS output dropped (this project only ships an ES-module browser build via nginx), CJS-interop change (shimmable via `legacy.inconsistentCjsInterop` if ever needed). `@vitejs/plugin-react@5.2.0` is peer-certified for `vite: '... || ^8.0.0'` **without** requiring the newer `@rolldown/plugin-babel`/`babel-plugin-react-compiler`/`oxc-transform-react` peers — those only appear starting at `@vitejs/plugin-react@6.0.0`, which additionally adopts Rolldown-native transforms and optionally the React Compiler babel plugin. **This plan targets Vite `8.3.0` + `@vitejs/plugin-react@5.2.0` only — it does not adopt plugin-react 6.x or the React Compiler babel plugin; that is a distinct, larger decision to raise separately if wanted later.**
  - `vitest@4.1.11`, `@vitest/browser-playwright@4.1.11`, `@storybook/react-vite@10.5.5`/`storybook@10.5.5` (all already at their current pinned versions) already declare Vite 8 support today — no version bump needed on those beyond what's already pinned.
- Of the 76 ESLint-migration-blocked lint sites: **68 are `react-hooks/set-state-in-effect`**, fixable by wrapping the effect's setState-touching logic in a `useEffectEvent`-created stable callback. **8 are `react-hooks/refs`**, all in `ProjectAdminPage.tsx`, all shaped as `onToggle: () => toggleProjectGroupRole(...)` inside an `options.map()` array literal passed to `MultiSelectDropdown` — spot-checked, and none of `toggleProjectGroupRole`/`addGroupMember`/etc. appear to close over a ref directly; this looks like the compiler's conservative refs-in-a-data-object heuristic not recognizing `onToggle` as an event-handler-only field, rather than a real bug — needs a real per-site look during Phase 4, not an assumed fix.
- The 68 `set-state-in-effect` sites split almost evenly along this repo's own existing module boundary: **25 files (~34 sites) under `src/modules/compliance/`**, **27 files (~34 sites + all 8 refs) everywhere else** (`src/pages`, `src/components`, `src/context`, `src/hooks`) — matching `CLAUDE.md`'s "Modular Feature System Boundary," which already treats the compliance module as independently bounded, so splitting the lint-fix work along that same line (Phases 3/4 below) is a natural checkpoint, not an arbitrary split.

Outcome of this plan: `vite@8.3.0`/`@vitejs/plugin-react@5.2.0`, `react`/`react-dom@19.3.0`, `eslint@10.x`/`eslint-plugin-react-hooks@7.1.1`, zero lint errors, no behavior regressions.

---

## Phase 1 — Vite 6 → 8.3.0 (Rolldown bundler swap), isolated from the React/ESLint work

Do this bump **first and alone** so a build/test failure can be attributed to the bundler swap specifically, not conflated with the React 19 or ESLint changes that follow.

**Changes:**
- `frontend/package.json`: `vite` `^6.4.3` → `^8.3.0`; `@vitejs/plugin-react` `^4.7.0` → `^5.2.0` **— explicitly not `^6.x`**. `plugin-react@5.2.0` is peer-certified for `vite: '... || ^8.0.0'` on its own; `6.x` additionally *requires* `@rolldown/plugin-babel`, `babel-plugin-react-compiler`, and `oxc-transform-react` as peers, which means adopting Rolldown-native transforms and the React Compiler babel plugin — a materially different, separately-consequential decision (the React Compiler changes runtime optimization semantics app-wide) that this plan does not make. If `sync-lockfile.sh` or `npm ci` pulls in `6.x` or those peers for any reason, stop and treat that as a sign the `^5.2.0` pin needs tightening, not something to accept silently. Leave `vitest`/`@vitest/browser-playwright`/`@vitest/coverage-v8`/`storybook`/`@storybook/*` untouched — already declare Vite 8 support at their current pinned versions.
- Run `frontend/scripts/sync-lockfile.sh`.
- Skim the diff for any Rolldown compat-shim deprecation warnings surfaced by `npm run build` (e.g. if anything now resolves through `build.rolldownOptions`'s shim) even though `vite.config.ts` doesn't set `rollupOptions`/`esbuild` today.

**Verification:**
- `npm run build` (`tsc -b && vite build`) — confirm the production build still produces a working bundle (check `dist/` output isn't obviously malformed, e.g. missing chunks).
- `npm run lint` — unaffected by this phase, should stay exactly as it is today (still on `eslint@9.39.5`).
- `npm run test-storybook -- --coverage` — full Storybook/Vitest browser-mode suite (most likely to reveal a Rolldown-transform regression, since it runs every story through Chromium).
- Rebuild+recreate the docker-compose frontend container (compose doesn't bind-mount source) and run the full Playwright suite (90 specs) against it.
- `docs/decisions.md` entry (Decided by: User for choosing Vite 8 over stopping at Vite 7; note explicitly that `@vitejs/plugin-react@6.x`/the React Compiler babel plugin were deliberately not adopted).

---

## Phase 2 — React 18 → 19.3.0 runtime bump

Builds on the now-Vite-8 baseline; still isolated from the ESLint migration.

**Changes:**
- `frontend/package.json`: `react`/`react-dom` `^18.3.1` → `^19.3.0`; `@types/react`/`@types/react-dom` `^18.3.5`/`^18.3.0` → `^19.3.0`.
- Run `sync-lockfile.sh`. Do **not** touch `eslint`/`@eslint/js`/`eslint-plugin-react-hooks` yet — stay on `^9.39.5`/`^5.2.0` so `npm run lint` should still be clean and unchanged.

**Verification:**
- `npm run lint` — expect clean, unchanged rule set.
- `npm run build`, `npm run test-storybook -- --coverage`.
- Rebuild+recreate containers, full Playwright suite (90 specs).
- Manually re-check the two `useId()` sites, the two `forwardRef` components, and `federatedLoader.ts`'s shared-scope contract for behavior drift.
- `docs/decisions.md` entry (Decided by: User for the React 19 upgrade decision itself).

---

## Phase 3 — ESLint 10 + `eslint-plugin-react-hooks` 7.1.1 migration, batch A (core files)

Scope: everywhere **outside** `src/modules/compliance/` — `src/pages/*`, `src/components/*`, `src/context/*`, `src/hooks/*`. ~27 files, ~34 `set-state-in-effect` sites (`ProjectAdminPage.tsx`'s 2 `set-state-in-effect` sites are in scope here; its 8 `refs` findings are deferred to Phase 4).

**Changes:**
- `frontend/package.json`: `eslint` → `^10.10.0`, `@eslint/js` → `^10.0.1`, `eslint-plugin-react-hooks` → `^7.1.1`. Run `sync-lockfile.sh`.
- For each flagged site: wrap the setState-touching logic (the local function the effect calls, e.g. `reload`, or inline resets like `setLoadError(null)`) in `useEffectEvent`, and call that stable event-callback from the effect instead — preserving exact existing fetch/reset behavior.
- Where a fixed site carries a `// eslint-disable-next-line react-hooks/exhaustive-deps` comment (several do, e.g. `RequirementsPage.tsx`, `ChangeRequestDetailPage.tsx`), remove it if the `useEffectEvent` restructuring makes it unnecessary (an effect-event callback isn't a reactive dependency).

**Verification:**
- `npm run lint`: 0 errors for every file in this batch's scope (compliance-module files will still show pending errors until Phase 4 — expected).
- `npm run build`, `npm run test-storybook -- --coverage`, full Playwright suite (rebuild+recreate containers first).
- `docs/decisions.md` entry.

---

## Phase 4 — ESLint migration batch B (compliance module) + the `react-hooks/refs` investigation

Scope: `src/modules/compliance/*` (~25 files, ~34 `set-state-in-effect` sites) plus the 8 `react-hooks/refs` findings in `ProjectAdminPage.tsx` deferred from Phase 3.

**Changes:**
- Same `useEffectEvent` restructuring pattern as Phase 3, applied across the compliance-module inventory (`ApplicabilityTree.tsx`, `ProjectCompliancePage.tsx`, `StandardWorkspacePage.tsx`, `RequirementMappingsModal.tsx`, etc.).
- For the 8 `refs` findings: read `MultiSelectDropdown`'s implementation and `toggleProjectGroupRole`'s full closure chain to determine whether the compiler is catching a real risk or a false positive from the options-array shape. If real, fix it properly. If a false positive, say so explicitly and get the user's sign-off before disabling `react-hooks/refs` for those specific lines with a documented comment (per `CLAUDE.md`'s rule that a lint rule can only be turned off, with justification, not silently).

**Verification:**
- `npm run lint`: 0 errors repo-wide.
- `npm run build`, `npm run test-storybook -- --coverage`, full Playwright suite (rebuild+recreate containers first).
- `docs/decisions.md` entry.

---

## Phase 5 — Final sweep and close-out

- Full clean-slate verification: `npm run lint`, `npm run build`, `npm run test-storybook -- --coverage`, full Playwright suite (90 specs) — all green, all at once, as the final gate.
- Check repo-wide for any other stale "React 18"/"Vite 6" mentions (research found only `docs/decisions.md`'s own 2026-09-14 entry — update it to point at this plan doc and mark the migration resolved, not still-open).
- Close this doc's status table (all phases done) and add a final summary `docs/decisions.md` entry for the overall upgrade.

---

## Notes for whoever resumes a phase

- One phase per session/PR, same discipline as `docs/compliance-module-plan.md`: implement, verify per that phase's bar above, record the `docs/decisions.md` entry, tick the status table, stop — don't cascade into the next phase automatically.
- Always use `frontend/scripts/sync-lockfile.sh` after any `package.json` change in this plan, never a bare `npm install`.
- Rebuild+recreate the docker-compose containers before any live/Playwright verification — compose does not bind-mount source in this project.
