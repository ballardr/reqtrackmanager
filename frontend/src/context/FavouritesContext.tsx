/**
 * Module: context/FavouritesContext
 *
 * Tracks whether the current user has any active favourited project, for `Layout.tsx`'s nav-rail "Favourites" entry
 * (`hasFavourites`), so the rail does not go stale when a favourite is toggled anywhere in a session.
 *
 * `FavouritesProvider` wraps the app inside `Layout` (beside `TerminologyProvider` and `BrandingProvider`) so the nav rail
 * and every page rendered as `children` share one `hasFavourites` value. Any component that toggles a project's
 * favourite status (`ProjectListPage.tsx`, `FavouritesPage.tsx`) calls `refreshFavourites()` (via `useFavourites()`)
 * after the mutating API call succeeds, so the rail updates at once without a recompute-on-navigate route list.
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
    api.get<ProjectListItem[]>("/api/v1/projects?archived=false&include_templates=true").then(
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
