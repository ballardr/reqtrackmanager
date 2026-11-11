/**
 * Module: hooks/usePublishedPolicies
 *
 * Loads the published policies for the Policies page and the links to it: the server's from the public read (no
 * sign-in needed) and, for a signed-in person, those of their organisations they may read. A failed read (including a
 * rate-limit refusal) yields an empty list, because a link to policies must never get in the way of the page it sits on.
 */
import { useContext, useEffect, useState } from "react";

import { api } from "../api/client";
import type { MemberPolicySummary, PublicPolicySummary } from "../api/types";
import { AuthContext } from "../context/AuthContextValue";

/**
 * @returns `policies` (empty until loaded or when none are published) and `loaded` (false until the read ends).
 */
export function usePublishedPolicies(): { policies: PublicPolicySummary[]; loaded: boolean } {
  const [state, setState] = useState<{ policies: PublicPolicySummary[]; loaded: boolean }>({ policies: [], loaded: false });
  useEffect(() => {
    let cancelled = false;
    api.get<PublicPolicySummary[]>("/api/v1/public/policies").then(
      (loaded) => { if (!cancelled) setState({ policies: Array.isArray(loaded) ? loaded : [], loaded: true }); },
      () => { if (!cancelled) setState({ policies: [], loaded: true }); },
    );
    return () => { cancelled = true; };
  }, []);
  return state;
}

/**
 * The published policies of the signed-in person's organisations that they may read. Reads nothing while signed out.
 *
 * @returns `policies` (empty until loaded, when signed out or on a failed read) and `loaded`.
 */
export function useMemberPolicies(): { policies: MemberPolicySummary[]; loaded: boolean } {
  // Read through the context directly: a page that renders outside the provider (a story) is simply signed out.
  const signedIn = (useContext(AuthContext)?.user ?? null) !== null;
  const [state, setState] = useState<{ policies: MemberPolicySummary[]; loaded: boolean }>({ policies: [], loaded: false });
  useEffect(() => {
    if (!signedIn) return;
    let cancelled = false;
    api.get<MemberPolicySummary[]>("/api/v1/policies/mine").then(
      (loaded) => { if (!cancelled) setState({ policies: Array.isArray(loaded) ? loaded : [], loaded: true }); },
      () => { if (!cancelled) setState({ policies: [], loaded: true }); },
    );
    return () => { cancelled = true; };
  }, [signedIn]);
  return signedIn ? state : { policies: [], loaded: true };
}
