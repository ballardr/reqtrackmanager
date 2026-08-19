/**
 * Module: i18n/terminology
 *
 * Pure logic (no React) behind C-C-03's per-project terminology overrides:
 * the fixed set of overridable terms, pluralisation, and the `{token}`
 * substitution mechanism that makes `strings.ts` itself terminology-aware.
 * Split out of `TerminologyContext.tsx` the same way `ProjectContextValue.ts`
 * was — so that file keeps exporting only the provider and hooks React's
 * Fast Refresh expects, and this file stays trivially unit-testable without
 * a React tree.
 *
 * Any `en` string in `strings.ts` (or the fixed template part of a
 * function-valued entry there) may embed a token — `{requirement}`,
 * `{Requirements}`, `{changeRequest}`, etc. — from `TOKEN_MAP` below.
 * `useStrings()` (in `TerminologyContext.tsx`) is the terminology-aware
 * replacement for calling `t()` directly: it walks the whole string table
 * and substitutes every token for the current project's resolved term (or
 * its English default outside a project, or where no override is set).
 * Plain `t()` is still correct for any string with no token in it.
 */

export type TerminologyKey = "project" | "stage" | "component" | "category" | "requirement" | "change_request";

// Lower case: these are substituted mid-phrase ("New requirement") as often
// as they're used standalone (a nav label, a page heading) — `useTerm`
// returns the raw lower-case form for the former; `useTermPlural`/token
// substitution capitalise on request (see `TOKEN_MAP`).
export const DEFAULT_TERMS: Record<TerminologyKey, string> = {
  project: "project",
  stage: "stage",
  component: "component",
  category: "category",
  requirement: "requirement",
  change_request: "change request",
};

function capitalize(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

/**
 * Pluralises a resolved term. Handles the one irregular default term
 * (category -> categories, not "categorys"); every other default is a
 * regular noun. A project overriding a term with a different irregular
 * plural (e.g. "Story"/"Stories") still needs to type the plural form
 * directly as its override to read correctly — this covers the built-in
 * defaults and regular-noun overrides only.
 */
export function pluralize(word: string): string {
  if (/[^aeiou]y$/i.test(word)) return `${word.slice(0, -1)}ies`;
  return `${word}s`;
}

interface TokenSpec {
  key: TerminologyKey;
  plural: boolean;
  capitalize: boolean;
}

/** Every recognised `{token}` name a string in `strings.ts` may embed. */
const TOKEN_MAP: Record<string, TokenSpec> = {
  project: { key: "project", plural: false, capitalize: false },
  Project: { key: "project", plural: false, capitalize: true },
  projects: { key: "project", plural: true, capitalize: false },
  Projects: { key: "project", plural: true, capitalize: true },
  stage: { key: "stage", plural: false, capitalize: false },
  Stage: { key: "stage", plural: false, capitalize: true },
  stages: { key: "stage", plural: true, capitalize: false },
  Stages: { key: "stage", plural: true, capitalize: true },
  component: { key: "component", plural: false, capitalize: false },
  Component: { key: "component", plural: false, capitalize: true },
  components: { key: "component", plural: true, capitalize: false },
  Components: { key: "component", plural: true, capitalize: true },
  category: { key: "category", plural: false, capitalize: false },
  Category: { key: "category", plural: false, capitalize: true },
  categories: { key: "category", plural: true, capitalize: false },
  Categories: { key: "category", plural: true, capitalize: true },
  requirement: { key: "requirement", plural: false, capitalize: false },
  Requirement: { key: "requirement", plural: false, capitalize: true },
  requirements: { key: "requirement", plural: true, capitalize: false },
  Requirements: { key: "requirement", plural: true, capitalize: true },
  changeRequest: { key: "change_request", plural: false, capitalize: false },
  ChangeRequest: { key: "change_request", plural: false, capitalize: true },
  changeRequests: { key: "change_request", plural: true, capitalize: false },
  ChangeRequests: { key: "change_request", plural: true, capitalize: true },
};

function resolveToken(spec: TokenSpec, terminology: Record<string, string>): string {
  const base = terminology[spec.key] || DEFAULT_TERMS[spec.key];
  const word = spec.plural ? pluralize(base) : base;
  return spec.capitalize ? capitalize(word) : word;
}

/**
 * Substitutes every recognised `{token}` in `value` for the project's
 * resolved terminology. Tokens not in `TOKEN_MAP` (the existing
 * `{org}`/`{name}`/`{email}`/etc. call-site placeholders used throughout
 * `strings.ts`, substituted manually via `.replace()` at each call site)
 * are left untouched — this only ever recognises the fixed terminology
 * token set, so it composes safely with that existing convention.
 */
export function applyTerminology(value: string, terminology: Record<string, string>): string {
  if (!value.includes("{")) return value;
  return value.replace(/\{([a-zA-Z]+)\}/g, (match, token: string) => {
    const spec = TOKEN_MAP[token];
    return spec ? resolveToken(spec, terminology) : match;
  });
}

/**
 * Deep-walks a string table (see `Strings` in `strings.ts`), applying
 * `applyTerminology` to every string leaf and to the return value of every
 * function leaf. Function-valued entries (e.g. `notProvisioned: (org) =>
 * ...`) keep taking their own params unchanged — only what they return is
 * substituted, so an existing `{org}`/`{name}` param placeholder embedded
 * in a template literal's fixed text still resolves the same way it always
 * has, via the caller's own `.replace()` or template interpolation.
 */
export function resolveTerminologyDeep<T>(node: T, terminology: Record<string, string>): T {
  if (typeof node === "string") return applyTerminology(node, terminology) as unknown as T;
  if (typeof node === "function") {
    const fn = node as (...args: unknown[]) => unknown;
    const wrapped = (...args: unknown[]) => {
      const result = fn(...args);
      return typeof result === "string" ? applyTerminology(result, terminology) : result;
    };
    return wrapped as unknown as T;
  }
  if (node && typeof node === "object") {
    const out = {} as T;
    for (const k of Object.keys(node) as (keyof T)[]) {
      out[k] = resolveTerminologyDeep(node[k], terminology);
    }
    return out;
  }
  return node;
}
