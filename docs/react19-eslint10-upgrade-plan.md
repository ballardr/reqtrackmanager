# Vite 8 + React 19.3.0 Upgrade, then ESLint 9→10 Migration — Implementation Plan

This document is the persistent, session-resumable implementation plan for upgrading the frontend's core toolchain (Vite, React) and finishing a previously-blocked ESLint 9→10 migration. It follows the same phased, resumable structure as `docs/compliance-module-plan.md` and `docs/platform-review-2026-09-plan.md` — read cold, by a session with no memory of this conversation.

**If you are starting a session against this plan, read "Status / Resume Here" below first.**

---

## Status / Resume Here

**Last updated:** 2026-09-15 (Phase 4 complete; next session starts fresh at Phase 5, per this plan's own discipline of not cascading into the next phase automatically).

**Overall progress:** 4 / 5 phases complete.

| # | Phase | Status |
|---|-------|--------|
| 1 | Vite 6 → 8.3.0 (Rolldown bundler swap) + `@vitejs/plugin-react` 4 → 5.2.0 | [x] Done — see `docs/decisions.md`'s "React 19/ESLint 10 upgrade plan, Phase 1" entry |
| 2 | React 18 → 19.3.0 runtime bump (`react`/`react-dom`/`@types/react`/`@types/react-dom`) | [x] Done — see `docs/decisions.md`'s "React 19/ESLint 10 upgrade plan, Phase 2" entry |
| 3 | ESLint 10 + `eslint-plugin-react-hooks` 7.1.1 migration | [x] Done, but not as originally scoped — see "Phase 3, revised" below and `docs/decisions.md`'s "React 19/ESLint 10 upgrade plan, Phase 3" entry. The planned `useEffectEvent`-per-site fix for `react-hooks/set-state-in-effect` turned out not to work; the rule was downgraded to `warn` with a documented rationale instead, repo-wide, in one step (no batch A/B split needed). Verification also surfaced and root-caused 3 flaky Playwright specs plus a real request-ordering race in `ProjectAdminPage.tsx`'s groups search, all fixed — see that decisions.md entry's "Verification surfaced 3 flaky Playwright specs" section for the full account. |
| 4 | `react-hooks/refs` investigation (8 findings, `ProjectAdminPage.tsx`) | [x] Done — all 8 confirmed false positives (same root cause: `reload()`'s anti-race ref touched transitively from 8 JSX event-handler props). No non-evasive fix exists at current dependency versions — the one upstream fix (facebook/react#35062) isn't shipped in any published `eslint-plugin-react-hooks` build and wouldn't cover all 8 sites anyway. Silenced with per-line, documented `eslint-disable-next-line` comments. `npm run lint` now 0 errors repo-wide (68 `set-state-in-effect` warnings remain, expected). See `docs/decisions.md`'s "React 19/ESLint 10 upgrade plan, Phase 4" entry, which also fixed `stage-review-and-completion.spec.ts`'s previously-open 30s timeout margin (found during this phase's own verification, root-caused with a real trace, unrelated to the refs change itself). |
| 5 | Final sweep and close-out | [ ] Not started |

**Outside this plan, same session:** `project-hierarchy.spec.ts`'s "doesn't clean up its own throwaway projects" gap (flagged as a follow-up above) was fixed directly at the user's request, along with root-causing a real CI failure (a missing `ORDER BY` in `list_organizations`, plus an identical shared-persona-grant leak in `project-list-org-scoping.spec.ts`) — see `docs/decisions.md`'s "`project-hierarchy.spec.ts` cleanup gap, and root-causing a real CI failure" entry. That entry also found and partially fixed a real `ProjectAdminPage.tsx` performance issue (`reload()`'s ~12 independent fetches ran serially, now parallelized) — kept as a genuine improvement, but it did **not** fully resolve `stage-review-and-completion.spec.ts`'s own persistent near-30s-timeout margin under CI-style retries, which remains an **open** item for whoever next touches Project Admin/that spec: profile its actual per-step timing (a trace, not a guess) rather than assume it's fixed.

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

**Correction found during Phase 3 (see that phase's section below for the full account): the `useEffectEvent`-fixes-`set-state-in-effect` premise above is wrong.** `useEffectEvent` only removes a function from the reactive dependency array (the `exhaustive-deps` concern); the rule that actually blocked the original 2026-09-14 migration attempt is a separate, React-Compiler-derived static check that traces whether a state setter is reachable from a function invoked in an effect, and it explicitly propagates that "contains setState" flag *through* a `useEffectEvent` wrapper rather than clearing it. This was verified empirically (wrapping a real call site and re-linting still errored, at the new location) and by reading the installed rule's own source. It is also a known, open, upstream issue — the exact pattern this app uses (and React's own documentation's canonical fetch-in-effect example) is misflagged; see `facebook/react` issues #34905, #34743, #34858 and the still-open, unmerged fix at #36734. Phase 3 downgraded the rule to `warn` with that rationale recorded in `eslint.config.js` instead of restructuring ~68 call sites around an unresolved upstream bug.

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

## Phase 3 — ESLint 10 + `eslint-plugin-react-hooks` 7.1.1 migration [DONE, revised from original scope below]

### As originally planned (superseded — kept for the record)

Scope: everywhere **outside** `src/modules/compliance/` — `src/pages/*`, `src/components/*`, `src/context/*`, `src/hooks/*`. ~27 files, ~34 `set-state-in-effect` sites (`ProjectAdminPage.tsx`'s 2 `set-state-in-effect` sites in scope here; its 8 `refs` findings deferred to Phase 4). The plan was: bump the three packages, then for each flagged site wrap the setState-touching logic in `useEffectEvent` and call that from the effect instead.

### What actually happened

The versions bumped exactly as planned: `eslint` → `^10.10.0`, `@eslint/js` → `^10.0.1`, `eslint-plugin-react-hooks` → `^7.1.1` (`frontend/package.json`, `sync-lockfile.sh`). Re-linting reproduced the same 76 errors documented in "Research already done" above (68 `set-state-in-effect`, 8 `refs`).

The `useEffectEvent`-per-site fix was tried on the simplest real site (`ProjectHistoryPage.tsx`) **before** rolling it out across the batch, and it did not work: wrapping `reload()`'s effect-body call in a `useEffectEvent`-created callback and calling that from the effect still errored — same rule, same file, just pointing at the new call site (`onFiltersChange();` instead of `reload();`).

Reading the installed rule's own source (`eslint-plugin-react-hooks/cjs/eslint-plugin-react-hooks.development.js`, `validateNoSetStateInEffects`/`getSetStateCall`) explained why: `react-hooks/set-state-in-effect` and `react-hooks/exhaustive-deps` solve different problems. `useEffectEvent` only takes a callback out of the *reactive dependency* graph (what `exhaustive-deps` cares about about stale closures) — it does not make a function's "contains a setState call" status disappear. The rule's own `isUseEffectEventType` branch explicitly *propagates* that status through the wrapper (`setStateFunctions.set(<the useEffectEvent result>, <the underlying setState>)`) rather than clearing it, so calling the wrapped event from inside a `useEffect` still trips the same check one level further out. The rule instead does a purely static, one-hop trace: does the function passed to `useEffect` (or a named function it calls, if that named function's own top-level body directly calls a setter) contain a literal call to a state setter? An `async function reload() { setX(null); await fetch(...); setY(data); }` pattern — this app's standard data-fetch-on-dependency-change shape, and also **React's own documented canonical pattern** for fetching data in an effect (react.dev, "Synchronizing with Effects") — matches that trace regardless of the `await` in between, because the rule doesn't special-case control flow after an `await`; it only cares whether the call is a direct top-level statement in the invoked function's own body.

Confirmed via web search that this is a known, currently-open, unresolved issue in React's own compiler team, not a misreading of the rule or something specific to this codebase:
- [facebook/react#34905](https://github.com/facebook/react/issues/34905) — `set-state-in-effect` false-positives on `setState` called after an `await`. Status: Unconfirmed. Fix PR [#36734](https://github.com/facebook/react/pull/36734) exists but is still open, unmerged.
- [facebook/react#34743](https://github.com/facebook/react/issues/34743) — the rule flagging common valid patterns straight from React's own docs, Next.js's docs, and libraries like MUI Joy UI; the reporter calls the available workarounds (`.then()`-nesting the setState call one level deeper so it falls outside the rule's one-hop trace, `setTimeout`, `startTransition`) "code smell or 'tricking the lint rule'" rather than a real fix.
- [facebook/react#34858](https://github.com/facebook/react/issues/34858) — same false positive against a fetch pattern lifted directly from React's own documentation.

Given there is no available fix that isn't either (a) an unresolved upstream compiler limitation or (b) deliberately shaping code to dodge a static trace with no genuine behavioral improvement — and given restructuring ~68 real call sites around a bug the React team itself hasn't resolved risks needing to be reverted once it lands — presented this to the user rather than picking a workaround unilaterally. **Decided by: User**, choosing (after a first pass of "pause and research further" to confirm the false-positive finding via GitHub before committing) to downgrade `react-hooks/set-state-in-effect` from `error` to `warn` in `frontend/eslint.config.js`, with the full rationale and the three issue links above recorded as a comment directly on the rule, rather than restructuring the call sites or leaving `npm run lint` red. This resolves all 68 `set-state-in-effect` findings **repo-wide in one step** (including the ~34 sites originally planned for a separate Phase 4 "batch B" in the compliance module) — no per-site code change was needed once the severity was corrected, and no batch split was necessary.

**Changes actually made:**
- `frontend/package.json`/`package-lock.json`: `eslint` → `^10.10.0`, `@eslint/js` → `^10.0.1`, `eslint-plugin-react-hooks` → `^7.1.1`.
- `frontend/eslint.config.js`: `"react-hooks/set-state-in-effect": "warn"` added to the `rules` block, with the rationale/issue-links comment described above.
- No application code changed in this phase — the `useEffectEvent` test edit on `ProjectHistoryPage.tsx` was reverted once it was shown not to work.

**Verification:**
- `npm run lint`: exits with **8 errors, 68 warnings** — the 8 errors are exactly the `react-hooks/refs` findings in `ProjectAdminPage.tsx`, already scoped to Phase 4 below; the 68 warnings are the now-downgraded `set-state-in-effect` findings, expected and accepted per the decision above.
- `npm run build`: clean (pre-existing `[INEFFECTIVE_DYNAMIC_IMPORT]`/chunk-size notices from Phase 1's Rolldown adoption reappear, unrelated to this phase — see that phase's decisions.md entry).
- `npm run test-storybook -- --coverage`: 115/115 test files, 936/936 tests passed.
- Full Playwright suite, containers rebuilt+recreated first — see `docs/decisions.md`'s Phase 3 entry for the actual result.

---

## Phase 4 — the `react-hooks/refs` investigation [DONE] (only remaining lint-error work)

Scope: the 8 `react-hooks/refs` findings in `ProjectAdminPage.tsx`. (The compliance-module `set-state-in-effect` batch originally planned for this phase no longer applies — Phase 3's rule downgrade resolved it repo-wide already.)

### What actually happened

All 8 findings are the same false positive, one root cause: every flagged site is a JSX callback prop (`onToggle`, 6× `onClick`, `onSelect`/`onSelectExternal`) for a handler that calls `reload()`, which touches four `useRef`s synchronously (including `loadGroupsRequestIdRef`, Phase 3's own anti-race guard) — the compiler's `readRefEffect` propagation flags passing any such handler as a JSX prop, even though these only ever run from event handling, never during render.

Per the user's explicit request, investigated upstream before accepting a disable rather than assuming a from-scratch investigation was needed: `facebook/react#35062` ("Allow ref access in callbacks passed to event handler props"), merged 2025-11-14 and cited in `eslint-plugin-react-hooks` 7.1.0's own changelog, implements exactly this exemption — but only for built-in DOM `on*` props, gated behind a compiler flag (`enableInferEventHandlers`, default `false`) confirmed **entirely absent** from every published `eslint-plugin-react-hooks` build checked, including the installed 7.1.1 and the newest canary (`7.1.1-canary-f1f7ed2a-20260904`). The changelog describes a capability that hasn't reached the npm package. Even once it does, it would only cover 6 of the 8 sites (the native `<button onClick>` ones) — the PR's own test fixtures keep custom-component props (`UserAutocomplete`'s `onSelect`/`onSelectExternal`, `MultiSelectDropdown`'s `onToggle`) as errors by design.

Also ruled out: `useEffectEvent` (no reference to it anywhere in the refs-validation code path), the `"use no memo"` per-function opt-out directive (verified empirically — added it to one function, still 8/8 errors; it only skips the babel-transform step, not the ESLint-facing event log), and swapping `useRef` for a same-shaped `useState(() => ({current: 0}))[0]` box (would evade the compiler's type detection, but is the same footgun with the "ref" label removed — worse than a documented disable, not better).

**Decided by: User** — presented all of the above and chose per-line `eslint-disable-next-line react-hooks/refs` comments with inline rationale, once no non-evasive route was confirmed to exist. Full account, including the trace-based fix also applied to `stage-review-and-completion.spec.ts`'s previously-open 30s timeout margin (found during this phase's own verification, unrelated to the refs change, comment-only diff), in `docs/decisions.md`'s "React 19/ESLint 10 upgrade plan, Phase 4" entry.

**Verification:** `npm run lint` 0 errors (68 `set-state-in-effect` warnings, expected), `npm run build` clean, `npm run test-storybook -- --coverage` 115/115 files, and a full Playwright suite verification that took three attempts to get a clean read (a forgotten reseed after a stack wipe, then accumulated shared-fixture pollution from several repeated runs in one session, then a genuinely clean `down -v`+reseed+run) — full detail, including why the remaining transient failures are unrelated to this phase, in that decisions.md entry.

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
