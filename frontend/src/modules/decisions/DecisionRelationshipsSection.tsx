/**
 * Module: modules/decisions/DecisionRelationshipsSection
 *
 * A Decision's own relationships (source overview §13/10.7, Phase 3): the
 * supersession trail, its links to core Requirements (Implements/Affects),
 * and its links to other Decisions (Depends on/Conflicts with) —
 * `GET /{decision_id}/relationships` returns all of these in one list
 * (`DecisionLinkOut` is polymorphic over `other_type`), so this renders them
 * as one flat list rather than three separate ones, distinguishing kind via
 * `link.display_name`/`other_type`.
 *
 * Unlike `RequirementTraceabilityLinksSection.tsx` (which only ever lists —
 * adding a link happens through the shared `RequirementLinkPickerModal`),
 * this section owns both listing and creation: a Decision's own detail
 * panel is the only place these relationships are created from (Phase 5
 * deliberately doesn't add a reverse-direction `requirementDetailSections`/
 * `requirementLinkPickerTabs` contribution yet — see `ProjectDecisionsPage
 * .tsx`'s own module docstring for that scoping call), so there is no
 * second component that needs its own "add" affordance to coordinate with.
 */
import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";

import type { Requirement } from "../../api/types";
import { api } from "../../api/client";
import { LabeledSelect } from "../../components/LabeledSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import type { Decision, DecisionDecisionLinkKind, DecisionLink, DecisionRequirementLinkKind } from "./types";

type RelationshipKind = "supersedes" | "implements" | "affects" | "depends_on" | "conflicts_with";

const KIND_OPTIONS: { value: RelationshipKind; label: string }[] = [
  { value: "supersedes", label: "Supersedes another Decision" },
  { value: "implements", label: "Implements a Requirement" },
  { value: "affects", label: "Affects a Requirement" },
  { value: "depends_on", label: "Depends on another Decision" },
  { value: "conflicts_with", label: "Conflicts with another Decision" },
];

export function DecisionRelationshipsSection({
  projectId,
  decision,
  onChanged,
}: {
  projectId: string;
  decision: Decision;
  /** Called after a relationship is successfully added — a supersession
   * specifically has a side effect on a *different* Decision (flipping it
   * to `SUPERSEDED`, source overview §13/10.6), which this section's own
   * `decision` prop has no way to reflect. The caller (`DecisionDetailPanel
   * .tsx`) forwards this to its own `onChanged`, the same signal
   * `ProjectDecisionsPage.tsx` already uses to refresh the whole Decisions
   * list after a lifecycle transition or edit — reused here rather than a
   * second, parallel refresh mechanism. */
  onChanged?: () => void;
}) {
  const { showToast } = useToast();
  const [links, setLinks] = useState<DecisionLink[] | null>(null);
  const [kind, setKind] = useState<RelationshipKind>("implements");
  const [otherDecisions, setOtherDecisions] = useState<Decision[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [targetId, setTargetId] = useState("");
  const [saving, setSaving] = useState(false);

  async function reload() {
    try {
      setLinks(await decisionsApi.listDecisionRelationships(projectId, decision.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Decision's relationships."), "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, decision.id]);

  useEffect(() => {
    setTargetId("");
    if (kind === "implements" || kind === "affects") {
      void api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`).then(setRequirements);
    } else {
      void decisionsApi.listDecisions(projectId).then((all) => setOtherDecisions(all.filter((d) => d.id !== decision.id)));
    }
  }, [projectId, decision.id, kind]);

  async function addRelationship() {
    if (!targetId) return;
    setSaving(true);
    try {
      if (kind === "supersedes") {
        await decisionsApi.createSupersession(projectId, decision.id, targetId);
      } else if (kind === "implements" || kind === "affects") {
        await decisionsApi.createDecisionRequirementLink(
          projectId, decision.id, targetId, kind as DecisionRequirementLinkKind
        );
      } else {
        await decisionsApi.createDecisionDecisionLink(projectId, decision.id, targetId, kind as DecisionDecisionLinkKind);
      }
      showToast("Relationship added.");
      setTargetId("");
      await reload();
      onChanged?.();
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
          <div
            key={link.id}
            className="row card"
            style={{ justifyContent: "space-between" }}
          >
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
          onChange={(v) => setKind(v as RelationshipKind)}
          options={KIND_OPTIONS}
        />
        {kind === "implements" || kind === "affects" ? (
          <LabeledSelect
            label="Requirement"
            value={targetId}
            onChange={setTargetId}
            options={requirements.map((r) => ({ value: r.id, label: `${r.unique_code} — ${r.name}` }))}
          />
        ) : (
          <LabeledSelect
            label={kind === "supersedes" ? "Decision this supersedes" : "Decision"}
            value={targetId}
            onChange={setTargetId}
            options={otherDecisions.map((d) => ({ value: d.id, label: `${d.unique_code} — ${d.title}` }))}
          />
        )}
        <button className="btn btn-primary" disabled={!targetId || saving} onClick={addRelationship}>
          <Link2 size={14} /> Add
        </button>
      </div>
    </div>
  );
}
