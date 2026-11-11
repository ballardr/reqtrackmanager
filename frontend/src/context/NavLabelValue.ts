/**
 * Module: context/NavLabelValue
 *
 * The navigation-name context object and the hooks that read it, kept apart from the provider component
 * (`NavLabelContext.tsx`) so that file exports only a component. Names are keyed by the route each
 * navigation entry opens (see the provider for why).
 */
import { createContext, useCallback, useContext } from "react";
import { useLocation } from "react-router-dom";

/** The names that apply, by normalised route path. */
export type NamesByPath = Record<string, string>;

/** Context value: empty outside a provider, so a component rendered alone shows built-in names. */
export const NavLabelValue = createContext<NamesByPath>({});

/** Subscribers of `refreshNavLabels`, one per mounted provider. */
const refreshListeners = new Set<(projectId: string) => void>();

/**
 * Registers a provider's refresh callback.
 *
 * @param listener Called with the id of the project whose names changed.
 * @returns A function that removes the listener.
 */
export function onNavLabelsRefresh(listener: (projectId: string) => void): () => void {
  refreshListeners.add(listener);
  return () => { refreshListeners.delete(listener); };
}

/**
 * Tells every mounted provider for `projectId` to re-read its names. Call it after the names changed.
 *
 * @param projectId The project whose navigation names changed.
 */
export function refreshNavLabels(projectId: string): void {
  refreshListeners.forEach((listener) => listener(projectId));
}

/** The route without its query, fragment and trailing slash, so a link and a location compare equal. */
export function normaliseNavPath(path: string): string {
  const bare = path.split(/[?#]/, 1)[0] ?? "";
  return bare.length > 1 ? bare.replace(/\/+$/, "") : bare;
}

/**
 * The name given to the navigation entry that opens `path`, or undefined when it has none (or `path` is not an entry).
 *
 * @param path A route, possibly with a query string.
 */
export function useNavLabelOverride(path: string | undefined): string | undefined {
  const names = useContext(NavLabelValue);
  return path === undefined ? undefined : names[normaliseNavPath(path)];
}

/** The override for the page being shown: use it for a page title, falling back to the built-in title. */
export function useCurrentNavLabelOverride(): string | undefined {
  return useNavLabelOverride(useLocation().pathname);
}

/**
 * A function that names an entry by its route, for code that builds several entries in a loop (the navigation rail).
 *
 * @returns `(path, builtIn) => name`: the override for `path`, else `builtIn`.
 */
export function useNavLabeler(): (path: string, builtIn: string) => string {
  const names = useContext(NavLabelValue);
  return useCallback((path, builtIn) => names[normaliseNavPath(path)] ?? builtIn, [names]);
}
