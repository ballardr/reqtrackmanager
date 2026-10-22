/**
 * Module: components/ArtefactLinksPanel
 *
 * The one Links panel every artefact detail page shows beside its content (in
 * `DetailLayout`'s aside): the record's direct links grouped by the type of record
 * at the other end, each phrased by its link type ("Implements", "Is addressed
 * by"), with where it lives, its status and whether it is archived; an "Add link"
 * dialog and a remove action for those who may change links.
 *
 * It replaces the per-module relationship sections: link kinds are not listed per
 * page, they come from the server (`link-types`, restriction- and rule-filtered), so
 * a new artefact type or link type needs no change here. Dedicated actions with
 * their own semantics (Supersede) are supplied by the page through `actions`.
 *
 * Responsibilities:
 * - Load the depth-1 link graph (`artefactLinksApi.graph`); the server has already
 *   hidden what the user may not see and says how many it left out.
 * - Show links to other projects (a parent or child) with a project badge, and flag
 *   a link its link type no longer permits instead of hiding it.
 * - Open the trace (tree and map) of the record's links in a modal.
 * - Remove a link behind a Tier-1 confirmation; route through a change request when
 *   the page says links are locked (`changeRequest`).
 *
 * Design decisions:
 * - `projectId` is undefined for an organisation-owned record; links are
 *   project-scoped, so the panel then shows a note instead of an add control.
 * - Other modules' statuses are shown through their registered label maps
 *   (`getArtefactStatusLabel`); a status with no label shows no badge, never the raw value.
 * - API calls are injectable (`api`) so stories and tests need no network.
 * - `compact` is the variant for a panel that sits inside another record's card (a finding in its
 *   engagement): no card chrome, a caption-sized "Links" title with icon buttons (+ to add, a branch
 *   icon to trace) beside it, and tighter spacing. `hideLinkedTypes` leaves out links to records of
 *   those artefact types where the page already shows them (the engagement a finding sits in); the
 *   trace and the records themselves are unchanged.
 * - Rows carry no pills. A group is a record type (a chevron toggle and a plain count), and inside it
 *   the relationship is a small label above its rows ("Has participant · 3"), so several links of one
 *   kind read as a list under one label rather than a repeated pill. A count shows only when it
 *   says something: more than one link, or a collapsed group. A record's code is a small muted
 *   suffix after its title (`LinkedRecordSummary`'s `list` layout).
 * - The relationship labels are off by default (the trace shows them, and each row's hover text
 *   names its relationship), and a "View options" popover turns them, and the compact layout, on or
 *   off for this panel. The relationship choice is remembered per viewer (local storage, optional).
 * - Each record-type group can be collapsed to its heading and count (a chevron toggle). A page
 *   that expects a long group of little interest passes `collapsedTypes` to start those groups
 *   collapsed (an engagement starts with its findings collapsed); the viewer's own toggling then wins.
 */
import { ChevronDown, ChevronRight, GitBranch, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { artefactLinksApi, type ArtefactLinksApi, type LinkGraph, type LinkGraphEdge, type LinkGraphNode } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { AddPopoverButton } from "./AddPopoverButton";
import { AddArtefactLinkModal, type LinksChangeRequestMode } from "./AddArtefactLinkModal";
import { ConfirmDialog } from "./ConfirmDialog";
import { ItemRow } from "./ItemRow";
import { LinkedRecordSummary } from "./LinkedRecordSummary";
import { LinkTraceModal } from "./LinkTraceModal";
import { useInDetailAside } from "./detailAsideContext";
import { TextAreaField } from "./FormFields";

export type { LinksChangeRequestMode } from "./AddArtefactLinkModal";

const RELATIONSHIPS_KEY = "reqtrack.links.showRelationships";

/** The viewer's remembered "show relationships" choice; absent or unreadable storage means hidden. */
function readStoredRelationships(): boolean {
  try {
    return localStorage.getItem(RELATIONSHIPS_KEY) === "1";
  } catch {
    return false;
  }
}

function storeRelationships(show: boolean): void {
  try {
    localStorage.setItem(RELATIONSHIPS_KEY, show ? "1" : "0");
  } catch {
    // Storage can be blocked; the choice then lasts for this panel only.
  }
}

interface LinkRow {
  edge: LinkGraphEdge;
  node: LinkGraphNode;
}

export function ArtefactLinksPanel({
  projectId,
  artefactType,
  artefactId,
  refreshToken = 0,
  onChanged,
  actions,
  changeRequest,
  hideStructuralLinks = false,
  compact = false,
  hideLinkedTypes,
  collapsedTypes,
  showRelationships: showRelationshipsDefault,
  api = artefactLinksApi,
}: {
  /** The project the page is in; `undefined` for an organisation-owned record. */
  projectId: string | undefined;
  /** The registered artefact type of the page's record (`"decision"`, `"requirement"`, …). */
  artefactType: string;
  artefactId: string;
  /** Change to make the panel reload (e.g. after the page changed something that affects links). */
  refreshToken?: number;
  /** Called after a link is added or removed, so the page can refresh anything derived from links. */
  onChanged?: () => void;
  /** Page-supplied controls shown beside "Add link" (e.g. a Supersede action). A function
   * receives `reload`, to refresh the panel after the control changed a link. */
  actions?: ReactNode | ((controls: { reload: () => void }) => ReactNode);
  /** Set when link changes must go through a change request (approved requirement, locked project). */
  changeRequest?: LinksChangeRequestMode;
  /** Leave out untyped structural links (an action's membership of a requirement) for a page that
   * already lists them in a section of its own, so the same record is not shown twice. */
  hideStructuralLinks?: boolean;
  /** Render without card chrome, with a caption-sized title and icon buttons, for a panel inside another card. */
  compact?: boolean;
  /** Artefact types whose links are left out of the list (still part of the trace). */
  hideLinkedTypes?: readonly string[];
  /** Artefact types whose group starts collapsed; opening or closing a group is the viewer's choice from then on. */
  collapsedTypes?: readonly string[];
  /** Start with the relationship labels shown (default: the viewer's remembered choice, else hidden). */
  showRelationships?: boolean;
  api?: ArtefactLinksApi;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  // Inside a detail page's aside the card and the title belong to the aside (its tab strip), not to this panel.
  const inAside = useInDetailAside();
  const [graph, setGraph] = useState<LinkGraph | null>(null);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [adding, setAdding] = useState(false);
  const [tracing, setTracing] = useState(false);
  const [removing, setRemoving] = useState<LinkRow | null>(null);
  const [removeReason, setRemoveReason] = useState("");
  // The viewer's explicit open/close per record type; a type not in here follows `collapsedTypes`.
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  // View options. `compact` is a per-panel default the viewer can flip; the relationship choice is remembered.
  const [compactView, setCompactView] = useState(compact);
  const [showRelationships, setShowRelationships] = useState(showRelationshipsDefault ?? readStoredRelationships());
  function chooseRelationships(next: boolean) {
    setShowRelationships(next);
    storeRelationships(next);
  }

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    api.graph(projectId, artefactType, artefactId)
      .then((result) => {
        if (!active) return;
        setGraph(result);
        setFailed(false);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType, artefactId, refreshToken, reload]);

  const groups = useMemo(() => {
    if (!graph) return [];
    const nodes = new Map(graph.nodes.map((n) => [`${n.type}:${n.id}`, n]));
    const byLabel = new Map<string, LinkRow[]>();
    const typeOf = new Map<string, string>();
    for (const edge of graph.edges) {
      if (hideStructuralLinks && edge.link_type_id === null) continue;
      const node = nodes.get(`${edge.to_type}:${edge.to_id}`);
      if (!node || hideLinkedTypes?.includes(node.type)) continue;
      byLabel.set(node.type_label, [...(byLabel.get(node.type_label) ?? []), { edge, node }]);
      typeOf.set(node.type_label, node.type);
    }
    return [...byLabel]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, rows]) => {
        const sorted = rows.sort(
          (a, b) => (a.edge.phrase ?? "").localeCompare(b.edge.phrase ?? "") || a.node.label.localeCompare(b.node.label),
        );
        // The rows of one relationship, in order, under one label.
        const phrases: { phrase: string | null; rows: LinkRow[] }[] = [];
        for (const row of sorted) {
          const last = phrases[phrases.length - 1];
          if (last && last.phrase === row.edge.phrase) last.rows.push(row);
          else phrases.push({ phrase: row.edge.phrase, rows: [row] });
        }
        return { label, type: typeOf.get(label) ?? label, rows: sorted, phrases };
      });
  }, [graph, hideStructuralLinks, hideLinkedTypes]);

  function changed() {
    setReload((n) => n + 1);
    onChanged?.();
  }

  async function removeLink(row: LinkRow) {
    if (!projectId) return;
    const reason = removeReason.trim();
    setRemoving(null);
    try {
      if (changeRequest) {
        await changeRequest.onProposeRemove(row.edge.id, reason);
      } else {
        await api.remove(projectId, artefactType, artefactId, row.edge.id);
        showToast(strings.artefactLinks.removed);
      }
      changed();
    } catch (err) {
      showToast(toErrorMessage(err, strings.artefactLinks.removeFailed), "error");
    }
  }

  if (!projectId) {
    return (
      <section className={compactView ? "stack artefact-links--compact" : inAside ? "stack" : "card stack"} aria-label={strings.artefactLinks.title}>
        {!inAside && <h2 className="artefact-links__title">{strings.artefactLinks.title}</h2>}
        <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.orgScopedNote}</p>
        {actions && <div className="row">{typeof actions === "function" ? actions({ reload: changed }) : actions}</div>}
      </section>
    );
  }

  // Changing links on a locked record goes through a change request, which anyone allowed to link it at all may propose.
  const canLink = (changeRequest ? graph?.can_propose : graph?.can_link) ?? false;
  const viewOptions = (
    <AddPopoverButton label={strings.artefactLinks.viewOptions} icon={SlidersHorizontal} size={compactView ? "sm" : "md"}>
      {() => (
        <div className="stack" style={{ gap: "var(--space-3)" }}>
          <label className="checkbox-label">
            <input type="checkbox" aria-label={strings.artefactLinks.viewCompact} checked={compactView} onChange={(e) => setCompactView(e.target.checked)} />
            <span>{strings.artefactLinks.viewCompact}</span>
          </label>
          <label className="checkbox-label">
            <input type="checkbox" aria-label={strings.artefactLinks.viewRelationships} checked={showRelationships} onChange={(e) => chooseRelationships(e.target.checked)} />
            <span className="stack" style={{ gap: "0.15rem" }}>
              <span>{strings.artefactLinks.viewRelationships}</span>
              <span className="text-muted" style={{ fontSize: "0.78rem" }}>{strings.artefactLinks.viewRelationshipsHint}</span>
            </span>
          </label>
        </div>
      )}
    </AddPopoverButton>
  );
  return (
    <section className={compactView ? "stack artefact-links--compact" : inAside ? "stack" : "card stack"} aria-label={strings.artefactLinks.title}>
      <div className={`row artefact-links__header${inAside ? " artefact-links__header--untitled" : ""}`}>
        {!inAside && <h2 className="artefact-links__title">{strings.artefactLinks.title}</h2>}
        {/* One structure and one order for both layouts (Add, Trace, then View options at the end), so the
            buttons do not move when the layout flips and the View options popover stays open. */}
        <div className="row artefact-links__buttons">
          {canLink && (
            compactView ? (
              <button
                className="btn btn-sm btn-icon" aria-label={strings.artefactLinks.addLink} title={strings.artefactLinks.addLink}
                aria-haspopup="dialog" onClick={() => setAdding(true)}
              >
                <Plus aria-hidden="true" />
              </button>
            ) : (
              <button className="btn btn-primary" onClick={() => setAdding(true)}>
                <Plus /> {strings.artefactLinks.addLink}
              </button>
            )
          )}
          {(compactView ? graph !== null : groups.length > 0) && (
            compactView ? (
              <button
                className="btn btn-sm btn-icon" aria-label={strings.artefactLinks.traceButton} title={strings.artefactLinks.traceButton}
                aria-haspopup="dialog" onClick={() => setTracing(true)}
              >
                <GitBranch aria-hidden="true" />
              </button>
            ) : (
              <button className="btn" onClick={() => setTracing(true)}>
                <GitBranch /> {strings.artefactLinks.traceButton}
              </button>
            )
          )}
          {viewOptions}
        </div>
      </div>
      {actions && canLink && (
        <div className="row artefact-links__actions">
          {typeof actions === "function" ? actions({ reload: changed }) : actions}
        </div>
      )}

      {failed ? (
        <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.loadError}</p>
      ) : graph === null ? (
        <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.loading}</p>
      ) : groups.length === 0 ? (
        <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.none}</p>
      ) : (
        groups.map((group) => {
          const isCollapsed = collapsed[group.type] ?? (collapsedTypes?.includes(group.type) ?? false);
          const listId = `artefact-links-${artefactId}-${group.type}`;
          return (
            <div key={group.label} className="stack" style={{ gap: "var(--space-2)" }}>
              <div className="row artefact-links__group-row">
                <h3 className="artefact-links__group">
                  <button
                    type="button" className="artefact-links__toggle" aria-expanded={!isCollapsed} aria-controls={listId}
                    onClick={() => setCollapsed((current) => ({ ...current, [group.type]: !isCollapsed }))}
                  >
                    {isCollapsed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
                    {group.label}
                  </button>
                </h3>
                {(group.rows.length > 1 || isCollapsed) && (
                  <span className="artefact-links__count" aria-label={strings.artefactLinks.groupCount(group.rows.length)}>{group.rows.length}</span>
                )}
              </div>
              <div id={listId} className="stack artefact-links__phrases" hidden={isCollapsed}>
                {(showRelationships ? group.phrases : [{ phrase: null, rows: [...group.rows].sort((a, b) => a.node.label.localeCompare(b.node.label)) }]).map((entry) => (
                  <div key={entry.phrase ?? ""} className="stack artefact-links__phrase">
                    {showRelationships && (
                      <span className="artefact-links__phrase-label">
                        {entry.phrase ?? strings.artefactLinks.untyped}
                        {entry.rows.length > 1 && <span className="artefact-links__count" aria-label={strings.artefactLinks.groupCount(entry.rows.length)}>{entry.rows.length}</span>}
                      </span>
                    )}
                    <ul className="artefact-links__list">
                      {entry.rows.map((row) => (
                        <LinkRowView
                          key={row.edge.id}
                          row={row}
                          currentProjectId={projectId}
                          canRemove={canLink && !row.edge.dedicated}
                          onRemove={() => {
                            setRemoveReason("");
                            setRemoving(row);
                          }}
                        />
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          );
        })
      )}
      {graph && graph.hidden_count > 0 && (
        <p className="text-muted artefact-links__note">{strings.artefactLinks.hiddenNote(graph.hidden_count)}</p>
      )}
      {graph && graph.unavailable_count > 0 && (
        <p className="text-muted artefact-links__note">{strings.artefactLinks.unavailableNote(graph.unavailable_count)}</p>
      )}
      {graph?.truncated && <p className="text-muted artefact-links__note">{strings.artefactLinks.truncatedNote}</p>}

      {adding && (
        <AddArtefactLinkModal
          projectId={projectId}
          artefactType={artefactType}
          artefactId={artefactId}
          api={api}
          changeRequest={changeRequest}
          onAdded={() => {
            setAdding(false);
            changed();
          }}
          onClose={() => setAdding(false)}
        />
      )}
      {tracing && graph && (
        <LinkTraceModal
          projectId={projectId}
          artefactType={artefactType}
          artefactId={artefactId}
          rootLabel={graph.root.label}
          api={api}
          onClose={() => setTracing(false)}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={strings.artefactLinks.removeTitle}
          message={
            changeRequest ? (
              <span className="stack" style={{ gap: "var(--space-3)" }}>
                <span>{strings.artefactLinks.removeConfirmViaChangeRequest}</span>
                <TextAreaField helpNotNeeded
                  label={strings.artefactLinks.reasonLabel}
                  value={removeReason}
                  onChange={setRemoveReason}
                  rows={2}
                />
              </span>
            ) : (
              strings.artefactLinks.removeConfirm
            )
          }
          confirmLabel={changeRequest ? strings.artefactLinks.removeActionViaChangeRequest : strings.artefactLinks.removeAction}
          confirmDisabled={!!changeRequest && !removeReason.trim()}
          onConfirm={() => void removeLink(removing)}
          onCancel={() => setRemoving(null)}
        />
      )}
    </section>
  );
}

/** One link: phrase, record (linked to its page), status, project, flags, and remove. */
function LinkRowView({
  row,
  currentProjectId,
  canRemove,
  onRemove,
}: {
  row: LinkRow;
  currentProjectId: string;
  canRemove: boolean;
  onRemove: () => void;
}) {
  const strings = useStrings();
  const { edge, node } = row;
  const phrase = edge.phrase ?? strings.artefactLinks.untyped;
  return (
    <ItemRow
      as="li"
      className="artefact-links__row"
      title={phrase}
      actions={canRemove && (
        <button
          className="btn btn-danger btn-sm btn-icon"
          title={strings.artefactLinks.removeAction}
          aria-label={strings.artefactLinks.removeLabel(phrase, node.label)}
          onClick={onRemove}
        >
          <Trash2 />
        </button>
      )}
    >
      {/* The record's own metadata (status, project, warning) may wrap below its title; the Remove action may not. */}
      <div className="artefact-links__summary" data-wrap-ok>
        <LinkedRecordSummary edge={edge} node={node} currentProjectId={currentProjectId} layout="list" />
      </div>
    </ItemRow>
  );
}
