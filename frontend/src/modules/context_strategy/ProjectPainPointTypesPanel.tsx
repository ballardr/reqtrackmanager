/**
 * Module: modules/context_strategy/ProjectPainPointTypesPanel
 *
 * The project-scoped tier of Pain Point's type vocabulary (Phase 0 Q3's
 * two-tier model, source overview §6.2) — shows this project's *effective*
 * type list (`projectPainPointApi.listTypes`: every active org type, with
 * this project's own override applied if one exists, plus every fully
 * project-local type) and lets a `pain_point_manager` rename/reorder/enable-
 * disable an org type's project-local override, add a project-local type,
 * and delete an override or local type.
 *
 * Reuses `DefinitionList` for the shared rename/add/delete-list shape
 * (matching `DecisionTypesPanel.tsx`'s own project-tier precedent exactly —
 * both are project-scoped definition lists gated by a project-level manager
 * role) and `ToggleSwitch` via `renderExtra` for the `is_enabled` toggle,
 * the same pattern `OrgPainPointTypesPanel.tsx` uses for `is_active`.
 *
 * **Placement: `projectAdminSections` (Project Admin), matching
 * `DecisionTypesPanel.tsx`'s own placement exactly (Decided by: Agent,
 * following the brief directly).** A project's own type-vocabulary
 * configuration is project admin surface, the same distinction
 * `OrgPainPointTypesPanel.tsx`'s own docstring draws for the org tier.
 *
 * **`onMove` is hand-rolled, not `services.ordering.move_ordered`-backed
 * (Decided by: Agent) — there is no project-tier `/move` endpoint to call.**
 * Unlike the org tier (`POST .../pain-point-types/{id}/move`, backed by
 * `move_ordered` against `PainPointTypeDefinition.sort_order`), the
 * project-scoped `PUT .../pain-point-types/{type_ref_id}` endpoint only ever
 * sets a row's own `display_order_override` to whatever integer it's given
 * — there is no atomic "swap with neighbour" primitive at this tier. This
 * panel's own `onMove` finds the adjacent row in the already-sorted
 * effective list and issues two `overrideType` calls that swap the two
 * rows' current `display_order` values — functionally equivalent to
 * `move_ordered`'s own up/down swap, just implemented client-side against a
 * `PUT`-only API. This also means selecting a **new** effective order value
 * for a fully-untouched org-tier row (`source === "org"`) lazily
 * materialises this project's own override the first time it's touched
 * (`get_or_create_project_pain_point_type`, Phase 3's own design) — the same
 * as renaming or disabling one.
 *
 * **Delete blocks with a plain error, not `DefinitionList`'s reassign-on-409
 * flow, for the same reason `OrgPainPointTypesPanel.tsx`'s own `onDelete`
 * does (Decided by: Agent).** `service.delete_project_pain_point_type` has
 * no reassignment parameter either (Phase 3's own design — blocked outright
 * if any Pain Point still references it, since `PainPoint.pain_point_type_id`
 * is `NOT NULL`). An org-tier row with `source === "org"` (no project
 * override exists yet) has nothing to delete at all — there is no
 * `ProjectPainPointType` row behind it yet, so this panel refuses locally
 * before calling the API, rather than surfacing a confusing 404.
 */
import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { DefinitionList } from "../../components/DefinitionList";
import { Spinner } from "../../components/Spinner";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectPainPointApi } from "./api";
import type { EffectivePainPointType } from "./types";

const SOURCE_LABEL: Record<EffectivePainPointType["source"], string> = {
  org: "Org default",
  project_override: "Org default (overridden)",
  project_local: "Project only",
};

export function ProjectPainPointTypesPanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [items, setItems] = useState<EffectivePainPointType[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function reload() {
    try {
      const list = await projectPainPointApi.listTypes(projectId);
      setItems([...list].sort((a, b) => a.display_order - b.display_order));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load this project's Pain Point types."));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (items === null) return <Spinner />;

  return (
    <div className="stack">
      <p className="text-muted">
        This project's effective Pain Point type list — every active organisation type (with this project's own
        override, if any) plus any type added directly for this project only. Disabling a type here only affects
        this project; the organisation's own list (Org Management) is unaffected.
      </p>
      <DefinitionList<EffectivePainPointType>
        items={items}
        fields={[{ key: "name", getValue: (item) => item.name, placeholder: "Project Pain Point type name", ariaLabel: "Project Pain Point type name" }]}
        getReassignLabel={(item) => item.name}
        onMove={async (id, direction) => {
          const idx = items.findIndex((i) => i.id === id);
          const otherIdx = direction === "up" ? idx - 1 : idx + 1;
          if (idx === -1 || otherIdx < 0 || otherIdx >= items.length) return;
          const a = items[idx];
          const b = items[otherIdx];
          try {
            await projectPainPointApi.overrideType(projectId, a.id, { display_order: b.display_order });
            await projectPainPointApi.overrideType(projectId, b.id, { display_order: a.display_order });
            await reload();
          } catch (err) {
            showToast(toErrorMessage(err, "Could not reorder Pain Point types."), "error");
          }
        }}
        onRename={async (id, values) => {
          await projectPainPointApi.overrideType(projectId, id, { name: values.name });
          await reload();
        }}
        onAdd={async (values) => {
          const nextOrder = items.length === 0 ? 0 : Math.max(...items.map((i) => i.display_order)) + 1;
          await projectPainPointApi.createLocalType(projectId, values.name, nextOrder);
          showToast("Project Pain Point type created.");
          await reload();
        }}
        onDelete={async (id) => {
          const item = items.find((i) => i.id === id);
          if (item?.source === "org") {
            throw new Error("This is an organisation default with no project-specific override yet — there is nothing to delete. Disable it instead.");
          }
          try {
            await projectPainPointApi.deleteType(projectId, id);
          } catch (err) {
            if (err instanceof ApiError && err.status === 409) {
              // See `OrgPainPointTypesPanel.tsx`'s own comment on this exact
              // pattern — `{ cause }` predates this frontend's `tsconfig.json`
              // `lib`/`target` (ES2020), so it's set as a property assignment
              // rather than via the constructor's second argument.
              const wrapped = new Error(
                "This type is still used by at least one Pain Point in this project. Disable it instead of deleting it.",
              ) as Error & { cause?: unknown };
              wrapped.cause = err;
              throw wrapped;
            }
            throw err;
          }
          showToast("Project Pain Point type deleted.");
          await reload();
        }}
        deleteLabel="Delete Pain Point type"
        addLabel="Add project-only Pain Point type"
        renderExtra={(item) => (
          <span key="pp-type-extra" className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
            <span className="text-muted" style={{ fontSize: "0.75rem" }}>{SOURCE_LABEL[item.source]}</span>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Enabled</span>
            <ToggleSwitch
              checked={item.is_enabled}
              label={`Enabled: ${item.name}`}
              onChange={async (next) => {
                try {
                  await projectPainPointApi.overrideType(projectId, item.id, { is_enabled: next });
                  await reload();
                } catch (err) {
                  showToast(toErrorMessage(err, "Could not update this Pain Point type."), "error");
                }
              }}
            />
          </span>
        )}
      />
    </div>
  );
}
