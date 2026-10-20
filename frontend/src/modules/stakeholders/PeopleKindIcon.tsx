/**
 * Module: modules/stakeholders/PeopleKindIcon
 *
 * The icon that marks a kind of person on the People page (Persona, Stakeholder, Stakeholder group): left
 * of the name in every row and in each kind chip. One map, `PEOPLE_KIND_ICON` (`peopleRows.ts`, beside the labels), so a list and a chip cannot
 * disagree. The kind is never conveyed by the icon alone: the icon has the kind's label as its accessible
 * name and as its tooltip.
 */
import { Tooltip } from "../../components/Tooltip";
import { PEOPLE_KIND_ICON, PEOPLE_KIND_LABEL, type PeopleKind } from "./peopleRows";

/**
 * @param kind The kind to mark.
 * @param labelled Show the kind's name as the tooltip and accessible name (default); a chip that already
 *   carries the name beside the icon passes `false` so it is not announced twice.
 */
export function PeopleKindIcon({ kind, labelled = true }: { kind: PeopleKind; labelled?: boolean }) {
  const Icon = PEOPLE_KIND_ICON[kind];
  const label = PEOPLE_KIND_LABEL[kind];
  if (!labelled) return <Icon size={14} aria-hidden="true" />;
  return (
    <Tooltip label={label}>
      <span role="img" aria-label={label} className="people-kind-icon">
        <Icon size={14} aria-hidden="true" />
      </span>
    </Tooltip>
  );
}
