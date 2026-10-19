/**
 * Module: modules/stakeholders/peopleRows
 *
 * The row model of the People page's combined list: a Persona, Stakeholder, Stakeholder Need and Stakeholder
 * group each become one `PeopleRow`, so `RecordListView` (which wants one record shape) can list them
 * together, and the pure helpers around it — the kinds the page can show, which of them a project has
 * switched on, and the `?kind=` query the old per-type routes redirect to.
 */
import type { ListedRecord } from "./RecordListView";
import type { Need, Persona, Stakeholder, StakeholderGroup } from "./types";

export type PeopleKind = "persona" | "stakeholder" | "need" | "group";

/** Display order of the kinds, in the filter chips and the New menu. */
export const PEOPLE_KINDS: PeopleKind[] = ["persona", "stakeholder", "need", "group"];

/** The kind named in the Kind column and the New menu. */
export const PEOPLE_KIND_LABEL: Record<PeopleKind, string> = {
  persona: "Persona",
  stakeholder: "Stakeholder",
  need: "Stakeholder Need",
  group: "Stakeholder Group",
};

/** The kind named in the filter chips. */
export const PEOPLE_KIND_PLURAL_LABEL: Record<PeopleKind, string> = {
  persona: "Personas",
  stakeholder: "Stakeholders",
  need: "Needs",
  group: "Groups",
};

/** The module sub-component whose being off removes a kind (groups belong with stakeholders). */
export const PEOPLE_KIND_SUBCOMPONENT: Record<PeopleKind, string> = {
  persona: "persona",
  stakeholder: "stakeholder",
  need: "stakeholder_need",
  group: "stakeholder",
};

/** One row of the combined list. */
export interface PeopleRow extends ListedRecord {
  kind: PeopleKind;
  /** Role or short description, whichever the kind has. */
  summary: string;
  /** The kind's own type (Persona type, Stakeholder type); null for kinds without one. */
  typeName: string | null;
  /** The underlying record, for the page's per-kind actions. */
  source: Persona | Stakeholder | Need | StakeholderGroup;
}

export function personaRow(p: Persona): PeopleRow {
  return { ...p, kind: "persona", summary: p.role_title, typeName: p.persona_type_name, source: p };
}

export function stakeholderRow(s: Stakeholder): PeopleRow {
  return { ...s, kind: "stakeholder", summary: s.role, typeName: s.stakeholder_type_name, source: s };
}

export function needRow(n: Need): PeopleRow {
  return { ...n, kind: "need", summary: n.description, typeName: null, source: n };
}

export function groupRow(g: StakeholderGroup): PeopleRow {
  const members = `${g.member_count} ${g.member_count === 1 ? "member" : "members"}`;
  return {
    ...g, kind: "group", summary: g.description || members, typeName: null, source: g,
    scope: g.project_id ? "project" : "organization",
  };
}

/**
 * The kinds a project has switched on, in display order. Groups travel with Stakeholders.
 *
 * @param disabledSubComponents The module's `disabled_sub_components` for the project.
 */
export function enabledKinds(disabledSubComponents: string[]): PeopleKind[] {
  return PEOPLE_KINDS.filter((k) => !disabledSubComponents.includes(PEOPLE_KIND_SUBCOMPONENT[k]));
}

/**
 * The kinds named by the `?kind=` query, restricted to the enabled ones. An absent, empty or all-unknown
 * value means every enabled kind, so a stale bookmark never lands on an empty page.
 *
 * @param raw The comma-separated `kind` query value, or null.
 * @param enabled The kinds the project has on.
 */
export function selectedKinds(raw: string | null, enabled: PeopleKind[]): PeopleKind[] {
  const wanted = (raw ?? "").split(",").filter((k): k is PeopleKind => (PEOPLE_KINDS as string[]).includes(k));
  const chosen = enabled.filter((k) => wanted.includes(k));
  return chosen.length > 0 ? chosen : enabled;
}

/** The `?kind=` value for a selection: empty when every enabled kind is selected (the default). */
export function kindQuery(selected: PeopleKind[], enabled: PeopleKind[]): string {
  return selected.length === enabled.length ? "" : selected.join(",");
}
