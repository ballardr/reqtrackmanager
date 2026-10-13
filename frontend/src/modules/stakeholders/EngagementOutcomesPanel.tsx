/**
 * Module: modules/stakeholders/EngagementOutcomesPanel
 *
 * The Pain Points, Needs and Open Questions an engagement (or one of its
 * research findings) raised or answered — the trace from a contact to the
 * backlog (Phase 0 addendum, item 20). One component for both holders: the
 * caller passes the matching `OutcomeApi`. A row names the kind and target type
 * through their label maps and links to the target's own page through the
 * generic `getArtefactPath`, so no other module is imported. Only an Open
 * Question can be answered. Removal is a tier-1 confirm and only the link is
 * removed.
 *
 * Adding picks a kind, a type and a record of that type from the project; a
 * type whose module is off simply offers no records. Three fields is a lot for a
 * page that has several lists, so the form lives in a `Modal` behind a (+) button
 * and the list is a row of chips.
 */
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { RecordFieldGroup } from "../../components/RecordDetailParts";
import { RemovableItemList } from "../../components/RemovableItemList";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { getArtefactPath } from "../artefactPaths";
import type { OutcomeApi } from "./api";
import type { EngagementOutcome, OutcomeKind, OutcomeTarget, OutcomeTargetType } from "./types";
import { OUTCOME_KIND_LABEL, OUTCOME_TARGET_TYPE_LABEL } from "./types";

const KIND_OPTIONS = Object.entries(OUTCOME_KIND_LABEL).map(([value, label]) => ({ value, label }));
const ALL_TYPE_OPTIONS = Object.entries(OUTCOME_TARGET_TYPE_LABEL).map(([value, label]) => ({ value, label }));
const ANSWERABLE_TYPE_OPTIONS = ALL_TYPE_OPTIONS.filter((o) => o.value === "open_question");

/** Label of a target type the backend reports; a type this build doesn't know reads as a generic record. */
function targetTypeLabel(targetType: string): string {
  return OUTCOME_TARGET_TYPE_LABEL[targetType as OutcomeTargetType] ?? "Record";
}

export function EngagementOutcomesPanel({
  heading = "Raised and answered",
  projectId,
  holderId,
  api,
  loadTargets,
  onChanged,
}: {
  heading?: string;
  projectId: string;
  /** The engagement or finding the outcomes belong to. */
  holderId: string;
  api: OutcomeApi;
  /** The project's records of a type, for the picker. */
  loadTargets: (targetType: OutcomeTargetType) => Promise<OutcomeTarget[]>;
  /** Called after an outcome is added or removed, so a page's Links panel can refresh. */
  onChanged?: () => void;
}) {
  const { showToast } = useToast();
  const [outcomes, setOutcomes] = useState<EngagementOutcome[] | null>(null);
  const [kind, setKind] = useState<OutcomeKind>("raised");
  const [targetType, setTargetType] = useState<OutcomeTargetType>("pain_point");
  const [targets, setTargets] = useState<OutcomeTarget[]>([]);
  const [picked, setPicked] = useState("");
  const [removing, setRemoving] = useState<EngagementOutcome | null>(null);
  const [adding, setAdding] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    api.list(projectId, holderId).then((rows) => active && setOutcomes(rows)).catch(() => active && setOutcomes([]));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, holderId, refresh]);

  useEffect(() => {
    let active = true;
    loadTargets(targetType).then((rows) => active && setTargets(rows)).catch(() => active && setTargets([]));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetType]);

  const typeOptions = kind === "answered" ? ANSWERABLE_TYPE_OPTIONS : ALL_TYPE_OPTIONS;
  const linked = new Set((outcomes ?? []).filter((o) => o.kind === kind).map((o) => o.target_id));
  const candidates = targets.filter((t) => !linked.has(t.id)).map((t) => ({ value: t.id, label: t.label }));

  function changeKind(next: OutcomeKind) {
    setKind(next);
    setPicked("");
    if (next === "answered") setTargetType("open_question");
  }

  async function mutate(action: () => Promise<unknown>, success: string, failure: string) {
    try {
      await action();
      showToast(success);
      setRefresh((n) => n + 1);
      onChanged?.();
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
    }
  }

  if (outcomes === null) return null;

  return (
    <RecordFieldGroup
      label={heading}
      gap="0.35rem"
      action={
        <button
          type="button" className="btn btn-sm btn-icon" aria-label={`Add to ${heading}`} title={`Add to ${heading}`}
          aria-haspopup="dialog" onClick={() => setAdding(true)}
        >
          <Plus size={14} aria-hidden="true" />
        </button>
      }
    >
      {outcomes.length === 0 ? (
        <span className="text-muted">Nothing raised or answered yet.</span>
      ) : (
        <RemovableItemList
          items={outcomes.map((o) => {
            const path = getArtefactPath(o.target_type, projectId, o.target_id);
            return {
              id: o.link_id,
              content: <span>{OUTCOME_KIND_LABEL[o.kind]} · {targetTypeLabel(o.target_type)}: {path ? <Link to={path}>{o.label}</Link> : o.label}</span>,
              removeLabel: `Remove ${o.label}`,
            };
          })}
          onRemove={(id) => setRemoving(outcomes.find((o) => o.link_id === id) ?? null)}
          noun="outcomes"
          modalTitle={heading}
        />
      )}
      {adding && (
        <Modal title="Record an outcome" onClose={() => setAdding(false)}>
          <div className="stack">
            <LabeledSelect label="Outcome kind" value={kind} placeholder={null} onChange={(v) => changeKind(v as OutcomeKind)} options={KIND_OPTIONS} />
            <LabeledSelect
              label="Outcome type" value={targetType} placeholder={null}
              onChange={(v) => { setTargetType(v as OutcomeTargetType); setPicked(""); }} options={typeOptions}
            />
            <LabeledSelect label="Outcome record" value={picked} onChange={setPicked} options={candidates} placeholder="Choose…" />
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setAdding(false)}>Cancel</button>
              <button
                className="btn btn-primary" disabled={!picked}
                onClick={() => {
                  const id = picked;
                  setPicked("");
                  setAdding(false);
                  void mutate(() => api.add(projectId, holderId, kind, targetType, id), "Outcome recorded.", "Could not record the outcome.");
                }}
              >
                Add outcome
              </button>
            </div>
          </div>
        </Modal>
      )}
      {removing && (
        <ConfirmDialog
          title={`Remove ${removing.label}?`}
          message="The two records stay; only the link between them is removed."
          confirmLabel="Remove"
          onConfirm={() => {
            const outcome = removing;
            setRemoving(null);
            void mutate(() => api.remove(projectId, holderId, outcome.link_id), "Outcome removed.", "Could not remove the outcome.");
          }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </RecordFieldGroup>
  );
}
