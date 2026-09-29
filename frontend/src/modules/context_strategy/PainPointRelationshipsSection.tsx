/**
 * Module: modules/context_strategy/PainPointRelationshipsSection
 *
 * A Pain Point's own relationships (docs/plans/module-01-context-and-
 * strategy-plan.md Phase 6/7.3): `Pain Point -> drives -> Strategy`, `->
 * motivates -> Requirement`, `-> raises -> Open Question`, `-> related to ->
 * Future State` (untyped), and `-> duplicate of -> another Pain Point` —
 * mirrors `StrategyRelationshipsSection.tsx`'s "one section owns both
 * listing and creation" shape and its `kindOptions`-driven target picker.
 *
 * **A sibling component, not a generalisation of `StrategyRelationships
 * Section.tsx`/`FutureStateRelationshipsSection.tsx` (Decided by: Agent)** —
 * checked both existing files fully first, per this phase's own brief: their
 * *substance* (which link kinds exist, which target types/pickers they
 * need, the reserved-Decision note's exact wording) genuinely diverges per
 * source artefact type, the same "per-source-artefact-type" shape
 * `service.py`'s own Phase 6 docstring establishes for the backend — only
 * the comment thread (identical shape, zero per-artefact content) qualified
 * for the `ArtefactCommentsSection` generalisation in Phase 7.2.
 *
 * **No scope-conditional target-picker restriction, unlike Strategy's/
 * Future State's own sections (Decided by: Agent) — simpler by construction,
 * not a narrower judgment call.** Pain Point has no organisation scope at
 * all (source overview §6), so there is no org-scoped-Pain-Point case whose
 * target pickers would need withholding the way an org-scoped Strategy
 * withholds `drives_requirement`/`defines_future_state`/`requires_
 * resolution_of_open_question`. Every one of Pain Point's five link kinds is
 * always offered.
 *
 * `Pain Point -> addresses -> Decision` (module docstring's reserved-
 * Decision-target relationship) has no equivalent here — §6.6 names no
 * Pain-Point-sourced relationship to Decision at all (the reserved direction
 * runs the other way, Decision -> addresses -> Pain Point), so unlike
 * `StrategyRelationshipsSection.tsx`/`FutureStateRelationshipsSection.tsx`
 * this section has no "reserved for future use" note to render.
 *
 * No dedicated supersession mechanism either — Pain Point has no version
 * table (Phase 3's own scope decision) and no `/supersessions` endpoint;
 * `duplicate_of` is a plain `PainPointLinkKind`, created through the same
 * `POST .../relationships` endpoint as every other kind here, not a special
 * one the way Strategy's/Future State's "supersedes" option is.
 */
import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";

import type { Requirement } from "../../api/types";
import { api } from "../../api/client";
import { LabeledSelect } from "../../components/LabeledSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectFutureStateApi, projectPainPointApi, projectStrategyApi } from "./api";
import type { ContextStrategyLink, FutureState, PainPoint, PainPointLinkKind, Strategy } from "./types";

interface OpenQuestionOption {
  id: string;
  question: string;
}

const KIND_OPTIONS: { value: PainPointLinkKind; label: string }[] = [
  { value: "drives_strategy", label: "Drives a Strategy" },
  { value: "motivates_requirement", label: "Motivates a Requirement" },
  { value: "raises_open_question", label: "Raises an Open Question" },
  { value: "related_to_future_state", label: "Related to a Future State" },
  { value: "duplicate_of", label: "Duplicate of another Pain Point" },
];

export function PainPointRelationshipsSection({
  projectId,
  painPoint,
}: {
  projectId: string;
  painPoint: PainPoint;
}) {
  const { showToast } = useToast();

  const [links, setLinks] = useState<ContextStrategyLink[] | null>(null);
  const [kind, setKind] = useState<PainPointLinkKind>("drives_strategy");
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [openQuestions, setOpenQuestions] = useState<OpenQuestionOption[]>([]);
  const [futureStates, setFutureStates] = useState<FutureState[]>([]);
  const [otherPainPoints, setOtherPainPoints] = useState<PainPoint[]>([]);
  const [targetId, setTargetId] = useState("");
  const [saving, setSaving] = useState(false);

  async function reload() {
    try {
      setLinks(await projectPainPointApi.listRelationships(projectId, painPoint.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Pain Point's relationships."), "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, painPoint.id]);

  useEffect(() => {
    setTargetId("");
    if (kind === "drives_strategy") {
      void projectStrategyApi.list(projectId).then(setStrategies).catch(() => setStrategies([]));
    } else if (kind === "motivates_requirement") {
      void api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`).then(setRequirements);
    } else if (kind === "raises_open_question") {
      void api
        .get<OpenQuestionOption[]>(`/api/v1/projects/${projectId}/modules/context_strategy/open-questions`)
        .then(setOpenQuestions)
        .catch(() => setOpenQuestions([]));
    } else if (kind === "related_to_future_state") {
      void projectFutureStateApi.list(projectId).then(setFutureStates).catch(() => setFutureStates([]));
    } else {
      void projectPainPointApi.list(projectId).then((all) => setOtherPainPoints(all.filter((p) => p.id !== painPoint.id)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, painPoint.id, kind]);

  async function addRelationship() {
    if (!targetId) return;
    setSaving(true);
    try {
      await projectPainPointApi.createRelationship(projectId, painPoint.id, kind, targetId);
      showToast("Relationship added.");
      setTargetId("");
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not add this relationship."), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="stack">
      <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Relationships</h3>
      {links === null ? (
        <p className="text-muted" style={{ margin: 0 }}>Loading…</p>
      ) : links.length === 0 ? (
        <p className="text-muted" style={{ margin: 0 }}>No relationships yet.</p>
      ) : (
        links.map((link) => (
          <div key={link.id} className="row card" style={{ justifyContent: "space-between" }}>
            <span>
              <span className="badge">{link.display_name}</span>{" "}
              {link.other_display_code ? `${link.other_display_code} — ` : ""}
              {link.other_display_name ?? "(unresolved)"}
            </span>
          </div>
        ))
      )}

      <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap", gap: "0.5rem" }}>
        <LabeledSelect
          label="Relationship"
          value={kind}
          onChange={(v) => setKind(v as PainPointLinkKind)}
          options={KIND_OPTIONS}
        />
        {kind === "drives_strategy" ? (
          <LabeledSelect
            label="Strategy" value={targetId} onChange={setTargetId}
            options={strategies.map((s) => ({ value: s.id, label: s.title }))}
          />
        ) : kind === "motivates_requirement" ? (
          <LabeledSelect
            label="Requirement" value={targetId} onChange={setTargetId}
            options={requirements.map((r) => ({ value: r.id, label: `${r.unique_code} — ${r.name}` }))}
          />
        ) : kind === "raises_open_question" ? (
          <LabeledSelect
            label="Open Question" value={targetId} onChange={setTargetId}
            options={openQuestions.map((q) => ({ value: q.id, label: q.question }))}
          />
        ) : kind === "related_to_future_state" ? (
          <LabeledSelect
            label="Future State" value={targetId} onChange={setTargetId}
            options={futureStates.map((f) => ({ value: f.id, label: f.title }))}
          />
        ) : (
          <LabeledSelect
            label="Pain Point" value={targetId} onChange={setTargetId}
            options={otherPainPoints.map((p) => ({ value: p.id, label: p.title }))}
          />
        )}
        <button className="btn btn-primary" disabled={!targetId || saving} onClick={addRelationship}>
          <Link2 size={14} /> Add
        </button>
      </div>
    </div>
  );
}
