/**
 * Module: modules/context_strategy/FutureStateRelationshipsSection
 *
 * A Future State's own relationships (docs/plans/module-01-context-and-
 * strategy-plan.md Phase 6/7.2): `Future State -> related to -> Pain Point`,
 * `-> related to -> Requirement`, `-> related to -> Guiding Principle`, plus
 * the dedicated supersession mechanism (its own `/supersessions` endpoint,
 * not a plain `FutureStateLinkKind`) — mirrors
 * `StrategyRelationshipsSection.tsx`'s exact "one section owns both listing
 * and creation" shape and its `kindOptions`-driven target picker. Kept as
 * its own sibling component, not folded into `StrategyRelationshipsSection.tsx`
 * or generalised (unlike `ArtefactCommentsSection.tsx`) — **Decided by:
 * Agent** — because the two components' *substance* (which link kinds
 * exist, which target types/pickers they need, the reserved-Decision note's
 * exact wording) genuinely diverges per artefact type, the same "per-source-
 * artefact-type" shape `service.py`'s own Phase 6 docstring establishes for
 * the backend; only the comment thread (identical shape, no per-artefact
 * content) qualified for generalisation.
 *
 * `Strategy -> defines -> Future State` (§5.6) is *not* offered as a pickable
 * kind here — Phase 6 built that relationship once, from Strategy's own side
 * only (`StrategyLinkKind.DEFINES_FUTURE_STATE`), not duplicated from both
 * ends (see `service.py`'s own docstring); it still renders correctly in this
 * section's own relationship list (`GET .../relationships` resolves it from
 * either artefact's viewpoint), just not as something *this* section can
 * create. `Future State -> related to -> Decision` (§7's "linkable to...
 * Decisions") is rendered as present-but-reserved text, the same reserved-
 * relationship treatment `StrategyRelationshipsSection.tsx` gives `Strategy
 * -> informs -> Decision`.
 *
 * **Scope decision, Decided by: Agent, following `StrategyRelationships
 * Section.tsx`'s own precedent directly:** `related_to_pain_point` (Pain
 * Point is project-scoped only, Phase 3) and `related_to_requirement` (a
 * Requirement is always project-scoped) are only offered when this Future
 * State itself is project-scoped. `related_to_guiding_principle` is
 * *also* restricted to the project-scoped case here, even though Guiding
 * Principle itself can be org-scoped (Phase 4) — building a combined org+
 * project Guiding Principle picker (and Guiding Principle has no frontend of
 * its own yet, Phase 7.4) is the same "don't build a cross-scope picker a
 * real need hasn't asked for yet" restraint Strategy's own section already
 * applies to `defines_future_state`/`requires_resolution_of_open_question`.
 * An org-scoped Future State can still record a supersession (an org-level
 * concept with no project to resolve).
 */
import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";

import type { Requirement } from "../../api/types";
import { api } from "../../api/client";
import { LabeledSelect } from "../../components/LabeledSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgFutureStateApi, projectFutureStateApi } from "./api";
import type { ContextStrategyLink, FutureState, FutureStateLinkKind } from "./types";

type RelationshipKind = "supersedes" | FutureStateLinkKind;

interface PainPointOption {
  id: string;
  title: string;
}
interface GuidingPrincipleOption {
  id: string;
  name: string;
}

export function FutureStateRelationshipsSection({
  futureState,
  projectId,
  organizationId,
  onChanged,
}: {
  futureState: FutureState;
  /** Present when this Future State is project-scoped — enables the
   * project-scoped-only target kinds (see this file's own module docstring). */
  projectId?: string;
  /** Present when this Future State is org-scoped. Exactly one of
   * `projectId`/`organizationId` is set, mirroring the backend's own scope
   * discriminator. */
  organizationId?: string;
  /** Called after a relationship is successfully added — a supersession has
   * a side effect on a *different* Future State (flipping it to
   * `SUPERSEDED`), which this section's own `futureState` prop has no way
   * to reflect; the caller re-fetches, same signal
   * `StrategyRelationshipsSection.tsx` already establishes. */
  onChanged?: () => void;
}) {
  const { showToast } = useToast();
  const api_ = projectId ? projectFutureStateApi : orgFutureStateApi;
  const scopeId = (projectId ?? organizationId)!;

  const [links, setLinks] = useState<ContextStrategyLink[] | null>(null);
  const [kind, setKind] = useState<RelationshipKind>(projectId ? "related_to_requirement" : "supersedes");
  const [otherFutureStates, setOtherFutureStates] = useState<FutureState[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [painPoints, setPainPoints] = useState<PainPointOption[]>([]);
  const [guidingPrinciples, setGuidingPrinciples] = useState<GuidingPrincipleOption[]>([]);
  const [targetId, setTargetId] = useState("");
  const [saving, setSaving] = useState(false);

  const kindOptions: { value: RelationshipKind; label: string }[] = [
    ...(projectId
      ? ([
          { value: "related_to_requirement", label: "Related to a Requirement" },
          { value: "related_to_pain_point", label: "Related to a Pain Point" },
          { value: "related_to_guiding_principle", label: "Related to a Guiding Principle" },
        ] as const)
      : []),
    { value: "supersedes", label: "Supersedes another Future State" },
  ];

  async function reload() {
    try {
      setLinks(await api_.listRelationships(scopeId, futureState.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Future State's relationships."), "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, futureState.id]);

  useEffect(() => {
    setTargetId("");
    if (kind === "related_to_requirement" && projectId) {
      void api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`).then(setRequirements);
    } else if (kind === "related_to_pain_point" && projectId) {
      void api
        .get<PainPointOption[]>(`/api/v1/projects/${projectId}/modules/context_strategy/pain-points`)
        .then(setPainPoints)
        .catch(() => setPainPoints([]));
    } else if (kind === "related_to_guiding_principle" && projectId) {
      void api
        .get<GuidingPrincipleOption[]>(`/api/v1/projects/${projectId}/modules/context_strategy/guiding-principles`)
        .then(setGuidingPrinciples)
        .catch(() => setGuidingPrinciples([]));
    } else {
      void api_.list(scopeId).then((all) => setOtherFutureStates(all.filter((fs) => fs.id !== futureState.id)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, futureState.id, kind, projectId]);

  async function addRelationship() {
    if (!targetId) return;
    setSaving(true);
    try {
      if (kind === "supersedes") {
        await api_.createSupersessionLink(scopeId, futureState.id, targetId);
      } else {
        await api_.createRelationship(scopeId, futureState.id, kind, targetId);
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
        Also reserved for future use: Future State → related to → Decision (not yet populatable).
      </p>

      <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap", gap: "0.5rem" }}>
        <LabeledSelect
          label="Relationship"
          value={kind}
          onChange={(v) => setKind(v as RelationshipKind)}
          options={kindOptions}
        />
        {kind === "related_to_requirement" ? (
          <LabeledSelect
            label="Requirement"
            value={targetId}
            onChange={setTargetId}
            options={requirements.map((r) => ({ value: r.id, label: `${r.unique_code} — ${r.name}` }))}
          />
        ) : kind === "related_to_pain_point" ? (
          <LabeledSelect
            label="Pain Point"
            value={targetId}
            onChange={setTargetId}
            options={painPoints.map((p) => ({ value: p.id, label: p.title }))}
          />
        ) : kind === "related_to_guiding_principle" ? (
          <LabeledSelect
            label="Guiding Principle"
            value={targetId}
            onChange={setTargetId}
            options={guidingPrinciples.map((g) => ({ value: g.id, label: g.name }))}
          />
        ) : (
          <LabeledSelect
            label="Future State this supersedes"
            value={targetId}
            onChange={setTargetId}
            options={otherFutureStates.map((fs) => ({ value: fs.id, label: fs.title }))}
          />
        )}
        <button className="btn btn-primary" disabled={!targetId || saving} onClick={addRelationship}>
          <Link2 size={14} /> Add
        </button>
      </div>
    </div>
  );
}
