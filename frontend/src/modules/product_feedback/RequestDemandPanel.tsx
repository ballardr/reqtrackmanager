/**
 * Module: modules/product_feedback/RequestDemandPanel
 *
 * Who asked for a request: the distinct requesters (Stakeholders and Personas, including those reached through linked
 * Engagements and through requests merged into it) with the weight each carries, the Engagements it was raised in,
 * the requests merged into it and the merge history. Requesters are authored with the generic "Requested by" link in
 * the Links panel, so this panel only reads; it says where to add one.
 *
 * Each requester's channel (how they asked) is shown beside them: a triager can set it from the pencil, and a
 * requester reached only through an Engagement reads as an Engagement with nothing to set.
 *
 * Demand is shown beside the score and never mixed into it. A requester the viewer may not see is counted but not
 * named. The kind of a requester is read from its artefact type, so this panel names no other module.
 */
import { Link } from "react-router-dom";

import { DetailCard } from "../../components/DetailCard";
import { getArtefactPath } from "../../modules/artefactPaths";
import { demandText } from "./requestListState";
import { RequesterChannelEdit } from "./RequesterChannelEdit";
import { REQUEST_STATUS_LABEL } from "./types";
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
 * @param projectId The request's project (record links resolve against it).
 * @param demand The request's demand, or null while loading.
 * @param merges The request's merge history, or null while loading.
 * @param channels The channels the project offers (for the picker).
 * @param canSetChannel Whether the viewer may record how a requester asked (a triager, on an unarchived request).
 * @param onSetChannel Records (or, with null, clears) one requester's channel; rejects with the server's message.
 */
export function RequestDemandPanel({
  projectId, demand, merges, channels = [], canSetChannel = false, onSetChannel,
}: {
  projectId: string;
  demand: Demand | null;
  merges: RequestMerge[] | null;
  channels?: ListChoice[];
  canSetChannel?: boolean;
  onSetChannel?: (requester: Requester, channelId: string | null) => Promise<void>;
}) {
  const recordPath = (type: string, id: string) => getArtefactPath(type, projectId, id);
  return (
    <DetailCard heading="Demand">
      {demand === null ? (
        <p className="text-muted">Loading…</p>
      ) : demand.requesters.length === 0 ? (
        <p className="text-muted">
          No one is recorded as having asked for this yet. Add a Stakeholder, Persona or Engagement with
          “Requested by” in the Links panel.
        </p>
      ) : (
        <>
          <p style={{ margin: 0 }}><strong>{demandText(demand)}</strong></p>
          <table className="table" aria-label="Requesters">
            <thead><tr><th>Requester</th><th>Kind</th><th>Weight</th><th>Channel</th><th>Via</th></tr></thead>
            <tbody>
              {demand.requesters.map((r) => {
                const path = r.hidden ? null : recordPath(r.artefact_type, r.id);
                return (
                  <tr key={`${r.artefact_type}:${r.id}`}>
                    <td>{r.hidden ? <span className="text-muted">A requester you can’t view</span> : path ? <Link to={path}>{r.label}</Link> : r.label}</td>
                    <td>{kindLabel(r.artefact_type)}</td>
                    <td>{formatWeight(r.effective_weight)}</td>
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
                  </tr>
                );
              })}
            </tbody>
          </table>
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
            <thead><tr><th>Duplicate</th><th>Merged into</th><th>When</th><th>State</th></tr></thead>
            <tbody>
              {merges.map((m) => (
                <tr key={m.id}>
                  <td>{m.duplicate.unique_code}</td>
                  <td>{m.canonical.unique_code}</td>
                  <td>{new Date(m.merged_at).toLocaleString()}</td>
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
