/**
 * Module: modules/stakeholders/RelationshipsPanel
 *
 * The §10.5 relationships on a Stakeholder's or Persona's detail page
 * (Experiences / Provides / Is affected by / Consulted on / Approves /
 * Reviews …) to the current project's Pain Points, Requirements and
 * Decisions: a list grouped by kind, an add row (kind → target type, when a
 * kind has more than one → target), and a remove with a tier-1 confirm
 * (docs/ux-style-guide.md "confirmation, in two tiers"); every mutation gives
 * a toast.
 *
 * One component for both holder kinds: the backend says which kinds apply to a
 * holder (a Persona is never "consulted" or "approves"), so nothing here is
 * per-kind. Targets belong to other modules, so links resolve through
 * `modules/artefactPaths` rather than hardcoded routes, and a kind whose
 * target module isn't installed yet (Design / System Element) is shown as a
 * muted note, not an add option.
 *
 * Like `RepresentationPanel`, it loads itself and renders nothing if the load
 * fails, and nothing when there is no project (the org-level detail route has
 * no single project's records to relate to). Target status is deliberately not
 * shown: it is another module's enum and has no label map here.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LabeledSelect } from "../../components/LabeledSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { getArtefactPath } from "../artefactPaths";
import { projectRelationshipApi } from "./api";
import type { Relationship, RelationshipHolderKind, RelationshipKind, RelationshipTarget } from "./types";
import { relationshipTargetTypeLabel } from "./types";

/** The calls the panel makes; `projectRelationshipApi` by default, injectable for stories. */
export type RelationshipPanelApi = Pick<typeof projectRelationshipApi, "kinds" | "targets" | "list" | "add" | "remove">;

export function RelationshipsPanel({
  projectId,
  holder,
  holderId,
  api = projectRelationshipApi,
}: {
  /** The project whose records are related to; `undefined` (org route) renders nothing. */
  projectId: string | undefined;
  holder: RelationshipHolderKind;
  holderId: string;
  api?: RelationshipPanelApi;
}) {
  const { showToast } = useToast();
  const [kinds, setKinds] = useState<RelationshipKind[] | null>(null);
  const [links, setLinks] = useState<Relationship[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [kindKey, setKindKey] = useState("");
  const [targetType, setTargetType] = useState("");
  const [targetId, setTargetId] = useState("");
  const [loadedTargets, setLoadedTargets] = useState<{ type: string; rows: RelationshipTarget[] } | null>(null);
  const [removing, setRemoving] = useState<Relationship | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    Promise.all([api.kinds(projectId), api.list(projectId, holder, holderId)])
      .then(([k, l]) => {
        if (!active) return;
        setKinds(k);
        setLinks(l);
        setUnavailable(false);
      })
      .catch(() => {
        if (active) setUnavailable(true);
      });
    return () => {
      active = false;
    };
  }, [api, projectId, holder, holderId, refresh]);

  const mine = useMemo(() => (kinds ?? []).filter((k) => k.holder_types.includes(holder)), [kinds, holder]);
  const addable = mine.filter((k) => k.available_target_types.length > 0);
  const reserved = mine.filter((k) => k.available_target_types.length === 0);
  const kind = addable.find((k) => k.key === kindKey);
  const effectiveTargetType = kind ? (kind.available_target_types.length === 1 ? kind.available_target_types[0] : targetType) : "";

  useEffect(() => {
    if (!projectId || !effectiveTargetType) return;
    let active = true;
    const type = effectiveTargetType;
    api
      .targets(projectId, type)
      .then((rows) => {
        if (active) setLoadedTargets({ type, rows });
      })
      .catch(() => {
        if (active) setLoadedTargets({ type, rows: [] });
      });
    return () => {
      active = false;
    };
  }, [api, projectId, effectiveTargetType, refresh]);
  // Rows loaded for a different target type than the current one are stale.
  const targets = loadedTargets?.type === effectiveTargetType ? loadedTargets.rows : [];

  if (!projectId || unavailable || kinds === null || links === null) return null;

  async function mutate(action: () => Promise<unknown>, success: string, failure: string) {
    try {
      await action();
      showToast(success);
      setRefresh((n) => n + 1);
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
    }
  }

  const grouped = mine
    .map((k) => ({ kind: k, rows: links.filter((l) => l.kind === k.key) }))
    .filter((g) => g.rows.length > 0);
  const linkedForKind = new Set(
    links.filter((l) => l.kind === kindKey && l.target_type === effectiveTargetType).map((l) => l.target_id),
  );
  const candidates = targets.filter((t) => !linkedForKind.has(t.id)).map((t) => ({ value: t.id, label: t.label }));

  return (
    <div className="stack" style={{ gap: "0.35rem" }} data-testid="relationships-panel">
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Relationships</span>
      {grouped.length === 0 ? (
        <span className="text-muted">No relationships to this project's records yet.</span>
      ) : (
        grouped.map(({ kind: k, rows }) => (
          <div key={k.key}>
            <span style={{ fontWeight: 600 }}>{k.forward}</span>
            <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
              {rows.map((l) => {
                const path = getArtefactPath(l.target_type, projectId, l.target_id);
                const text = `${l.label}${l.is_archived ? " (archived)" : ""}`;
                return (
                  <li key={l.link_id}>
                    <span className="text-muted">{relationshipTargetTypeLabel(l.target_type)}: </span>
                    {path ? <Link to={path}>{text}</Link> : text}
                    <button className="btn" style={{ marginLeft: "0.5rem" }} aria-label={`Remove ${k.forward} ${l.label}`} onClick={() => setRemoving(l)}>
                      Remove
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))
      )}

      {addable.length > 0 && (
        <div className="row" style={{ gap: "0.5rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <LabeledSelect
            label="Relationship"
            value={kindKey}
            onChange={(v) => {
              setKindKey(v);
              setTargetType("");
              setTargetId("");
            }}
            options={addable.map((k) => ({ value: k.key, label: k.forward }))}
            placeholder="Choose…"
          />
          {kind && kind.available_target_types.length > 1 && (
            <LabeledSelect
              label="Target type"
              value={targetType}
              onChange={(v) => {
                setTargetType(v);
                setTargetId("");
              }}
              options={kind.available_target_types.map((t) => ({ value: t, label: relationshipTargetTypeLabel(t) }))}
              placeholder="Choose…"
            />
          )}
          {effectiveTargetType && (
            <LabeledSelect
              label={relationshipTargetTypeLabel(effectiveTargetType)}
              value={targetId}
              onChange={setTargetId}
              options={candidates}
              placeholder="Choose…"
            />
          )}
          <button
            className="btn"
            disabled={!kind || !effectiveTargetType || !targetId}
            onClick={async () => {
              const id = targetId;
              setTargetId("");
              await mutate(
                () => api.add(projectId, holder, holderId, kindKey, effectiveTargetType, id),
                "Relationship added.",
                "Could not add the relationship.",
              );
            }}
          >
            Add relationship
          </button>
        </div>
      )}

      {reserved.map((k) => (
        <span key={k.key} className="text-muted" style={{ fontSize: "0.85rem" }}>
          {k.forward} {k.target_types.map(relationshipTargetTypeLabel).join(" / ")}: available once the module that provides it is installed.
        </span>
      ))}

      {removing && (
        <ConfirmDialog
          title={`Remove this relationship?`}
          message={`The link to ${removing.label} is removed; both records stay.`}
          confirmLabel="Remove"
          onConfirm={async () => {
            const link = removing;
            setRemoving(null);
            await mutate(() => api.remove(projectId, holder, holderId, link.link_id), "Relationship removed.", "Could not remove the relationship.");
          }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  );
}
