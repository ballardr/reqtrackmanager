/**
 * Module: modules/compliance/ComplianceStatusPage
 *
 * The By standard and Outstanding tabs of the Standards page (`/standards/by-standard`, `/standards/outstanding`):
 * the organisation-wide compliance status views, hosted beside the standards list because standards are an entity
 * of their own (a nav entry, a workspace), and these views read across every project assigned one.
 *
 * Responsibilities:
 * - Choose the organisations. The page offers an Organisation filter (first in the filter panel, only when the person
 *   has more than one) listing the organisations where the person may read the status
 *   (`useComplianceStatusOrganizations`); the choice is `?org=` and no choice reads every one of them.
 * - Hand the organisations read and the title-row parts (`ComplianceStatusFrame`) to the view's panel, which draws its
 *   own `ListPageLayout`. A person with no organisation to read sees the tab strip and a message.
 *
 * Design decisions: the panel is keyed by the organisations read so no filter or expanded row carries over from the
 * previous choice; this page decides no access (the endpoints enforce the Compliance Manager role).
 */
import { useState } from "react";

import type { Organization } from "../../api/types";
import { FilterSelect } from "../../components/FilterSelect";
import { LoadFailed } from "../../components/LoadFailed";
import { Spinner } from "../../components/Spinner";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../../context/BrandingContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice } from "../../hooks/useUrlFilter";
import { t } from "../../i18n/strings";
import * as complianceApi from "./api";
import { OrgComplianceOutstandingPanel } from "./OrgComplianceOutstandingPanel";
import { OrgComplianceStandardsPanel } from "./OrgComplianceStandardsPanel";
import { useStandardsTabs } from "./StandardsTabs";
import { useComplianceStatusOrganizations } from "./useComplianceNavVisibility";

const strings = t().standardsPage;
const failureStrings = t().requestFailure;

/**
 * @param view The status tab to draw.
 */
export function ComplianceStatusPage({ view }: { view: "by-standard" | "outstanding" }) {
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const orgLabelPlural = useOrgLabelPlural();
  const { ids, loaded } = useComplianceStatusOrganizations();
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [orgChoice, setOrgChoice] = useUrlChoice("org", ids);
  const { tabs, contentProps } = useStandardsTabs(view, orgChoice);

  const loadOrganizations = async () => {
    if (!loaded) return;
    setFailed(false);
    try {
      const mine = await complianceApi.listMyActiveOrganizations();
      setOrgs(mine.filter((o) => ids.includes(o.id)).sort((a, b) => a.name.localeCompare(b.name)));
    } catch {
      setFailed(true);
    }
  };
  useLoadOnChange(loadOrganizations, [loaded, ids]);

  if (failed) {
    return <LoadFailed message={failureStrings.loadFailed(failureStrings.complianceStatus)} onRetry={() => void loadOrganizations()} />;
  }
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
      help={strings.organisationHelp(orgLabel, orgLabelPlural)}
      value={orgChoice}
      onChange={(next: string) => setOrgChoice(next)}
      allLabel={t().projects.allOrganisations(orgLabelPlural)}
      options={orgs.map((o) => ({ value: o.id, label: o.name }))}
    />
  ) : undefined;
  const read = orgChoice ? orgs.filter((o) => o.id === orgChoice) : orgs;
  const frame = { tabs, contentProps, orgFilter, orgs: read, showOrg: read.length > 1 };
  const panelKey = read.map((o) => o.id).join(",");
  return view === "by-standard"
    ? <OrgComplianceStandardsPanel key={panelKey} frame={frame} />
    : <OrgComplianceOutstandingPanel key={panelKey} frame={frame} />;
}
