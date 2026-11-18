/**
 * Module: modules/architecture/ConnectionSummaryList
 *
 * The one compact list of connections used wherever a narrow column names several of them (the diagram's Selection card for a
 * line that stands for several connections, an element's Connections card). Each row is two lines inside the shared `ItemRow`:
 * the code with the type and protocol, then the two ends; the row's actions stay at its end. A caller that lets the person
 * choose a row (`onChoose`) gets the two lines as one button, and the code is then plain text, so the row has a single main
 * control and the record's page is a separate action.
 *
 * Design decisions: the code never breaks across lines (it is one unbreakable unit) while the row wraps as a whole, so a
 * narrow card shows no clipped column and no code split over three lines. The caller supplies the formatted code (the code
 * rule differs by page) and the row's actions, so the list holds no permission or navigation logic of its own.
 * Dependencies: `components/ItemRow`.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ItemRow } from "../../components/ItemRow";
import type { ArchitectureConnection } from "./types";

/**
 * One connection's row.
 *
 * @param connection The connection to summarise.
 * @param code The connection's code, already formatted by the caller's code rule.
 * @param to Where the code links to; without it (or with `onChoose`) the code is plain text.
 * @param showName Also show the connection's own name after the type (an element page lists them by name).
 * @param actions The row's controls (an Open or Edit icon action); none for a connection the viewer cannot edit.
 * @param onChoose Makes the row's two lines one button that calls this; omit for a row that is only read.
 * @param autoFocus Moves the keyboard focus to the row's button when it first appears (the way back from a chosen connection).
 * @param onFocused Called once that focus has moved.
 */
export function ConnectionSummaryRow({
  connection, code, to, showName = false, actions, onChoose, autoFocus = false, onFocused,
}: {
  connection: ArchitectureConnection;
  code: ReactNode;
  to?: string;
  showName?: boolean;
  actions?: ReactNode;
  onChoose?: () => void;
  autoFocus?: boolean;
  onFocused?: () => void;
}) {
  const detail = [connection.connection_type_name, connection.protocol].filter(Boolean).join(" · ");
  const from = connection.source_element_name || connection.source_element_code;
  const target = connection.target_element_name || connection.target_element_code;
  const choose = useRef<HTMLButtonElement>(null);
  const asked = useRef(autoFocus);
  const done = useRef(onFocused);
  useEffect(() => {
    if (!asked.current) return;
    asked.current = false;
    choose.current?.focus();
    done.current?.();
  }, []);
  const lines = (
    <>
      <span className="connection-summary__line" style={{ display: "flex", flexWrap: "wrap", columnGap: "var(--space-2)", alignItems: "baseline" }}>
        <span style={{ whiteSpace: "nowrap", overflowWrap: "normal" }}>{to && !onChoose ? <Link to={to}>{code}</Link> : code}</span>
        {showName && connection.name && <span>{connection.name}</span>}
        {detail && <span className="text-muted">{detail}</span>}
      </span>
      <span className="connection-summary__line text-muted" style={{ display: "block" }}>
        {from}<span aria-hidden="true"> → </span><span className="sr-only"> to </span>{target}
      </span>
    </>
  );
  return (
    <ItemRow as="li" align="start" className="item-list-row" actions={actions}>
      {onChoose ? <button ref={choose} type="button" className="item-row__choose" onClick={onChoose}>{lines}</button> : lines}
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
 * @param onChoose Called with a connection when its row is chosen (click, Enter or Space); omit for a list that is only read.
 * @param focusId The connection whose row takes the keyboard focus when it first appears.
 * @param onFocused Called once that focus has moved.
 */
export function ConnectionSummaryList({
  connections, label, codeOf, linkTo, showName, actionsOf, onChoose, focusId, onFocused,
}: {
  connections: ArchitectureConnection[];
  label: string;
  codeOf: (connection: ArchitectureConnection) => ReactNode;
  linkTo?: (connection: ArchitectureConnection) => string;
  showName?: boolean;
  actionsOf?: (connection: ArchitectureConnection) => ReactNode;
  onChoose?: (connection: ArchitectureConnection) => void;
  focusId?: string | null;
  onFocused?: () => void;
}) {
  return (
    <ul className="item-row-list" aria-label={label}>
      {connections.map((c) => (
        <ConnectionSummaryRow
          key={c.id} connection={c} code={codeOf(c)} to={linkTo?.(c)} showName={showName} actions={actionsOf?.(c)}
          onChoose={onChoose ? () => onChoose(c) : undefined} autoFocus={focusId === c.id} onFocused={onFocused}
        />
      ))}
    </ul>
  );
}
