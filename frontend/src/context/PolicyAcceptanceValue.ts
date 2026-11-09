/**
 * Module: context/PolicyAcceptanceValue
 *
 * The `PolicyAcceptanceContext` object and its value type, split from the provider so that file exports only a
 * component (Fast Refresh). Outside a provider (a story, a signed-out page) nothing is pending.
 */
import { createContext } from "react";

import type { PendingPolicy } from "../api/types";

export interface PolicyAcceptanceValue {
  /** The required policies the signed-in person has not accepted (empty while loading or when none). */
  pending: PendingPolicy[];
  /** Reads the list again, for example after an acceptance. */
  reload: () => Promise<void>;
}

export const PolicyAcceptanceContext = createContext<PolicyAcceptanceValue>({ pending: [], reload: async () => undefined });
