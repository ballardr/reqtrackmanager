/**
 * Module: modules/entityAccentColor
 *
 * Generic resolver for the entity-accent-colour pattern (`.entity-accent-card` / `.entity-accent-row`,
 * `styles/theme.css`): the left-border stripe that tells entity kinds apart in a list mixing several (for example the
 * Links card of `pages/RequirementDetailPage.tsx`).
 *
 * Two merged sources:
 * - A fixed map for the core entity kinds (`requirement`, `action`, `change_request`), which have no
 *   `TierAModuleDefinition`; they stay in `api/types.ts`'s `ENTITY_ACCENT_COLOR` as CSS-variable-backed constants.
 * - Every installed module's own `entityAccentColor` (`modules/types.ts`) keyed by its `key`, a literal
 *   `{ light, dark }` hex pair resolved client-side through `useTheme()`; `modules/compliance/module.ts` is the
 *   reference.
 *
 * No module's colour lives in a core file: a per-module entry in a closed core map or a `--color-entity-*` variable in
 * a core stylesheet is the boundary violation CLAUDE.md's "Modular Feature System Boundary" describes.
 */
import { useMemo } from "react";

import { ENTITY_ACCENT_COLOR, type EntityAccentKind } from "../api/types";
import { resolveEffectiveTheme, useTheme } from "../context/ThemeContext";
import { getInstalledModule } from "./registry";

/** The neutral fallback for a kind with no registered colour (a module that sets no `entityAccentColor`, or an unknown
 * kind): the grey `--color-text-muted` resolves to in each theme, so an unstyled row reads as "no accent". */
const FALLBACK_COLOR: { light: string; dark: string } = { light: "#6b7280", dark: "#9aa4b2" };

const CORE_ENTITY_KINDS = new Set<string>(Object.keys(ENTITY_ACCENT_COLOR));

/** Resolves `kind`'s accent colour for `effectiveTheme` ("light" or "dark", not the raw `"system"` preference).
 * `kind` is a core entity kind (`"requirement"`, `"action"`, `"change_request"`) or an installed module's `key`
 * (unique by `ModuleDefinition.key`). A core kind returns `ENTITY_ACCENT_COLOR`'s `var(--color-entity-*)` reference,
 * which `theme.css` already switches per theme; a module's colour is a literal hex pair, so `effectiveTheme` selects
 * between them. Both are valid CSS colour values, so callers need not tell them apart. */
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
