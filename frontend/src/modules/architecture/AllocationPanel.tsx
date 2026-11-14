/**
 * Module: modules/architecture/AllocationPanel
 *
 * The allocation card shared by the two places allocation is read: a requirement's "Architecture" card (the elements it is
 * allocated to) and an element's "Requirements" card (the requirements allocated to it). Each lists what is allocated, what
 * the placement suggests (Accept, Accept all, Dismiss) and what was dismissed (Restore).
 *
 * Design decisions:
 * - One component for both ends, because the two cards differ only in which side of the pair is the other record;
 *   a screen fixes the side with `perspective`.
 * - Suggestions are computed by the server and become links only when accepted here (`projectAllocationApi.accept`);
 *   the panel never writes a link itself.
 * - The card draws nothing while the record has no allocation, no suggestion and no dismissal, so a requirement of a project
 *   that does not use the architecture is unchanged. Allocating by hand stays in the Links panel.
 * - A person who cannot change links reads the lists and sees no buttons (`can_manage` from the server).
 * - What "suggested" means is explained in the `(?)` tooltip, never in permanent text.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { FieldHelp } from "../../components/FieldHelp";
import { RecordCode } from "../../components/RecordCode";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectAllocationApi } from "./api";
import { ARCHITECTURE_HELP } from "./help";
import {
  ARCHITECTURE_STATUS_LABEL,
  ARCHITECTURE_STATUS_TONE,
  type AllocationPair,
  type AllocationView,
} from "./types";

/** Which record the card is for: the requirement's own card lists elements, the element's lists requirements. */
export type AllocationPerspective = { kind: "requirement"; requirementId: string } | { kind: "element"; elementId: string };

const pairKey = (pair: AllocationPair) => `${pair.requirement.id}:${pair.element.id}`;
const pairBody = (pair: AllocationPair) => ({ requirement_id: pair.requirement.id, element_id: pair.element.id });

/** The other record of a pair as a link with its code and name. */
function OtherEnd({ projectId, perspective, pair }: { projectId: string; perspective: AllocationPerspective; pair: AllocationPair }) {
  if (perspective.kind === "requirement") {
    return (
      <Link to={`/projects/${projectId}/modules/architecture/elements/${pair.element.id}`}>
        <span className="text-muted"><ScopedRecordCode record={pair.element} /></span> {pair.element.name}
      </Link>
    );
  }
  return (
    <Link to={`/projects/${projectId}/requirements/${pair.requirement.id}`}>
      <span className="text-muted"><RecordCode code={pair.requirement.unique_code} /></span> {pair.requirement.name}
    </Link>
  );
}

/**
 * @param projectId The project of the record the card is on.
 * @param perspective The requirement or element the card is for.
 * @param refreshToken Bumped by the page when something that could change allocation (its links) changed; re-reads the card.
 */
export function AllocationPanel({
  projectId, perspective, refreshToken = 0,
}: { projectId: string; perspective: AllocationPerspective; refreshToken?: number }) {
  const { showToast } = useToast();
  const [view, setView] = useState<AllocationView | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const { kind } = perspective;
  const recordId = perspective.kind === "requirement" ? perspective.requirementId : perspective.elementId;
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let live = true;
    const api = projectAllocationApi(projectId);
    const read = kind === "requirement" ? api.forRequirement(recordId) : api.forElement(recordId);
    read.then((next) => { if (live) setView(next); }).catch(() => { if (live) setView(null); });
    return () => { live = false; };
  }, [projectId, recordId, kind, refreshToken, reloadKey]);

  /** Runs one mutation with feedback, then re-reads the card. */
  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    try {
      showToast(await action());
    } catch (err) {
      showToast(toErrorMessage(err, "The allocation could not be changed."), "error");
    } finally {
      setBusy(false);
      reload();
    }
  };

  const accept = (pairs: AllocationPair[]) => run(async () => {
    const result = await projectAllocationApi(projectId).accept(pairs.map(pairBody));
    if (result.failed.length > 0) {
      throw new Error(`${result.accepted} allocated. ${result.failed.length} could not be allocated: ${result.failed[0].reason}`);
    }
    return result.accepted === 1 ? "Allocation added." : `${result.accepted} allocations added.`;
  });
  const dismiss = (pair: AllocationPair) => run(async () => {
    await projectAllocationApi(projectId).dismiss(pairBody(pair));
    return "Suggestion dismissed.";
  });
  const restore = (pair: AllocationPair) => run(async () => {
    await projectAllocationApi(projectId).restore(pairBody(pair));
    return "Suggestion restored.";
  });

  if (view === null || (view.allocated.length + view.suggested.length + view.dismissed.length === 0)) return null;
  const heading = perspective.kind === "requirement" ? "Architecture" : "Requirements";
  const manage = view.can_manage;
  const row = (pair: AllocationPair, actions?: ReactNode, status = true) => (
    <li key={pairKey(pair)} className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
      <span>
        <OtherEnd projectId={projectId} perspective={perspective} pair={pair} />{" "}
        {status && perspective.kind === "requirement" && (
          <Badge tone={ARCHITECTURE_STATUS_TONE[pair.element.status]}>{ARCHITECTURE_STATUS_LABEL[pair.element.status]}</Badge>
        )}
      </span>
      {actions}
    </li>
  );

  return (
    <DetailCard heading={heading}>
      {view.allocated.length > 0 && (
        <div className="stack">
          <h3 className="artefact-links__group">Allocated</h3>
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
            {view.allocated.map((pair) => row(pair))}
          </ul>
        </div>
      )}
      {view.suggested.length > 0 && (
        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <h3 className="artefact-links__group">
              Suggested <FieldHelp label="Suggested" help={ARCHITECTURE_HELP.allocationSuggested} />
            </h3>
            {manage && view.suggested.length > 1 && (
              <button className="btn" disabled={busy} onClick={() => void accept(view.suggested)}>Accept all</button>
            )}
          </div>
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
            {view.suggested.map((pair) => row(pair, manage && (
              <span className="row">
                <button className="btn" disabled={busy} onClick={() => void accept([pair])}>Accept</button>
                <button className="btn" disabled={busy} onClick={() => void dismiss(pair)}>Dismiss</button>
              </span>
            )))}
          </ul>
        </div>
      )}
      {view.dismissed.length > 0 && (
        <div className="stack">
          <h3 className="artefact-links__group">Dismissed</h3>
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
            {view.dismissed.map((pair) => row(pair, manage && (
              <button className="btn" disabled={busy} onClick={() => void restore(pair)}>Restore</button>
            ), false))}
          </ul>
        </div>
      )}
    </DetailCard>
  );
}
