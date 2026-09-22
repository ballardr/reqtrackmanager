/**
 * Module: modules/entityAccentColor
 *
 * Generic resolver for the entity-accent-colour pattern (`.entity-accent-
 * card`/`.entity-accent-row`, `styles/theme.css`) — the left-border stripe
 * a list row showing a specific entity kind renders with, so a user
 * scanning a list that mixes several entity kinds (e.g. `pages/
 * RequirementDetailPage.tsx`'s own Links card, which shows both core
 * requirement-to-requirement links and a module's own link kinds side by
 * side) can tell them apart at a glance.
 *
 * Two sources, merged:
 * - A small fixed map for the entity kinds core itself owns (`requirement`,
 *   `action`, `change_request`) — these aren't any module's concern and
 *   have no `TierAModuleDefinition` to read a colour from.
 * - Every installed module's own `entityAccentColor` (`modules/types.ts`),
 *   keyed by that module's own `key` — `modules/compliance/module.ts`'s
 *   own entry is the reference example.
 *
 * **Why this file exists**: `frontend/src/api/types.ts`'s `ENTITY_ACCENT_
 * COLOR`/`EntityAccentKind` used to be the single source for this, a fixed
 * `Record` in a core file with one entry per entity kind including
 * `"compliance"` — a per-module value hand-added to a core, closed-set map,
 * the exact same failure mode CLAUDE.md's "Modular Feature System Boundary"
 * section already documents for `ProjectSequenceCounter.artefact_type`
 * (Module 4 Phase 1), just applied to a display colour instead of an artefact-
 * type string. A second instance of the identical mistake (an attempted
 * `"decision"` entry) was caught and reverted before landing — see this
 * repo's own memory/decisions log — which is what prompted pulling this
 * mechanism out to a real, module-registrable one instead of adding a third
 * hardcoded entry. `theme.css`'s `--color-entity-*` variables for `compliance`
 * (and the attempted `decision`) are gone with it — a module's colour now
 * lives as a literal `{ light, dark }` hex pair on its own `module.ts`
 * (`TierAModuleDefinition.entityAccentColor`), not a CSS custom property
 * declared in a core stylesheet, resolved client-side via `useTheme()`
 * instead of a `:root[data-theme="dark"]` override. `requirement`/`action`/
 * `change_request` stay in `api/types.ts`'s own `ENTITY_ACCENT_COLOR` as
 * CSS-variable-backed core constants — those three are genuinely core-owned
 * entity kinds with no module to register them from, so keeping them as
 * plain CSS variables (simpler, no JS theme-branching needed) is correct,
 * not a shortcut back to the same mistake; the boundary this file exists to
 * enforce is specifically "no *module's* colour lives in a core file."
 */
import { useMemo } from "react";

import { ENTITY_ACCENT_COLOR, type EntityAccentKind } from "../api/types";
import { resolveEffectiveTheme, useTheme } from "../context/ThemeContext";
import { getInstalledModule } from "./registry";

/** The neutral fallback for an entity kind with no registered colour of its
 * own (a module that never set `entityAccentColor`, or a kind string that
 * matches no core kind and no installed module's `key`) — the same grey
 * `--color-text-muted` already resolves to in each theme, so an unstyled
 * row still reads as "no accent," not as a visibly broken/missing colour. */
const FALLBACK_COLOR: { light: string; dark: string } = { light: "#6b7280", dark: "#9aa4b2" };

const CORE_ENTITY_KINDS = new Set<string>(Object.keys(ENTITY_ACCENT_COLOR));

/** Resolves `kind`'s accent colour for `effectiveTheme` ("light"/"dark", not
 * the raw `"system"` preference — callers pass `resolveEffectiveTheme(theme)`,
 * same as `useEntityAccentColor` below does). `kind` is a core entity kind
 * (`"requirement"`/`"action"`/`"change_request"`) or an installed module's
 * own `key` (e.g. `"compliance"`) — there's no separate registry to
 * distinguish the two, since a module's `key` is already namespaced by the
 * module system itself (`ModuleDefinition.key` must be unique).
 *
 * A core kind's value is `ENTITY_ACCENT_COLOR`'s own `var(--color-entity-*)`
 * reference, not a literal hex — `theme.css`'s existing `:root[data-theme=
 * "dark"]` override already handles that case, so `effectiveTheme` is only
 * actually branched on for a module-contributed colour (a literal hex pair,
 * no CSS variable). Both forms are valid CSS colour values wherever this
 * result is used (`style={{ ["--entity-accent-color"]: ... }}`), so callers
 * don't need to know which kind of value they got back. */
export function getEntityAccentColor(kind: string, effectiveTheme: "light" | "dark"): string {
  if (CORE_ENTITY_KINDS.has(kind)) return ENTITY_ACCENT_COLOR[kind as EntityAccentKind];
  const module = getInstalledModule(kind);
  if (module?.entityAccentColor) return module.entityAccentColor[effectiveTheme];
  return FALLBACK_COLOR[effectiveTheme];
}

/** React hook form of `getEntityAccentColor`, resolving the caller's own
 * current effective theme via `useTheme()` — the usual way a component
 * consumes this (`style={{ ["--entity-accent-color"]: useEntityAccentColor
 * ("compliance") }}`). */
export function useEntityAccentColor(kind: string): string {
  const { theme } = useTheme();
  const effectiveTheme = resolveEffectiveTheme(theme);
  return useMemo(() => getEntityAccentColor(kind, effectiveTheme), [kind, effectiveTheme]);
}
