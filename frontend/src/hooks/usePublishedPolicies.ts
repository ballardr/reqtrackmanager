/**
 * Module: hooks/usePublishedPolicies
 *
 * Loads the published server policies from the public read (no sign-in needed), for the Policies page and the
 * links to it. A failed read (including a rate-limit refusal) yields an empty list, because a link to policies
 * must never get in the way of the page it sits on.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { PublicPolicySummary } from "../api/types";

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
