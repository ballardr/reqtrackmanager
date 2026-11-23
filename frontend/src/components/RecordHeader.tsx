/**
 * Module: components/RecordHeader
 *
 * The header of every record detail page: back link, title (with the record's code as a muted suffix), status
 * pills, the Edit icon button and the object-action menu, with the record's lifecycle track beneath. Tags,
 * components and references share the line under the title with the badges and the version. A `returnTo` control sits
 * beside the back link when the person arrived from another record's page (docs/ux-style-guide.md, "Pattern: return to
 * where you came from").
 *
 * Design decisions (style guide "Pattern: record header and object actions"):
 * - Edit and the menu sit at the right edge of the title row in an `ItemRow`, so they never move or wrap under a
 *   long title.
 * - The title, its code and `titleAddon` are one inline run: the code follows the title's last word and wraps with
 *   it, so its place never depends on the title's length.
 * - *Object actions* (Archive/Restore, Delete permanently, Export, Subscribe, and every state move other than the
 *   next forward one) live in the menu, which renders even for a single action. The next forward move is Promote: the
 *   next step of the `LifecycleTrack` and the menu's first row (docs/ux-style-guide.md, "Pattern: lifecycle track and
 *   Promote").
 * - The page passes only what the current user may do: an action they cannot perform is omitted, never disabled,
 *   and with no actions the menu is not drawn. The page owns each action's confirmation dialog
 *   (`useConfirmedAction`).
 *
 * External dependencies: `ActionMenu`, `ItemRow`, `LifecycleTrack`, react-router `Link`.
 */
import { RecordCode } from "./RecordCode";
import { Pencil } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { useNavLabelOverride } from "../context/NavLabelValue";
import { listBackTarget } from "../hooks/useListPosition";
import { ItemRow } from "./ItemRow";
import { LifecycleTrack, type LifecycleTrackProps } from "./LifecycleTrack";
import { useStrings } from "../context/TerminologyContext";
import { withDetailRank } from "./detailCardOrder";

/** Leading arrow of the back link; drawn here so every page reads the same. */
const BACK_ARROW = "← ";

/**
 * @param recordLabel Singular record name; the menu is named "{recordLabel} actions".
 * @param title The record's title (heading text).
 * @param titleAddon Small control shown right after the title (an `EntitySwitcher`).
 * @param code Human-readable code (`REQ-001`), shown as a small muted suffix.
 * @param codeOwner The owning organisation's code for a record the organisation owns (`PER-001` becomes `ACME-PER-001`).
 * @param subtitle Secondary line under the title (type, owner, priority).
 * @param badges Status and scope pills, shown on the line under the title.
 * @param version The record's version number, for a versioned record; shown as "Version n" after the badges, never as its own line.
 * @param tags The record's tags, components and references (`RecordTags`), after the badges and the version on the line under the title (wrapping onto further lines of the same row). `RecordTags` draws nothing for a record with none that the viewer cannot add to, and an empty line is hidden, so the header carries no gap.
 * @param back Link back to the list: `{ to, label }` (it lands on the list as it was left, filters and scroll position kept), or `{ onClick, label }` inside a page that switches views itself. The label is the destination's plural name ("Pain Points"); a name the project or organisation gave the destination's navigation entry replaces it. The header draws the leading arrow, so pages never type it.
 * @param returnTo A control beside the back link that leads to where the person came from (`ReturnLink`, or a menu of the places the record is used). Its page decides what it shows and whether it is trustworthy; the header only places it.
 * @param headingLevel `h1` (default) for a page; `h2` for a record opened inside a page that already has an `h1`.
 * @param onEdit Opens the edit form; omit when the user cannot edit.
 * @param lifecycle The record's states and its next forward move (`LifecycleTrack`), drawn under the title; omit for a record with no states. The move is also the first row of the actions menu.
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
  version,
  tags,
  back,
  returnTo,
  headingLevel = "h1",
  onEdit,
  lifecycle,
  actions = [],
}: {
  recordLabel: string;
  title: ReactNode;
  titleAddon?: ReactNode;
  code?: string;
  codeOwner?: string | null;
  subtitle?: ReactNode;
  badges?: ReactNode;
  version?: number;
  tags?: ReactNode;
  back?: { to: string; label: string } | { onClick: () => void; label: string };
  returnTo?: ReactNode;
  headingLevel?: "h1" | "h2";
  onEdit?: () => void;
  lifecycle?: LifecycleTrackProps;
  actions?: Array<ActionMenuItem | null | false | undefined>;
}) {
  const strings = useStrings();
  const backName = useNavLabelOverride(back && "to" in back ? back.to : undefined);
  const promoteTarget = lifecycle?.promote && [...lifecycle.steps, ...(lifecycle.offPath ? [lifecycle.offPath] : [])].find((st) => st.key === lifecycle.promote?.to);
  const promoteRow: ActionMenuItem | null = lifecycle?.promote?.onPromote && promoteTarget
    ? { label: strings.lifecycle.promoteTo(promoteTarget.label), onSelect: lifecycle.promote.onPromote }
    : null;
  const items = [promoteRow, ...actions].filter((a): a is ActionMenuItem => !!a);
  const Heading = headingLevel;
  const hasControls = onEdit || items.length > 0;
  return (
    <header className="stack record-header" style={{ gap: "var(--space-3)" }}>
      {(back || returnTo) && (
        <div className={returnTo ? "row" : undefined} style={returnTo ? { gap: "var(--space-4)", alignItems: "center" } : undefined}>
          {back && ("to" in back ? (
            <Link {...listBackTarget(back.to)}>{BACK_ARROW}{backName ?? back.label}</Link>
          ) : (
            <button type="button" className="btn" onClick={back.onClick}>{BACK_ARROW}{back.label}</button>
          ))}
          {returnTo}
        </div>
      )}
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
        <div className="record-header__title">
          <Heading className="record-header__heading">{title}</Heading>
          {code && (
            <>{" "}<span className="record-header__code text-muted"><RecordCode code={code} ownerProjectCode={codeOwner} /></span></>
          )}
          {titleAddon && <>{" "}<span className="record-header__addon">{titleAddon}</span></>}
        </div>
      </ItemRow>
      {(badges || version !== undefined || tags) && (
        <div className="row record-header__line">
          {badges}
          {version !== undefined && (
            <span className="text-muted" style={{ fontSize: "0.85rem" }} title={`Version ${version} of this record`}>
              Version {version}
            </span>
          )}
          {tags}
        </div>
      )}
      {subtitle && <p className="text-muted" style={{ margin: 0 }}>{subtitle}</p>}
      {lifecycle && <LifecycleTrack {...lifecycle} />}
    </header>
  );
}

withDetailRank(RecordHeader, "header");
