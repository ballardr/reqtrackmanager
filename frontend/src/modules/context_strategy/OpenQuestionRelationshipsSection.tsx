/**
 * Module: modules/context_strategy/OpenQuestionRelationshipsSection
 *
 * An Open Question's own relationships (docs/plans/module-01-context-and-
 * strategy-plan.md Phase 6/7.5): `Open Question -> related to -> Strategy`
 * and `-> related to -> Requirement` — both untyped (§9.2's own plain
 * "Related Strategy"/"Related Requirements" field naming, no causal verb),
 * mirroring `PainPointRelationshipsSection.tsx`'s "one section owns both
 * listing and creation" shape and its `kindOptions`-driven target picker.
 *
 * **A sibling component, not a generalisation of any of the other four
 * (Decided by: Agent)** — checked all four existing sections first, per this
 * module's own established practice: Open Question's own two kinds and
 * target pickers diverge from every sibling's, the same "per-source-
 * artefact-type" reasoning `PainPointRelationshipsSection.tsx`'s own
 * docstring already established a third time.
 *
 * **No scope-conditional target-picker restriction, mirroring Pain Point's
 * own reasoning exactly** — Open Question has no organisation scope at all
 * (source overview §9), so there is no org-scoped case whose pickers would
 * need withholding.
 *
 * **The Strategy target picker lists this project's own Strategies only
 * (`projectStrategyApi.list`), not this project's organisation's org-scoped
 * Strategies too (Decided by: Agent) — matching `PainPointRelationshipsSection.
 * tsx`'s own `drives_strategy` picker precedent exactly, not a new
 * limitation invented here.** An org-scoped Strategy is still reachable and
 * linkable via the generic relationship machinery from the Strategy side of
 * a future pass if this turns out to matter in practice; revisit both
 * sections together if it does, rather than diverging one from the other.
 *
 * `Open Question -> resolved by -> Decision` (§9.5, the reserved
 * Decision-target relationship, Phase 0 Q5) has no equivalent here — Module
 * 4's own Phase 7 builds the real "Create Decision from Open Question"
 * workflow and its relationship, not this module — so unlike
 * `StrategyRelationshipsSection.tsx`/`FutureStateRelationshipsSection.tsx`/
 * `GuidingPrincipleRelationshipsSection.tsx` this section renders no
 * "reserved for future use" note; `resolve_open_question` (the plain status
 * transition) is this artefact's own stand-in until that workflow exists.
 *
 * No dedicated supersession mechanism either — Open Question has no version
 * table (Phase 5's own scope decision) and no `/supersessions` endpoint.
 */
import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";

import type { Requirement } from "../../api/types";
import { api } from "../../api/client";
import { LabeledSelect } from "../../components/LabeledSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectOpenQuestionApi, projectStrategyApi } from "./api";
import type { ContextStrategyLink, OpenQuestion, OpenQuestionLinkKind, Strategy } from "./types";

const KIND_OPTIONS: { value: OpenQuestionLinkKind; label: string }[] = [
  { value: "related_to_strategy", label: "Related to a Strategy" },
  { value: "related_to_requirement", label: "Related to a Requirement" },
];

export function OpenQuestionRelationshipsSection({
  projectId,
  openQuestion,
}: {
  projectId: string;
  openQuestion: OpenQuestion;
}) {
  const { showToast } = useToast();

  const [links, setLinks] = useState<ContextStrategyLink[] | null>(null);
  const [kind, setKind] = useState<OpenQuestionLinkKind>("related_to_strategy");
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [targetId, setTargetId] = useState("");
  const [saving, setSaving] = useState(false);

  async function reload() {
    try {
      setLinks(await projectOpenQuestionApi.listRelationships(projectId, openQuestion.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Open Question's relationships."), "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, openQuestion.id]);

  useEffect(() => {
    setTargetId("");
    if (kind === "related_to_strategy") {
      void projectStrategyApi.list(projectId).then(setStrategies).catch(() => setStrategies([]));
    } else {
      void api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`).then(setRequirements);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, openQuestion.id, kind]);

  async function addRelationship() {
    if (!targetId) return;
    setSaving(true);
    try {
      await projectOpenQuestionApi.createRelationship(projectId, openQuestion.id, kind, targetId);
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
          onChange={(v) => setKind(v as OpenQuestionLinkKind)}
          options={KIND_OPTIONS}
        />
        {kind === "related_to_strategy" ? (
          <LabeledSelect
            label="Strategy" value={targetId} onChange={setTargetId}
            options={strategies.map((s) => ({ value: s.id, label: s.title }))}
          />
        ) : (
          <LabeledSelect
            label="Requirement" value={targetId} onChange={setTargetId}
            options={requirements.map((r) => ({ value: r.id, label: `${r.unique_code} — ${r.name}` }))}
          />
        )}
        <button className="btn btn-primary" disabled={!targetId || saving} onClick={addRelationship}>
          <Link2 size={14} /> Add
        </button>
      </div>
    </div>
  );
}
