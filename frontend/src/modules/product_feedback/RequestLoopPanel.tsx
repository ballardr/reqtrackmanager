/**
 * Module: modules/product_feedback/RequestLoopPanel
 *
 * Closing the loop on a delivered or declined request: each requester, the channel they asked through (so you know
 * how to reach them), a "Told" checkbox, the date it was
 * recorded and an optional note, plus "Mark all told" for the ones still open. Nothing is sent to anyone: this records
 * that someone told them (the note says how), so the open-loop badge and list can show who is still waiting.
 *
 * Requesters come from the request's demand, merged duplicates' included, so a person who asked twice is told once.
 * A requester the viewer may not see still gets a row (they are owed an answer) without a name. Telling is
 * recorded only for a delivered or declined request; before then the panel says so.
 */
import { useState } from "react";

import { DetailCard } from "../../components/DetailCard";
import { CheckboxField, TextField } from "../../components/FormFields";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import type { CloseTheLoop, LoopRequester } from "./types";

const key = (r: LoopRequester) => `${r.artefact_type}:${r.id}`;

/**
 * @param loop The request's close-the-loop state.
 * @param onInformed Records (or withdraws) that the given requesters were told, with the note; rejects with the server's message.
 */
export function RequestLoopPanel({
  loop, onInformed,
}: {
  loop: CloseTheLoop;
  onInformed: (parties: { artefact_type: string; id: string }[], informed: boolean, note: string) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  const open = loop.requesters.filter((r) => !r.informed);
  return (
    <DetailCard heading="Closing the loop">
      {loop.status === "declined" && loop.decline_reason && (
        <p style={{ margin: 0 }}><span className="text-muted">Reason given: </span>{loop.decline_reason}</p>
      )}
      {loop.requesters.length === 0 ? (
        <p className="text-muted">No one is recorded as having asked for this, so there is no one to tell.</p>
      ) : (
        <>
          <p style={{ margin: 0 }}>
            {loop.open_count === 0 ? "Everyone who asked has been told." : `${loop.open_count} of ${loop.requesters.length} still to be told.`}
          </p>
          {loop.can_record && (
            <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)", flexWrap: "wrap" }}>
              <TextField
                help={PRODUCT_FEEDBACK_HELP.informedNote} label="How they were told" ariaLabel="How they were told"
                value={note} onChange={setNote}
              />
              <button
                className="btn" disabled={open.length === 0}
                onClick={() => void onInformed(open.map((r) => ({ artefact_type: r.artefact_type, id: r.id })), true, note)}
              >
                Mark all told
              </button>
            </div>
          )}
          <table className="table" aria-label="Requesters to tell">
            <thead><tr><th>Requester</th><th>Channel</th><th>Told</th><th>When</th><th>Note</th></tr></thead>
            <tbody>
              {loop.requesters.map((r) => {
                const name = r.hidden ? "A requester you can’t view" : r.label ?? "";
                return (
                  <tr key={key(r)}>
                    <td>{name}</td>
                    <td className="text-muted">{r.channel ? r.channel.name : r.via_engagement ? "Engagement" : "–"}</td>
                    <td>
                      <CheckboxField
                        helpNotNeeded label="" ariaLabel={`Told ${name}`} checked={r.informed} disabled={!loop.can_record}
                        onChange={(checked) => void onInformed([{ artefact_type: r.artefact_type, id: r.id }], checked, note)}
                      />
                    </td>
                    <td>{r.informed_at ? new Date(r.informed_at).toLocaleDateString() : "–"}</td>
                    <td className="text-muted">{r.note || "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
      {!loop.can_record && <p className="text-muted">Telling requesters can be recorded once the request is delivered or declined.</p>}
    </DetailCard>
  );
}
