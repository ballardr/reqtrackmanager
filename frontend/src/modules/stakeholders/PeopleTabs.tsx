/**
 * Module: modules/stakeholders/PeopleTabs
 *
 * The "People / Needs" tab strip under the title of the People page and the Needs page. Each tab is its own
 * route (`/people`, `/needs`), so choosing one navigates, and the list column of the page showing it is the
 * strip's panel (`peoplePanelProps`, `peopleTabState.ts`). There is no strip when the project has only one of the two on, since
 * a single tab says nothing.
 */
import { useNavigate } from "react-router-dom";

import { Tabs } from "../../components/Tabs";
import { PEOPLE_TABS_ID_PREFIX, type PeopleTab } from "./peopleTabState";

/**
 * @param projectId The project whose pages the tabs link between.
 * @param active The tab of the page showing this strip.
 * @param hasPeople Whether the People tab exists (a Persona, Stakeholder or Group kind is on).
 * @param hasNeeds Whether the Needs tab exists (the Stakeholder Need sub-component is on).
 */
export function PeopleTabs({
  projectId, active, hasPeople, hasNeeds,
}: { projectId: string; active: PeopleTab; hasPeople: boolean; hasNeeds: boolean }) {
  const navigate = useNavigate();
  const tabs: { key: PeopleTab; label: string }[] = [
    ...(hasPeople ? [{ key: "people" as const, label: "People" }] : []),
    ...(hasNeeds ? [{ key: "needs" as const, label: "Needs" }] : []),
  ];
  if (tabs.length < 2) return null;
  return (
    <Tabs
      idPrefix={PEOPLE_TABS_ID_PREFIX}
      tabs={tabs}
      active={active}
      onChange={(key) => navigate(`/projects/${projectId}/modules/stakeholders/${key}`)}
    />
  );
}
