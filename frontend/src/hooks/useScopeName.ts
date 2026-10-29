/**
 * Module: hooks/useScopeName
 *
 * The display name of the project or organisation a dialog acts for, so it can say which one the person is
 * about to download for.
 *
 * Responsibilities:
 * - Fetch the name once per scope (cached for the session) and return `null` until it is known or if it cannot be read.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";

const names = new Map<string, Promise<string | null>>();

/**
 * @param kind Whether `id` is a project or an organisation.
 * @param id The project's or organisation's id; `undefined` yields `null`.
 * @returns The name, or `null` while loading, when it cannot be read, or when `id` is missing.
 */
export function useScopeName(kind: "project" | "organization", id: string | undefined): string | null {
  const [fetched, setFetched] = useState<{ key: string; name: string | null } | null>(null);
  const key = id ? `${kind}:${id}` : "";
  useEffect(() => {
    if (!id) return;
    let active = true;
    let pending = names.get(key);
    if (!pending) {
      const path = kind === "project" ? `/api/v1/projects/${id}` : `/api/v1/orgs/${id}`;
      pending = api.get<{ name: string }>(path).then((found) => found.name || null).catch(() => {
        names.delete(key);
        return null;
      });
      names.set(key, pending);
    }
    void pending.then((name) => {
      if (active) setFetched({ key, name });
    });
    return () => {
      active = false;
    };
  }, [kind, id, key]);
  return fetched?.key === key ? fetched.name : null;
}
