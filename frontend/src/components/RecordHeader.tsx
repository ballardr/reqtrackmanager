/**
 * Module: components/RecordHeader
 *
 * The header of every record detail page: back link, title (with the record's
 * code as a muted suffix), status pills, the Edit icon button and the object-action
 * menu, with the record's visible workflow buttons beneath.
 *
 * Design decisions (style guide "Pattern: record header and object actions"):
 * - Edit and the menu sit at the right edge of the title row, in an `ItemRow`, so they
 *   never move or wrap under a long title at any viewport width.
 * - *Object actions* (Archive/Restore, Delete permanently, Export, Subscribe) live in
 *   the menu, which renders even for a single action; *transitions* (Submit, Approve,
 *   Retire, Withdraw) stay visible beside the status because they depend on it.
 * - The page passes only what the current user may do: an action they cannot perform
 *   is omitted, never disabled, and with no actions at all the menu is not drawn.
 * - The page owns each action's confirmation dialog (`useConfirmedAction`).
 *
 * External dependencies: `ActionMenu`, `ItemRow`, react-router `Link`.
 */
import { RecordCode } from "./RecordCode";
import { Pencil } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { ItemRow } from "./ItemRow";

/**
 * @param recordLabel Singular record name; the menu is named "{recordLabel} actions".
 * @param title The record's title (heading text).
 * @param titleAddon Small control shown right after the title (an `EntitySwitcher`).
 * @param code Human-readable code (`REQ-001`), shown as a small muted suffix.
 * @param codeOwner The owning organisation's code for a record the organisation owns (`PER-001` becomes `ACME-PER-001`).
 * @param subtitle Secondary line under the title (type, owner, version).
 * @param badges Status and scope pills, shown on the line under the title.
 * @param back Link back to the list: `{ to, label }`, or `{ onClick, label }` inside a page that switches views itself.
 * @param headingLevel `h1` (default) for a page; `h2` for a record opened inside a page that already has an `h1`.
 * @param onEdit Opens the edit form; omit when the user cannot edit.
 * @param transitions Visible workflow buttons (Submit, Approve, Retire...).
 * @param actions Object actions for the menu; falsy entries are dropped.
 */
export function RecordHeader({
  recordLabel,
  title,
  titleAddon,
  code,
  codeOwner,
  subtitle,
  badges,
  back,
  headingLevel = "h1",
  onEdit,
  transitions,
  actions = [],
}: {
  recordLabel: string;
  title: ReactNode;
  titleAddon?: ReactNode;
  code?: string;
  codeOwner?: string | null;
  subtitle?: ReactNode;
  badges?: ReactNode;
  back?: { to: string; label: string } | { onClick: () => void; label: string };
  headingLevel?: "h1" | "h2";
  onEdit?: () => void;
  transitions?: ReactNode;
  actions?: Array<ActionMenuItem | null | false | undefined>;
}) {
  const items = actions.filter((a): a is ActionMenuItem => !!a);
  const Heading = headingLevel;
  const hasControls = onEdit || items.length > 0;
  return (
    <header className="stack record-header" style={{ gap: "0.5rem" }}>
      {back && ("to" in back ? (
        <Link to={back.to}>{back.label}</Link>
      ) : (
        <div><button type="button" className="btn" onClick={back.onClick}>{back.label}</button></div>
      ))}
      <ItemRow
        actions={
          hasControls ? (
            <>
              {onEdit && (
                <button type="button" className="btn btn-icon" title="Edit" aria-label="Edit" onClick={onEdit}>
                  <Pencil />
                </button>
              )}
              {items.length > 0 && <ActionMenu triggerLabel={`${recordLabel} actions`} items={items} />}
            </>
          ) : undefined
        }
      >
        <span className="row" style={{ gap: "0.6rem", alignItems: "baseline", flexWrap: "nowrap", minWidth: 0 }}>
          <Heading style={{ margin: 0, minWidth: 0 }}>{title}</Heading>
          {code && (
            <span className="text-muted" style={{ fontSize: "0.9rem", flex: "none" }}><RecordCode code={code} ownerProjectCode={codeOwner} /></span>
          )}
          {titleAddon}
        </span>
      </ItemRow>
      {badges && <div className="row">{badges}</div>}
      {subtitle && <p className="text-muted" style={{ margin: 0 }}>{subtitle}</p>}
      {transitions && <div className="row">{transitions}</div>}
    </header>
  );
}
