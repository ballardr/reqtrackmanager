/**
 * Module: modules/context_strategy/StrategyRelationshipsSection
 *
 * A Strategy's own relationships (docs/plans/module-01-context-and-strategy-
 * plan.md Phase 6/7.1): `Strategy -> drives -> Requirement`, `Strategy ->
 * defines -> Future State`, `Strategy -> requires resolution of -> Open
 * Question`, `Strategy -> contributes to -> Strategy`, plus the dedicated
 * supersession mechanism (its own `/supersessions` endpoint, not a plain
 * `StrategyLinkKind`) — mirrors `modules/decisions/
 * DecisionRelationshipsSection.tsx`'s exact "one section owns both listing
 * and creation" shape and its `KIND_OPTIONS`-driven target picker.
 *
 * `Strategy -> informs -> Decision` (§5.6) is rendered as present-but-
 * reserved text, not a pickable kind: Phase 6 confirmed this relationship
 * type is reserved until Decision Management's own Phase 7 builds the
 * wiring from its own side (`GET .../relationships`'s own `ContextStrategyLinkOut`
 * shape already tolerates an unresolvable `"decision"` `other_type`, so
 * nothing breaks once real rows do start appearing here — see `schemas.py`'s
 * own docstring) — see this module's plan doc's "Phase 6 notes".
 *
 * **Scope decision, Decided by: Agent:** `defines_future_state` and
 * `requires_resolution_of_open_question` target *project-scoped* artefacts
 * (Future State, Open Question) that have no frontend of their own yet
 * (Phase 7.2/7.5) and, for an **organisation**-scoped Strategy, no single
 * project to search within in the first place — target pickers for those
 * two kinds, plus `drives_requirement` (a Requirement is always project-
 * scoped), are only offered when this Strategy itself is project-scoped.
 * An org-scoped Strategy can still record `contributes_to_strategy` (another
 * Strategy in the same organisation) and a supersession — both org-level
 * concepts with no project to resolve. This mirrors the same "don't build a
 * cross-project/cross-scope picker a real need hasn't asked for yet"
 * restraint this module's other phases already apply (Phase 3's Pain Point
 * type reassignment, Phase 4's Guiding Principle scoping).
 */
import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";

import type { Requirement } from "../../api/types";
import { api } from "../../api/client";
import { LabeledSelect } from "../../components/LabeledSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgStrategyApi, projectStrategyApi } from "./api";
import type { ContextStrategyLink, Strategy, StrategyLinkKind } from "./types";

type RelationshipKind = "supersedes" | StrategyLinkKind;

interface FutureStateOption {
  id: string;
  title: string;
}
interface OpenQuestionOption {
  id: string;
  title: string;
}

export function StrategyRelationshipsSection({
  strategy,
  projectId,
  organizationId,
  onChanged,
}: {
  strategy: Strategy;
  /** Present when this Strategy is project-scoped — enables the
   * project-scoped-only target kinds (see this file's own module docstring). */
  projectId?: string;
  /** Present when this Strategy is org-scoped. Exactly one of `projectId`/
   * `organizationId` is set, mirroring the backend's own scope discriminator. */
  organizationId?: string;
  /** Called after a relationship is successfully added — a supersession has
   * a side effect on a *different* Strategy (flipping it to `SUPERSEDED`),
   * which this section's own `strategy` prop has no way to reflect; the
   * caller re-fetches, the same signal `DecisionRelationshipsSection.tsx`
   * already establishes this precedent for. */
  onChanged?: () => void;
}) {
  const { showToast } = useToast();
  const api_ = projectId ? projectStrategyApi : orgStrategyApi;
  const scopeId = (projectId ?? organizationId)!;

  const [links, setLinks] = useState<ContextStrategyLink[] | null>(null);
  const [kind, setKind] = useState<RelationshipKind>(projectId ? "drives_requirement" : "contributes_to_strategy");
  const [otherStrategies, setOtherStrategies] = useState<Strategy[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [futureStates, setFutureStates] = useState<FutureStateOption[]>([]);
  const [openQuestions, setOpenQuestions] = useState<OpenQuestionOption[]>([]);
  const [targetId, setTargetId] = useState("");
  const [saving, setSaving] = useState(false);

  const kindOptions: { value: RelationshipKind; label: string }[] = [
    ...(projectId
      ? ([
          { value: "drives_requirement", label: "Drives a Requirement" },
          { value: "defines_future_state", label: "Defines a Future State" },
          { value: "requires_resolution_of_open_question", label: "Requires resolution of an Open Question" },
        ] as const)
      : []),
    { value: "contributes_to_strategy", label: "Contributes to another Strategy" },
    { value: "supersedes", label: "Supersedes another Strategy" },
  ];

  async function reload() {
    try {
      setLinks(await api_.listRelationships(scopeId, strategy.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Strategy's relationships."), "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, strategy.id]);

  useEffect(() => {
    setTargetId("");
    if (kind === "drives_requirement" && projectId) {
      void api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`).then(setRequirements);
    } else if (kind === "defines_future_state" && projectId) {
      void api
        .get<FutureStateOption[]>(`/api/v1/projects/${projectId}/modules/context_strategy/future-states`)
        .then(setFutureStates)
        .catch(() => setFutureStates([]));
    } else if (kind === "requires_resolution_of_open_question" && projectId) {
      void api
        .get<OpenQuestionOption[]>(`/api/v1/projects/${projectId}/modules/context_strategy/open-questions`)
        .then(setOpenQuestions)
        .catch(() => setOpenQuestions([]));
    } else {
      void api_.list(scopeId).then((all) => setOtherStrategies(all.filter((s) => s.id !== strategy.id)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, strategy.id, kind, projectId]);

  async function addRelationship() {
    if (!targetId) return;
    setSaving(true);
    try {
      if (kind === "supersedes") {
        await api_.createSupersessionLink(scopeId, strategy.id, targetId);
      } else {
        await api_.createRelationship(scopeId, strategy.id, kind, targetId);
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
          <div key={link.id} className="row card" style={{ justifyContent: "space-between" }}>
            <span>
              <span className="badge">{link.display_name}</span>{" "}
              {link.other_display_code ? `${link.other_display_code} — ` : ""}
              {link.other_display_name ?? "(unresolved)"}
            </span>
          </div>
        ))
      )}
      <p className="text-muted" style={{ margin: 0, fontSize: "0.8rem" }}>
        Also reserved for future use: Strategy → informs → Decision (not yet populatable).
      </p>

      <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap", gap: "0.5rem" }}>
        <LabeledSelect
          label="Relationship"
          value={kind}
          onChange={(v) => setKind(v as RelationshipKind)}
          options={kindOptions}
        />
        {kind === "drives_requirement" ? (
          <LabeledSelect
            label="Requirement"
            value={targetId}
            onChange={setTargetId}
            options={requirements.map((r) => ({ value: r.id, label: `${r.unique_code} — ${r.name}` }))}
          />
        ) : kind === "defines_future_state" ? (
          <LabeledSelect
            label="Future State"
            value={targetId}
            onChange={setTargetId}
            options={futureStates.map((f) => ({ value: f.id, label: f.title }))}
          />
        ) : kind === "requires_resolution_of_open_question" ? (
          <LabeledSelect
            label="Open Question"
            value={targetId}
            onChange={setTargetId}
            options={openQuestions.map((q) => ({ value: q.id, label: q.title }))}
          />
        ) : (
          <LabeledSelect
            label={kind === "supersedes" ? "Strategy this supersedes" : "Strategy"}
            value={targetId}
            onChange={setTargetId}
            options={otherStrategies.map((s) => ({ value: s.id, label: s.title }))}
          />
        )}
        <button className="btn btn-primary" disabled={!targetId || saving} onClick={addRelationship}>
          <Link2 size={14} /> Add
        </button>
      </div>
    </div>
  );
}
