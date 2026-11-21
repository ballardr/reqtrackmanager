/**
 * Module: modules/compliance/ComplianceStatusPage
 *
 * The By standard and Outstanding tabs of the Standards page (`/standards/by-standard`, `/standards/outstanding`):
 * the organisation-wide compliance status views, hosted beside the standards list because standards are an entity
 * of their own (a nav entry, a workspace), and these views read across every project assigned one.
 *
 * Responsibilities:
 * - Choose the organisation. Both views are per organisation, so the page offers an Organisation filter (first in the
 *   filter panel, only when the person has more than one) listing the organisations where the person may read the
 *   status (`useComplianceStatusOrganizations`); the choice is `?org=`, defaulting to the first.
 * - Hand the chosen organisation and the title-row parts (`ComplianceStatusFrame`) to the view's panel, which draws
 *   its own `ListPageLayout`. A person with no organisation to read sees the tab strip and a message.
 *
 * Design decisions: the panel is keyed by organisation so no filter or expanded row carries over from the previous
 * one; this page decides no access (the endpoints enforce the Compliance Manager role).
 */
import { useState } from "react";

import type { Organization } from "../../api/types";
import { FilterSelect } from "../../components/FilterSelect";
import { Spinner } from "../../components/Spinner";
import { useOrgLabel, useOrgLabelCapitalized } from "../../context/BrandingContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice } from "../../hooks/useUrlFilter";
import { t } from "../../i18n/strings";
import * as complianceApi from "./api";
import { OrgComplianceOutstandingPanel } from "./OrgComplianceOutstandingPanel";
import { OrgComplianceStandardsPanel } from "./OrgComplianceStandardsPanel";
import { useStandardsTabs } from "./StandardsTabs";
import { useComplianceStatusOrganizations } from "./useComplianceNavVisibility";

const strings = t().standardsPage;

/**
 * @param view The status tab to draw.
 */
export function ComplianceStatusPage({ view }: { view: "by-standard" | "outstanding" }) {
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const { ids, loaded } = useComplianceStatusOrganizations();
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [orgChoice, setOrgChoice] = useUrlChoice("org", ids);
  const orgId = orgChoice || orgs?.[0]?.id || "";
  const { tabs, contentProps } = useStandardsTabs(view, orgId);

  useLoadOnChange(async () => {
    if (!loaded) return;
    const mine = await complianceApi.listMyActiveOrganizations();
    setOrgs(mine.filter((o) => ids.includes(o.id)).sort((a, b) => a.name.localeCompare(b.name)));
  }, [loaded, ids]);

  if (!loaded || orgs === null) return <Spinner />;
  if (orgs.length === 0) {
    return (
      <div className="stack">
        <h1 style={{ margin: 0 }}>{strings.title}</h1>
        {tabs}
        <p className="text-muted">{strings.noStatusAccess}</p>
      </div>
    );
  }

  const orgFilter = orgs.length > 1 ? (
    <FilterSelect
      label={orgLabelCap}
      help={strings.organisationHelp(orgLabel)}
      value={orgId}
      onChange={(next) => setOrgChoice(next)}
      options={orgs.map((o) => ({ value: o.id, label: o.name }))}
    />
  ) : undefined;
  const frame = { tabs, contentProps, orgFilter };
  return view === "by-standard"
    ? <OrgComplianceStandardsPanel key={orgId} orgId={orgId} frame={frame} />
    : <OrgComplianceOutstandingPanel key={orgId} orgId={orgId} frame={frame} />;
}
