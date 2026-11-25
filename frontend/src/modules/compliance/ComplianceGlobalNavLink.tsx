/**
 * Module: modules/compliance/ComplianceGlobalNavLink
 *
 * The "Compliance Standards" top-level nav-rail link, registered through `module.ts`'s `globalNavItems` (`modules/types.ts`)
 * and never imported by `Layout.tsx`. It owns its visibility: it renders nothing unless `useComplianceNavVisibility()` says so,
 * because the entry is niche. It stays active on the Standards page's By standard and Outstanding tabs, which have their own
 * addresses. It uses `NavRailLink` (exported from `components/Layout.tsx` for module reuse) so it matches core rail entries.
 */
import { ListChecks } from "lucide-react";

import { NavRailLink } from "../../components/NavRailLink";
import { STANDARDS_STATUS_PATH } from "./paths";
import { useComplianceNavVisibility } from "./useComplianceNavVisibility";

export function ComplianceGlobalNavLink({ railCollapsed }: { railCollapsed: boolean }) {
  const visible = useComplianceNavVisibility();
  if (!visible) return null;
  return (
    <NavRailLink
      to="/standards" exact alsoActiveOn={STANDARDS_STATUS_PATH} label="Compliance Standards"
      icon={<ListChecks size={16} />} railCollapsed={railCollapsed}
    />
  );
}
