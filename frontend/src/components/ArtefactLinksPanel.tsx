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
 * - Remove a link behind a Tier-1 confirmation; route through a change request when
 *   the page says links are locked (`changeRequest`).
 *
 * Design decisions:
 * - `projectId` is undefined for an organisation-owned record; links are
 *   project-scoped, so the panel then shows a note instead of an add control.
 * - Other modules' statuses are shown through their registered label maps
 *   (`getArtefactStatusLabel`); a status with no label shows no badge, never the raw value.
 * - API calls are injectable (`api`) so stories and tests need no network.
 */
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { artefactLinksApi, type ArtefactLinksApi, type LinkGraph, type LinkGraphEdge, type LinkGraphNode } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { getArtefactPath, getArtefactStatusLabel } from "../modules/artefactPaths";
import { AddArtefactLinkModal, type LinksChangeRequestMode } from "./AddArtefactLinkModal";
import { ConfirmDialog } from "./ConfirmDialog";

export type { LinksChangeRequestMode } from "./AddArtefactLinkModal";

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
  api?: ArtefactLinksApi;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [graph, setGraph] = useState<LinkGraph | null>(null);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<LinkRow | null>(null);
  const [removeReason, setRemoveReason] = useState("");

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
    for (const edge of graph.edges) {
      if (hideStructuralLinks && edge.link_type_id === null) continue;
      const node = nodes.get(`${edge.to_type}:${edge.to_id}`);
      if (!node) continue;
      byLabel.set(node.type_label, [...(byLabel.get(node.type_label) ?? []), { edge, node }]);
    }
    return [...byLabel]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, rows]) => ({
        label,
        rows: rows.sort(
          (a, b) => (a.edge.phrase ?? "").localeCompare(b.edge.phrase ?? "") || a.node.label.localeCompare(b.node.label),
        ),
      }));
  }, [graph, hideStructuralLinks]);

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
      <section className="card stack" aria-label={strings.artefactLinks.title}>
        <h2 className="artefact-links__title">{strings.artefactLinks.title}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.orgScopedNote}</p>
        {actions && <div className="row">{typeof actions === "function" ? actions({ reload: changed }) : actions}</div>}
      </section>
    );
  }

  const canManage = graph?.can_manage ?? false;
  return (
    <section className="card stack" aria-label={strings.artefactLinks.title}>
      <div className="row artefact-links__header">
        <h2 className="artefact-links__title">{strings.artefactLinks.title}</h2>
        {canManage && (
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            <Plus size={14} /> {strings.artefactLinks.addLink}
          </button>
        )}
      </div>
      {actions && canManage && (
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
        groups.map((group) => (
          <div key={group.label} className="stack" style={{ gap: "0.35rem" }}>
            <h3 className="artefact-links__group">{group.label}</h3>
            <ul className="artefact-links__list">
              {group.rows.map((row) => (
                <LinkRowView
                  key={row.edge.id}
                  row={row}
                  currentProjectId={projectId}
                  canRemove={canManage && !row.edge.dedicated}
                  onRemove={() => {
                    setRemoveReason("");
                    setRemoving(row);
                  }}
                />
              ))}
            </ul>
          </div>
        ))
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
      {removing && (
        <ConfirmDialog
          title={strings.artefactLinks.removeTitle}
          message={
            changeRequest ? (
              <span className="stack" style={{ gap: "0.5rem" }}>
                <span>{strings.artefactLinks.removeConfirmViaChangeRequest}</span>
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.artefactLinks.reasonLabel}
                  <textarea
                    className="input" rows={2} aria-label={strings.artefactLinks.reasonLabel}
                    value={removeReason} onChange={(e) => setRemoveReason(e.target.value)}
                  />
                </label>
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
  const path = getArtefactPath(node.type, node.project_id ?? currentProjectId, node.id);
  const statusLabel = getArtefactStatusLabel(node.type, node.status);
  const elsewhere = node.project_id !== null && node.project_id !== currentProjectId;
  return (
    <li className="artefact-links__row">
      <span className="badge">{phrase}</span>
      <span className="artefact-links__target">{path ? <Link to={path}>{node.label}</Link> : node.label}</span>
      {statusLabel && <span className="badge badge--muted">{statusLabel}</span>}
      {node.is_archived && <span className="badge badge--muted">{strings.artefactLinks.archivedBadge}</span>}
      {elsewhere && (
        <Link className="badge badge--info" to={`/projects/${node.project_id}`}>
          {strings.artefactLinks.otherProjectBadge(node.project_name ?? "")}
        </Link>
      )}
      {!edge.nesting_permitted && (
        <span className="badge badge--warning" title={strings.artefactLinks.notPermittedExplanation}>
          {strings.artefactLinks.notPermitted}
        </span>
      )}
      {canRemove && (
        <button
          className="btn btn-danger artefact-links__remove"
          title={strings.artefactLinks.removeAction}
          aria-label={strings.artefactLinks.removeLabel(phrase, node.label)}
          onClick={onRemove}
        >
          <Trash2 size={14} />
        </button>
      )}
    </li>
  );
}
