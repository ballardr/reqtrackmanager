/**
 * Module: modules/architecture/ConnectionSummaryList
 *
 * The one compact list of connections used wherever a narrow column names several of them (the diagram's Selection card for a
 * line that stands for several connections, an element's Connections card). Each row is two lines inside the shared `ItemRow`:
 * the code with the type and protocol, then the two ends; the row's actions stay at its end.
 *
 * Design decisions: the code never breaks across lines (it is one unbreakable unit) while the row wraps as a whole, so a
 * narrow card shows no clipped column and no code split over three lines. The caller supplies the formatted code (the code
 * rule differs by page) and the row's actions, so the list holds no permission or navigation logic of its own.
 * Dependencies: `components/ItemRow`.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ItemRow } from "../../components/ItemRow";
import type { ArchitectureConnection } from "./types";

/**
 * One connection's row.
 *
 * @param connection The connection to summarise.
 * @param code The connection's code, already formatted by the caller's code rule.
 * @param to Where the code links to; without it the code is plain text.
 * @param showName Also show the connection's own name after the type (an element page lists them by name).
 * @param actions The row's controls (an Edit icon action); none for a connection the viewer cannot edit.
 */
export function ConnectionSummaryRow({
  connection, code, to, showName = false, actions,
}: {
  connection: ArchitectureConnection;
  code: ReactNode;
  to?: string;
  showName?: boolean;
  actions?: ReactNode;
}) {
  const detail = [connection.connection_type_name, connection.protocol].filter(Boolean).join(" · ");
  const from = connection.source_element_name || connection.source_element_code;
  const target = connection.target_element_name || connection.target_element_code;
  return (
    <ItemRow as="li" align="start" className="item-list-row" actions={actions}>
      <div style={{ display: "flex", flexWrap: "wrap", columnGap: "var(--space-2)", alignItems: "baseline" }}>
        <span style={{ whiteSpace: "nowrap", overflowWrap: "normal" }}>{to ? <Link to={to}>{code}</Link> : code}</span>
        {showName && connection.name && <span>{connection.name}</span>}
        {detail && <span className="text-muted">{detail}</span>}
      </div>
      <div className="text-muted">
        {from}<span aria-hidden="true"> → </span><span className="sr-only"> to </span>{target}
      </div>
    </ItemRow>
  );
}

/**
 * A list of connections in the shared row shape.
 *
 * @param connections The connections, in order.
 * @param label Accessible name of the list.
 * @param codeOf The caller's formatted code for a connection.
 * @param linkTo Where a connection's code links to; omit for plain text.
 * @param showName Show each connection's own name (see `ConnectionSummaryRow`).
 * @param actionsOf The row's controls for a connection; return nothing for one that has none.
 */
export function ConnectionSummaryList({
  connections, label, codeOf, linkTo, showName, actionsOf,
}: {
  connections: ArchitectureConnection[];
  label: string;
  codeOf: (connection: ArchitectureConnection) => ReactNode;
  linkTo?: (connection: ArchitectureConnection) => string;
  showName?: boolean;
  actionsOf?: (connection: ArchitectureConnection) => ReactNode;
}) {
  return (
    <ul className="item-row-list" aria-label={label}>
      {connections.map((c) => (
        <ConnectionSummaryRow
          key={c.id} connection={c} code={codeOf(c)} to={linkTo?.(c)} showName={showName} actions={actionsOf?.(c)}
        />
      ))}
    </ul>
  );
}
