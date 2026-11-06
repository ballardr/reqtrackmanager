/**
 * Module: modules/product_feedback/RequestDemandPanel
 *
 * Who asked for a request: the distinct requesters (Stakeholders and Personas, including those reached through linked
 * Engagements and through requests merged into it) with the weight each carries and where it comes from (an Influence
 * level, a Persona's own weight, or this or a parent project's override of it), the Engagements it was raised in,
 * the requests merged into it and the merge history. Requesters are authored with the generic "Requested by" link in
 * the Links panel or with this panel's own Add requester button (the same field the request forms use).
 *
 * Requesters arrive a page at a time (heaviest first): a request can be asked for by hundreds, so the table shows
 * "Showing N of M" with a Show more button, and the headline count and weight always cover every requester.
 *
 * Each requester's channel (how they asked) is shown beside them: a triager can set it from the pencil, and a
 * requester reached only through an Engagement reads as an Engagement with nothing to set.
 *
 * Demand is shown beside the score and never mixed into it. A requester the viewer may not see is counted but not
 * named. The kind of a requester is read from its artefact type, so this panel names no other module.
 */
import { X } from "lucide-react";
import { Link } from "react-router-dom";

import { DetailCard } from "../../components/DetailCard";
import { Tooltip } from "../../components/Tooltip";
import { getArtefactPath } from "../../modules/artefactPaths";
import { demandText } from "./requestListState";
import { RequesterChannelEdit } from "./RequesterChannelEdit";
import { REQUEST_STATUS_LABEL, REQUESTER_WEIGHT_SOURCE_LABEL } from "./types";
import type { Demand, Requester, RequestMerge } from "./types";
import type { ListChoice } from "./useFeedbackLists";

/** `stakeholder_group` becomes "Stakeholder group". */
function kindLabel(artefactType: string): string {
  const text = artefactType.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatWeight(weight: number): string {
  return Number.isInteger(weight) ? String(weight) : weight.toFixed(1);
}

/**
 * The red ✕ that removes a requester or an Engagement. Always shown, so every row reads the same: where the request
 * has no link of its own to remove it stays dimmed (`aria-disabled`, still focusable) and its tooltip says why and
 * what to do instead. The explanation is a shared `Tooltip`, never a native `title`.
 *
 * @param name What it removes, for the accessible name.
 * @param label The tooltip: what the button does, or why it cannot.
 * @param onClick Called when it can act; omit to dim it.
 */
function RemoveButton({ name, label, onClick }: { name: string; label: string; onClick?: () => void }) {
  return (
    <Tooltip label={label} wrap>
      <button
        type="button" className="btn btn-sm btn-icon btn-danger" aria-label={name} aria-disabled={onClick ? undefined : true}
        onClick={onClick}
      >
        <X />
      </button>
    </Tooltip>
  );
}

/** Why a requester has no ✕ of its own, and what removes it. */
function whyNotRemovable(r: Requester): string {
  if (r.from_merge) return "Counted from a request merged into this one. Undo that merge to remove them.";
  if (r.via_engagement) return "Reached through an Engagement this request was raised in. Remove that Engagement to remove them.";
  return "This request has no link of its own to them.";
}

/**
 * @param projectId The request's project (record links resolve against it).
 * @param demand The request's demand, or null while loading.
 * @param merges The request's merge history, or null while loading.
 * @param channels The channels the project offers (for the picker).
 * @param canSetChannel Whether the viewer may record how a requester asked (a triager, on an unarchived request).
 * @param onSetChannel Records (or, with null, clears) one requester's channel; rejects with the server's message.
 * @param onRemoveRequester Asks to remove a requester or an Engagement the request was raised in: given the link's id and
 *   the name to confirm with. Only the request's own links have a button; a requester reached through an Engagement
 *   or a merged duplicate is removed by removing that Engagement or undoing that merge.
 * @param onAddRequesters Opens the add-requesters dialog; the button is omitted when this is not given (no triage right).
 * @param onShowMore Loads the next page of requesters; the button shows while some are not yet loaded.
 * @param loadingMore Disables Show more while a page is on its way.
 */
export function RequestDemandPanel({
  projectId, demand, merges, channels = [], canSetChannel = false, onSetChannel, onRemoveRequester, onAddRequesters, onShowMore, loadingMore = false,
}: {
  projectId: string;
  demand: Demand | null;
  merges: RequestMerge[] | null;
  channels?: ListChoice[];
  canSetChannel?: boolean;
  onSetChannel?: (requester: Requester, channelId: string | null) => Promise<void>;
  onRemoveRequester?: (linkId: string, name: string, kind: "requester" | "engagement") => void;
  onAddRequesters?: () => void;
  onShowMore?: () => void;
  loadingMore?: boolean;
}) {
  const recordPath = (type: string, id: string) => getArtefactPath(type, projectId, id);
  return (
    <DetailCard
      heading="Demand"
      action={onAddRequesters ? <button type="button" className="btn btn-sm" onClick={onAddRequesters}>Add requester</button> : undefined}
    >
      {demand === null ? (
        <p className="text-muted">Loading…</p>
      ) : demand.requesters.length === 0 ? (
        <p className="text-muted">
          No one is recorded as having asked for this yet.{onAddRequesters ? " Use Add requester to record a Stakeholder, Persona or Engagement." : ""}
        </p>
      ) : (
        <>
          <p style={{ margin: 0 }}><strong>{demandText(demand)}</strong></p>
          <table className="table" aria-label="Requesters">
            <thead><tr><th>Requester</th><th>Kind</th><th>Weight</th><th>Channel</th><th>Via</th>{onRemoveRequester && <th><span className="sr-only">Actions</span></th>}</tr></thead>
            <tbody>
              {demand.requesters.map((r) => {
                const path = r.hidden ? null : recordPath(r.artefact_type, r.id);
                return (
                  <tr key={`${r.artefact_type}:${r.id}`}>
                    <td>{r.hidden ? <span className="text-muted">A requester you can’t view</span> : path ? <Link to={path}>{r.label}</Link> : r.label}</td>
                    <td>{kindLabel(r.artefact_type)}</td>
                    <td>
                      {formatWeight(r.effective_weight)}
                      {!r.hidden && r.weight_source && REQUESTER_WEIGHT_SOURCE_LABEL[r.weight_source] && (
                        <div className="text-muted" style={{ fontSize: "0.75rem" }}>{REQUESTER_WEIGHT_SOURCE_LABEL[r.weight_source]}</div>
                      )}
                    </td>
                    <td>
                      <span className="row" style={{ gap: "var(--space-1)", alignItems: "center" }}>
                        {r.channel ? r.channel.name : r.via_engagement ? <span className="text-muted">Engagement</span> : <span className="text-muted">Not recorded</span>}
                        {canSetChannel && onSetChannel && !r.via_engagement && (
                          <RequesterChannelEdit
                            who={r.hidden ? "a requester you can’t view" : r.label ?? ""} current={r.channel} channels={channels}
                            onSave={(channelId) => onSetChannel(r, channelId)}
                          />
                        )}
                      </span>
                    </td>
                    <td className="text-muted">
                      {[r.from_merge && "Merged duplicate", r.via_engagement && "Engagement"].filter(Boolean).join(", ") || "Direct"}
                    </td>
                    {onRemoveRequester && (
                      <td>
                        <RemoveButton
                          name={`Remove requester ${r.label ?? "you can’t view"}`}
                          label={r.link_id ? `Remove ${r.label ?? "this requester"} as a requester` : whyNotRemovable(r)}
                          onClick={r.link_id ? () => onRemoveRequester(r.link_id!, r.label ?? "this requester", "requester") : undefined}
                        />
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {demand.requesters.length < demand.requester_count && (
            <div className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
              <span className="text-muted">Showing {demand.requesters.length} of {demand.requester_count} requesters</span>
              {onShowMore && <button type="button" className="btn btn-sm" disabled={loadingMore} onClick={onShowMore}>Show more</button>}
            </div>
          )}
        </>
      )}
      {demand && demand.engagements.length > 0 && (
        <p style={{ margin: 0 }}>
          <span className="text-muted">Raised in: </span>
          {demand.engagements.map((e, i) => {
            const path = e.hidden ? null : recordPath("engagement", e.id);
            return (
              <span key={e.id}>
                {i > 0 && ", "}
                {e.hidden ? "an Engagement you can’t view" : path ? <Link to={path}>{e.label}</Link> : e.label}
                {onRemoveRequester && (
                  <span style={{ marginLeft: "var(--space-1)" }}>
                    <RemoveButton
                      name={`Remove Engagement ${e.label ?? "you can’t view"}`}
                      label={e.link_id
                        ? `Remove ${e.label ?? "this Engagement"}. People only it reached stop counting as requesters.`
                        : "Counted from a request merged into this one. Undo that merge to remove it."}
                      onClick={e.link_id ? () => onRemoveRequester(e.link_id!, e.label ?? "this Engagement", "engagement") : undefined}
                    />
                  </span>
                )}
              </span>
            );
          })}
        </p>
      )}
      {demand && demand.merged_duplicates.length > 0 && (
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span className="text-muted">Merged duplicates</span>
          <ul style={{ margin: 0 }}>
            {demand.merged_duplicates.map((d) => (
              <li key={d.id}>
                <Link to={`/projects/${projectId}/modules/product_feedback/requests/${d.id}`}>{d.unique_code} {d.title}</Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {merges && merges.length > 0 && (
        <details>
          <summary>Merge history ({merges.length})</summary>
          <table className="table" aria-label="Merge history">
            <thead><tr><th>Duplicate</th><th>Merged into</th><th>When</th><th>Why</th><th>State</th></tr></thead>
            <tbody>
              {merges.map((m) => (
                <tr key={m.id}>
                  <td>{m.duplicate.unique_code}</td>
                  <td>{m.canonical.unique_code}</td>
                  <td>{new Date(m.merged_at).toLocaleString()}</td>
                  <td style={{ whiteSpace: "pre-wrap" }}>{m.note || <span className="text-muted">—</span>}</td>
                  <td>
                    {m.active ? "Merged" : `Undone ${m.unmerged_at ? new Date(m.unmerged_at).toLocaleDateString() : ""} (back to ${REQUEST_STATUS_LABEL[m.prior_status]})`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </DetailCard>
  );
}
