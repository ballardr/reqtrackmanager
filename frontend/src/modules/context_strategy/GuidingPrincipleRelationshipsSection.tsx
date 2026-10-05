/**
 * Module: modules/context_strategy/GuidingPrincipleRelationshipsSection
 *
 * A Guiding Principle's own relationships (docs/plans/module-01-context-and-
 * strategy-plan.md Phase 6/7.4): `Guiding Principle -> supports -> Strategy`,
 * `Guiding Principle -> informs -> Requirement`, plus the dedicated
 * supersession mechanism (its own `/supersessions` endpoint, not a plain
 * `GuidingPrincipleLinkKind`) — mirrors `StrategyRelationshipsSection.tsx`'s
 * exact "one section owns both listing and creation" shape and its
 * `kindOptions`-driven target picker.
 *
 * **Sibling component, not a generalisation of `StrategyRelationshipsSection.
 * tsx`/`FutureStateRelationshipsSection.tsx`/`PainPointRelationshipsSection.tsx`
 * (Decided by: Agent)** — checked all three first, per this module's own
 * established practice (`FutureStateRelationshipsSection.tsx`'s/
 * `PainPointRelationshipsSection.tsx`'s own docstrings already made this
 * exact call for their own artefact types): Guiding Principle's own kind set
 * (`supports_strategy`/`informs_requirement`) and target pickers genuinely
 * diverge from every sibling's, sharing only the generic "pick a kind, pick
 * a target, POST" shape those sections already independently established is
 * not enough alone to justify merging.
 *
 * `Guiding Principle -> guides -> Decision` (§8.5) is rendered as
 * present-but-reserved text, not a pickable kind — same reserved-relationship
 * treatment as `Strategy -> informs -> Decision` (see that section's own
 * docstring and this module's Phase 6 notes).
 *
 * **Scope decision, Decided by: Agent, following `StrategyRelationshipsSection.
 * tsx`'s own restraint exactly:** `informs_requirement` targets a Requirement,
 * always project-scoped, so it is only offered when this Guiding Principle
 * itself is project-scoped — an organisation-scoped Guiding Principle has no
 * single project to search a Requirement within. `supports_strategy` has no
 * such restriction — a Strategy exists at both scopes (Phase 0 Q2), so this
 * Guiding Principle's own target picker lists Strategies at its own matching
 * scope (`projectStrategyApi`/`orgStrategyApi`, same "search within the same
 * scope as the source" convention `contributes_to_strategy`'s own picker
 * already uses). Supersession (another Guiding Principle) also lists at the
 * matching scope.
 */
import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";

import type { Requirement } from "../../api/types";
import { api } from "../../api/client";
import { LabeledSelect } from "../../components/LabeledSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgGuidingPrincipleApi, orgStrategyApi, projectGuidingPrincipleApi, projectStrategyApi } from "./api";
import type { ContextStrategyLink, GuidingPrinciple, GuidingPrincipleLinkKind, Strategy } from "./types";

type RelationshipKind = "supersedes" | GuidingPrincipleLinkKind;

export function GuidingPrincipleRelationshipsSection({
  guidingPrinciple,
  projectId,
  organizationId,
  onChanged,
}: {
  guidingPrinciple: GuidingPrinciple;
  /** Present when this Guiding Principle is project-scoped — enables the
   * project-scoped-only `informs_requirement` kind (see this file's own
   * module docstring). */
  projectId?: string;
  /** Present when this Guiding Principle is org-scoped. Exactly one of
   * `projectId`/`organizationId` is set, mirroring the backend's own scope
   * discriminator. */
  organizationId?: string;
  /** Called after a relationship is successfully added — a supersession has
   * a side effect on a *different* Guiding Principle (flipping it to
   * `Superseded`), which this section's own `guidingPrinciple` prop has no
   * way to reflect; the caller re-fetches, same signal
   * `StrategyRelationshipsSection.tsx`'s own `onChanged` establishes. */
  onChanged?: () => void;
}) {
  const { showToast } = useToast();
  const api_ = projectId ? projectGuidingPrincipleApi : orgGuidingPrincipleApi;
  const strategyApi = projectId ? projectStrategyApi : orgStrategyApi;
  const scopeId = (projectId ?? organizationId)!;

  const [links, setLinks] = useState<ContextStrategyLink[] | null>(null);
  const [kind, setKind] = useState<RelationshipKind>("supports_strategy");
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [otherGuidingPrinciples, setOtherGuidingPrinciples] = useState<GuidingPrinciple[]>([]);
  const [targetId, setTargetId] = useState("");
  const [saving, setSaving] = useState(false);

  const kindOptions: { value: RelationshipKind; label: string }[] = [
    { value: "supports_strategy", label: "Supports a Strategy" },
    ...(projectId ? ([{ value: "informs_requirement", label: "Informs a Requirement" }] as const) : []),
    { value: "supersedes", label: "Supersedes another Guiding Principle" },
  ];

  async function reload() {
    try {
      setLinks(await api_.listRelationships(scopeId, guidingPrinciple.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Guiding Principle's relationships."), "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, guidingPrinciple.id]);

  useEffect(() => {
    setTargetId("");
    if (kind === "informs_requirement" && projectId) {
      void api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`).then(setRequirements);
    } else if (kind === "supersedes") {
      void api_.list(scopeId).then((all) => setOtherGuidingPrinciples(all.filter((g) => g.id !== guidingPrinciple.id)));
    } else {
      void strategyApi.list(scopeId).then(setStrategies);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, guidingPrinciple.id, kind, projectId]);

  async function addRelationship() {
    if (!targetId) return;
    setSaving(true);
    try {
      if (kind === "supersedes") {
        await api_.createSupersessionLink(scopeId, guidingPrinciple.id, targetId);
      } else {
        await api_.createRelationship(scopeId, guidingPrinciple.id, kind, targetId);
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
        Also reserved for future use: Guiding Principle → guides → Decision (not yet populatable).
      </p>

      <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap", gap: "0.5rem" }}>
        <LabeledSelect
          label="Relationship"
          value={kind}
          onChange={(v) => setKind(v as RelationshipKind)}
          options={kindOptions}
        />
        {kind === "informs_requirement" ? (
          <LabeledSelect
            label="Requirement"
            value={targetId}
            onChange={setTargetId}
            options={requirements.map((r) => ({ value: r.id, label: `${r.unique_code} — ${r.name}` }))}
          />
        ) : kind === "supersedes" ? (
          <LabeledSelect
            label="Guiding Principle this supersedes"
            value={targetId}
            onChange={setTargetId}
            options={otherGuidingPrinciples.map((g) => ({ value: g.id, label: g.name }))}
          />
        ) : (
          <LabeledSelect
            label="Strategy"
            value={targetId}
            onChange={setTargetId}
            options={strategies.map((s) => ({ value: s.id, label: s.title }))}
          />
        )}
        <button className="btn btn-primary" disabled={!targetId || saving} onClick={addRelationship}>
          <Link2 size={14} /> Add
        </button>
      </div>
    </div>
  );
}
