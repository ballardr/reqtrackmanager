/**
 * Module: modules/stakeholders/PeopleKindLabel
 *
 * The one label for a person record named in a chip, link list, badge or table cell: the kind icon
 * (`PeopleKindIcon`, named by the kind as tooltip and accessible name), an optional leading part (a record
 * code), the name (a link when `to` is given) and an optional trailing note. The icon is `flex: none` and the
 * name is a `CellText`, so a long name is cut with an ellipsis and never changes the shape of the chip or row
 * that holds it.
 *
 * Dependencies: `PeopleKindIcon`, `CellText`, `react-router-dom`'s `Link`; the `.people-kind-label` rules in
 * `styles/theme.css`.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { CellText } from "../../components/CellText";
import { PeopleKindIcon } from "./PeopleKindIcon";
import type { PersonKind } from "./peopleRows";

/**
 * Shows a person record with the icon of its kind.
 *
 * @param kind The kind of record named.
 * @param name The record's name or an anonymous participant's label.
 * @param to Route of the record's page; omit for text only.
 * @param before Content between the icon and the name (a record code).
 * @param after Content after the name (a note such as "anonymous").
 */
export function PeopleKindLabel({
  kind, name, to, before, after,
}: {
  kind: PersonKind;
  name: string;
  to?: string;
  before?: ReactNode;
  after?: ReactNode;
}) {
  return (
    <span className="people-kind-label">
      <PeopleKindIcon kind={kind} />
      {before}
      {to ? <Link to={to} className="people-kind-label__name"><CellText>{name}</CellText></Link> : <CellText>{name}</CellText>}
      {after}
    </span>
  );
}
