/**
 * Module: context/FavouritesContext
 *
 * Tracks whether the current user has any active favourited project, for
 * `Layout.tsx`'s nav-rail "Favourites" entry (`hasFavourites`). Previously
 * this lived as local state in `LayoutShell`, recomputed only on mount and
 * again on landing at `/projects` or `/favourites` — "the only two places
 * a favourite can be toggled" at the time the comment was written. That's
 * no longer true generally (any future favourite-star elsewhere would go
 * stale) and was already a real gap for a session that never revisits
 * either route after the first toggle. See docs/ux-audit-2026-08.md
 * "Favourites: no filter, nav-rail lag, no view toggle" and
 * docs/ux-style-guide.md's "Pattern: role display" sibling section for
 * the general shape of this kind of fix.
 *
 * `FavouritesProvider` wraps the app inside `Layout` (alongside
 * `TerminologyProvider`/`BrandingProvider`) so both the nav rail and every
 * page rendered as `children` share the same `hasFavourites` value. Any
 * component that toggles a project's favourite status calls
 * `refreshFavourites()` (via `useFavourites()`) immediately after the
 * mutating API call succeeds — `ProjectListPage.tsx` and
 * `FavouritesPage.tsx` today — so the rail updates the moment a toggle
 * happens anywhere, without adding more special-cased routes to a
 * recompute-on-navigate list.
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { ProjectListItem } from "../api/types";
import { useAuth } from "./AuthContext";

interface FavouritesContextValue {
  hasFavourites: boolean;
  /** Call after a favourite is toggled anywhere, so the nav rail's
   * "Favourites" entry re-derives its visibility from current state. */
  refreshFavourites: () => void;
}

const FavouritesContext = createContext<FavouritesContextValue>({
  hasFavourites: false,
  refreshFavourites: () => {},
});

export function FavouritesProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [hasFavourites, setHasFavourites] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  const refreshFavourites = useCallback(() => setRefreshToken((t) => t + 1), []);

  useEffect(() => {
    if (!user) return;
    api.get<ProjectListItem[]>("/api/v1/projects?archived=false").then(
      (list) => setHasFavourites(list.some((p) => p.is_favorite))
    );
  }, [user, refreshToken]);

  return (
    <FavouritesContext.Provider value={{ hasFavourites, refreshFavourites }}>
      {children}
    </FavouritesContext.Provider>
  );
}

export function useFavourites(): FavouritesContextValue {
  return useContext(FavouritesContext);
}
