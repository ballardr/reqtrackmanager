/**
 * Module: modules/compliance/OrgCompliancePanel
 *
 * Phase 14's org-level, read/drill-down-only compliance surface — §22's
 * Organisation Compliance View and §23's Compliance Dashboard. Explicitly
 * NOT the standards-management UI (`ComplianceAdminPanel`, Phase 12) —
 * that panel's own docstring already flagged this as a separate, later
 * surface. Declared as its own flat top-level `ResourceMenu` group
 * (`"compliance-overview"`, `/orgs/:orgId/admin/compliance-overview`)
 * rather than a fourth tab bolted onto `ComplianceAdminPanel`'s existing
 * three — the style guide's own 2026-08-24 addendum is explicit that a
 * resource-menu group that's outgrowing itself should split into more flat
 * top-level groups rather than gain nested sub-navigation, and standards
 * management vs. org-wide compliance reporting are different jobs for a
 * different (if overlapping) audience, not one crowded screen.
 *
 * Mounting mechanism: originally mounted the same way Phase 12 mounted
 * `ComplianceAdminPanel` (directly by a hardcoded `OrgAdminPage.tsx` render
 * block, since Phase 3's Tier A `installedModules`/routing mechanism is
 * project-scoped only and has no org-level equivalent). **Updated by the
 * module system follow-up (2026-09-07, see `docs/decisions.md`'s "Module
 * system follow-up: dynamic org-admin panel registration" entry)**: this
 * panel is now declared in `./module.ts`'s `orgAdminSections`
 * (`modules/types.ts`) instead, alongside `ComplianceAdminPanel`'s own
 * entry — see that component's own docstring for the full up-to-date
 * mechanism, which applies unchanged here.
 *
 * Three `Tabs` (Dashboard / Standards / Outstanding) — within the style
 * guide's own five-or-fewer threshold, mirroring Phase 13's
 * `ProjectCompliancePage` three-tab IA (Standards / Evidence / Outstanding)
 * for the same kind of "a handful of equally-relevant views of one
 * dataset" surface.
 */
import { useState } from "react";

import { Tabs, tabPanelProps } from "../../components/Tabs";
import { OrgComplianceDashboard } from "./OrgComplianceDashboard";
import { OrgComplianceOutstandingPanel } from "./OrgComplianceOutstandingPanel";
import { OrgComplianceStandardsPanel } from "./OrgComplianceStandardsPanel";

type OrgComplianceTabKey = "dashboard" | "standards" | "outstanding";

export function OrgCompliancePanel({ orgId }: { orgId: string }) {
  const [tab, setTab] = useState<OrgComplianceTabKey>("dashboard");

  return (
    <div className="stack">
      <Tabs<OrgComplianceTabKey>
        idPrefix="compliance-overview"
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "dashboard", label: "Dashboard" },
          { key: "standards", label: "Compliance by standard" },
          { key: "outstanding", label: "Outstanding" },
        ]}
      />
      {tab === "dashboard" && (
        <div {...tabPanelProps("compliance-overview", "dashboard")}>
          <OrgComplianceDashboard orgId={orgId} />
        </div>
      )}
      {tab === "standards" && (
        <div {...tabPanelProps("compliance-overview", "standards")}>
          <OrgComplianceStandardsPanel orgId={orgId} />
        </div>
      )}
      {tab === "outstanding" && (
        <div {...tabPanelProps("compliance-overview", "outstanding")}>
          <OrgComplianceOutstandingPanel orgId={orgId} />
        </div>
      )}
    </div>
  );
}
