/**
 * Module: modules/compliance/StandardsTabs
 *
 * The tab strip of the Standards page (`/standards`): Standards (the list), By standard and Outstanding (the organisation-wide
 * status views). Each tab has its own address (`paths.ts::standardsViewPath`), so a tab can be bookmarked and an Org Resources
 * address can redirect to it.
 * - The two status tabs are offered only to a person who may read compliance status in some organisation
 *   (`useComplianceStatusOrganizations`); everyone else sees the list alone, with no strip.
 * - The chosen organisation (`?org=`, none meaning every organisation) is kept when moving between the status tabs.
 * - A hook returns the `tabs` and `contentProps` a `ListPageLayout` takes, so the three pages place the strip and wire the tab
 *   panel the same way.
 */
import type { HTMLAttributes, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import type { Organization } from "../../api/types";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { t } from "../../i18n/strings";
import { standardsViewPath, type StandardsView } from "./paths";
import { useComplianceStatusOrganizations } from "./useComplianceNavVisibility";

/** The parts of the Standards page a status tab's panel places in its own `ListPageLayout`. */
export interface ComplianceStatusFrame {
  /** The tab strip (`useStandardsTabs`). */
  tabs: ReactNode | undefined;
  /** Attributes of the list column, wiring it as the tab's panel. */
  contentProps: HTMLAttributes<HTMLDivElement> | undefined;
  /** The Organisation filter, first in the panel's filters; `undefined` for a person in one organisation. */
  orgFilter: ReactNode | undefined;
  /** The organisations the tab reads: the one chosen in the filter, or every organisation the person may read. */
  orgs: Organization[];
  /** True when more than one organisation is read, so each row states its organisation. */
  showOrg: boolean;
}

const strings = t().standardsPage;
const ID_PREFIX = "standards-view";

/**
 * @param active The view the page shows.
 * @param org The organisation a status tab is filtered to (`""` or omitted for every organisation), kept when
 *   switching status tab.
 * @returns `tabs` (the strip, `undefined` when the person has only the list) and `contentProps` for the list column.
 */
export function useStandardsTabs(
  active: StandardsView,
  org = "",
): { tabs: ReactNode | undefined; contentProps: HTMLAttributes<HTMLDivElement> | undefined } {
  const navigate = useNavigate();
  const { ids } = useComplianceStatusOrganizations();
  if (ids.length === 0 && active === "standards") return { tabs: undefined, contentProps: undefined };
  return {
    tabs: (
      <Tabs<StandardsView>
        idPrefix={ID_PREFIX}
        tabs={[
          { key: "standards", label: strings.tabStandards },
          { key: "by-standard", label: strings.tabByStandard },
          { key: "outstanding", label: strings.tabOutstanding },
        ]}
        active={active}
        onChange={(next) => navigate(standardsViewPath(next, next === "standards" ? {} : { org }))}
      />
    ),
    contentProps: tabPanelProps(ID_PREFIX, active),
  };
}
