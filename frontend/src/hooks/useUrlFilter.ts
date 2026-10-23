/**
 * Module: hooks/useUrlFilter
 *
 * A list's filters, sort and search kept in the URL's query string instead of component state, with the
 * same `[value, setter]` shape as `useState`. This is what lets a list come back as it was left after a
 * trip to a record (the browser's Back restores the URL, so the filters follow) and lets a filtered list
 * be bookmarked or shared; `useListPosition` keys the saved scroll position by that URL.
 *
 * Responsibilities:
 * - `useUrlText` / `useUrlFlag` / `useUrlChoice` / `useUrlList` / `useUrlSort`: one query parameter each.
 * - Writes replace the history entry (a filter change is not a page the Back button should step through)
 *   and keep every other parameter.
 *
 * Design decisions:
 * - A parameter at its default is absent from the URL, so a plain link to the list stays short and a value
 *   a deep link names (`?status=draft`) is just the same parameter set by hand.
 * - The router applies a URL change after the event that caused it, so each hook also shows the value it was
 *   just given until the URL catches up; otherwise a controlled input would flip back for a render (a caret
 *   that jumps in a search box, a checkbox that seems not to have changed).
 * - Setters called in the same tick (a "clear filters" handler) accumulate: React Router's own functional
 *   update would apply each to the same stale parameters and keep only the last.
 * - A page-local concern that is not a filter (a dialog being open, a selection) stays in `useState`.
 */
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { SortState } from "../components/sortState";

type SetParams = ReturnType<typeof useSearchParams>[1];

/** Parameters written earlier in the current tick, so several setters in one handler all take effect. */
let pending: URLSearchParams | null = null;

/** Applies `mutate` on top of whatever was already written this tick, then replaces the URL's query. */
function write(current: URLSearchParams, setParams: SetParams, mutate: (params: URLSearchParams) => void): void {
  if (!pending) {
    pending = new URLSearchParams(current);
    queueMicrotask(() => {
      pending = null;
    });
  }
  mutate(pending);
  setParams(new URLSearchParams(pending), { replace: true });
}

/** A setter takes the next value or, like `useState`'s, a function of the current one. */
export type UrlSetter<T> = (next: T | ((current: T) => T)) => void;

function resolve<T>(next: T | ((current: T) => T), current: T): T {
  return typeof next === "function" ? (next as (current: T) => T)(current) : next;
}

/**
 * The value a hook shows: the URL's, except right after a set, until the URL has changed to match.
 *
 * @param fromUrl The value the URL currently holds.
 * @param key A string that changes exactly when `fromUrl` does.
 * @returns The value to show and a function that records a value just set.
 */
function useJustSet<T>(fromUrl: T, key: string): [T, (value: T) => void] {
  const [justSet, setJustSet] = useState<{ value: T; base: string } | null>(null);
  // The URL has moved on (our write landed, or the person navigated): forget the override.
  if (justSet && justSet.base !== key) setJustSet(null);
  return [justSet && justSet.base === key ? justSet.value : fromUrl, (value) => setJustSet({ value, base: key })];
}

/**
 * A free-text parameter (a search box).
 *
 * @param name The query parameter.
 * @param inUrl False keeps the text in component state instead, for a list that is also embedded in a page
 *   whose own query parameters it must not touch (a list inside an admin tab); fixed for the component's life.
 * @returns The current text (`""` when absent) and its setter; `""` removes the parameter.
 */
export function useUrlText(name: string, inUrl = true): [string, UrlSetter<string>] {
  const [params, setParams] = useSearchParams();
  const [local, setLocal] = useState("");
  const fromUrl = params.get(name) ?? "";
  const [value, remember] = useJustSet(fromUrl, fromUrl);
  if (!inUrl) return [local, setLocal];
  const set: UrlSetter<string> = (next) => {
    let text = "";
    write(params, setParams, (p) => {
      text = resolve(next, p.get(name) ?? "");
      if (text) p.set(name, text);
      else p.delete(name);
    });
    remember(text);
  };
  return [value, set];
}

/**
 * A boolean parameter, `1` / `0`.
 *
 * @param name The query parameter.
 * @param defaultValue The value when the parameter is absent; setting it back to the default removes the parameter.
 * @param options `explicit`: always keep the value in the URL (written on mount when absent), for a default the
 *   page works out from how it was opened and must not re-derive after the person has changed other filters.
 * @returns The current value and its setter.
 */
export function useUrlFlag(name: string, defaultValue = false, options: { explicit?: boolean } = {}): [boolean, UrlSetter<boolean>] {
  const { explicit = false } = options;
  const [params, setParams] = useSearchParams();
  const raw = params.get(name);
  const fromUrl = raw === "1" ? true : raw === "0" ? false : defaultValue;
  const [value, remember] = useJustSet(fromUrl, String(raw));
  const set: UrlSetter<boolean> = (next) => {
    let flag = defaultValue;
    write(params, setParams, (p) => {
      const rawNow = p.get(name);
      const current = rawNow === "1" ? true : rawNow === "0" ? false : defaultValue;
      flag = resolve(next, current);
      if (flag === defaultValue && !explicit) p.delete(name);
      else p.set(name, flag ? "1" : "0");
    });
    remember(flag);
  };
  const missing = explicit && raw === null;
  useEffect(() => {
    if (missing) write(params, setParams, (p) => p.set(name, defaultValue ? "1" : "0"));
  }, [missing, params, setParams, name, defaultValue]);
  return [value, set];
}

/**
 * A parameter restricted to known values (a status or priority filter).
 *
 * @param name The query parameter.
 * @param allowed The accepted values; anything else in the URL reads as no filter.
 * @returns The chosen value (`""` for none) and its setter.
 */
export function useUrlChoice<T extends string>(name: string, allowed: readonly T[]): [T | "", UrlSetter<T | "">] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(name);
  const fromUrl = allowed.includes(raw as T) ? (raw as T) : "";
  const [value, remember] = useJustSet<T | "">(fromUrl, fromUrl);
  const set: UrlSetter<T | ""> = (next) => {
    let chosen: T | "" = "";
    write(params, setParams, (p) => {
      const rawNow = p.get(name);
      const current = allowed.includes(rawNow as T) ? (rawNow as T) : "";
      chosen = resolve(next, current);
      if (chosen) p.set(name, chosen);
      else p.delete(name);
    });
    remember(chosen);
  };
  return [value, set];
}

/**
 * A repeated parameter (`tag=a&tag=b`).
 *
 * @param name The query parameter.
 * @returns The values in URL order and a setter; an empty list removes the parameter.
 */
export function useUrlList(name: string): [string[], UrlSetter<string[]>] {
  const [params, setParams] = useSearchParams();
  const key = JSON.stringify(params.getAll(name));
  // The same array while the list is unchanged: pages use it as an effect dependency.
  const fromUrl = useMemo<string[]>(() => JSON.parse(key) as string[], [key]);
  const [value, remember] = useJustSet(fromUrl, key);
  const set: UrlSetter<string[]> = (next) => {
    let chosen: string[] = [];
    write(params, setParams, (p) => {
      chosen = resolve(next, p.getAll(name));
      p.delete(name);
      for (const item of chosen) p.append(name, item);
    });
    remember(chosen);
  };
  return [value, set];
}

function readSort<K extends string>(params: URLSearchParams, keys: readonly K[]): SortState<K> | null {
  const key = params.get("sort");
  if (!keys.includes(key as K)) return null;
  return { key: key as K, direction: params.get("order") === "desc" ? "desc" : "asc" };
}

/**
 * A table's sort, as `sort=<key>&order=asc|desc`.
 *
 * @param keys The sortable column keys; any other `sort` in the URL reads as unsorted.
 * @returns The sort (or `null`) and its setter.
 */
export function useUrlSort<K extends string>(keys: readonly K[]): [SortState<K> | null, UrlSetter<SortState<K> | null>] {
  const [params, setParams] = useSearchParams();
  const read = readSort(params, keys);
  const readKey = read?.key ?? null;
  const readDirection = read?.direction ?? null;
  const key = `${readKey}:${readDirection}`;
  // A stable object while the sort is unchanged, so it can be a memo or effect dependency.
  const fromUrl = useMemo<SortState<K> | null>(
    () => (readKey !== null && readDirection !== null ? { key: readKey, direction: readDirection } : null),
    [readKey, readDirection],
  );
  const [value, remember] = useJustSet(fromUrl, key);
  const set: UrlSetter<SortState<K> | null> = (next) => {
    let chosen: SortState<K> | null = null;
    write(params, setParams, (p) => {
      chosen = resolve(next, readSort(p, keys));
      if (chosen) {
        p.set("sort", chosen.key);
        p.set("order", chosen.direction);
      } else {
        p.delete("sort");
        p.delete("order");
      }
    });
    remember(chosen);
  };
  return [value, set];
}
