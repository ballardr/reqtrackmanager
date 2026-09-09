/**
 * Module: modules/compliance/ComplianceGlobalNavLink
 *
 * The "Compliance Standards" top-level nav-rail link (docs/compliance-
 * module-plan.md Phase 18) — registered via `module.ts`'s `globalNavItems`
 * (`modules/types.ts`), never imported by `Layout.tsx` directly. Owns its
 * own visibility entirely: renders nothing at all unless
 * `useComplianceNavVisibility()` says so, since this tab is niche (unlike
 * Projects, which `Layout.tsx` always shows unconditionally).
 *
 * Uses `NavRailLink`, exported from `components/Layout.tsx` for exactly
 * this kind of module-owned reuse, so this link renders indistinguishably
 * from every core rail entry.
 */
import { ListChecks } from "lucide-react";

import { NavRailLink } from "../../components/Layout";
import { useComplianceNavVisibility } from "./useComplianceNavVisibility";

export function ComplianceGlobalNavLink({ railCollapsed }: { railCollapsed: boolean }) {
  const visible = useComplianceNavVisibility();
  if (!visible) return null;
  return <NavRailLink to="/standards" exact label="Compliance Standards" icon={<ListChecks size={16} />} railCollapsed={railCollapsed} />;
}
