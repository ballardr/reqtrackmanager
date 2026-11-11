/**
 * Module: hooks/usePolicyAcceptance
 *
 * Reads the policies the signed-in person must accept (`PolicyAcceptanceContext`) and records an acceptance.
 * `useAcceptPolicy` ends with feedback like every mutation (a success toast, or the server's message, for example
 * when the text changed while it was open) and reloads the list so every notice updates.
 */
import { useCallback, useContext } from "react";

import { api } from "../api/client";
import type { PendingPolicy } from "../api/types";
import { PolicyAcceptanceContext, type PolicyAcceptanceValue } from "../context/PolicyAcceptanceValue";
import { t } from "../i18n/strings";
import { useMutation } from "./useMutation";

const text = t().policies;

/** The session-storage key remembering that one person was shown the sign-in dialog, so a second person on the same tab is asked too. */
export const acceptDialogShownKey = (userId: string) => `policies.acceptDialogShown.${userId}`;

/**
 * @returns The pending policies and `reload`; nothing is pending outside the provider.
 */
export function usePolicyAcceptance(): PolicyAcceptanceValue {
  return useContext(PolicyAcceptanceContext);
}

/**
 * @returns `accept(policy)`, which resolves to whether the acceptance was recorded (it never rejects).
 */
export function useAcceptPolicy(): (policy: PendingPolicy) => Promise<boolean> {
  const run = useMutation();
  const { reload } = usePolicyAcceptance();
  return useCallback(async (policy: PendingPolicy) => {
    const ok = await run(
      () => api.post(`/api/v1/policies/mine/${policy.id}/acknowledge`, { version: policy.version }),
      { success: text.accepted, failure: text.acceptFailed },
    );
    await reload();
    return ok;
  }, [run, reload]);
}
