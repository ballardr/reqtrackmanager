/**
 * Module: modules/stakeholders/peopleTabState
 *
 * The shared constants of the "People / Needs" tab strip (`PeopleTabs`): the tab keys and the attributes that
 * make the list column the active tab's panel.
 */
import { tabPanelProps } from "../../components/Tabs";

export const PEOPLE_TABS_ID_PREFIX = "people-tabs";

export type PeopleTab = "people" | "needs";

/** Attributes for the element that holds the active tab's content, or none when there is no strip. */
export function peoplePanelProps(active: PeopleTab, hasPeople: boolean, hasNeeds: boolean) {
  return hasPeople && hasNeeds ? tabPanelProps(PEOPLE_TABS_ID_PREFIX, active) : {};
}
