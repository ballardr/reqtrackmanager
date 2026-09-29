/**
 * Module: modules/context_strategy/OrgPainPointTypesPanel
 *
 * The organisation-scoped shared base tier of Pain Point's type vocabulary
 * (Phase 0 Q3's two-tier model, source overview §6.2) — a plain, ordered,
 * flat "definition" list, so this reuses `DefinitionList` verbatim for
 * rename/reorder/add/delete-with-409, the same way `modules/decisions/
 * DecisionTypesPanel.tsx` does for Decision Types. Extended with `renderExtra`
 * for the `is_active` enable/disable toggle (§6.2 "Disable types") — checked
 * `modules/compliance/MappingTypesPanel.tsx` first for precedent on a
 * `DefinitionList` boolean toggle via `renderExtra` (its own
 * `implies_equivalence` toggle) rather than inventing a new prop on the
 * shared component; `ActionTypesPanel.tsx` has no such toggle to check
 * against (Action Types have no enable/disable concept), so `MappingTypesPanel`
 * is this component's actual precedent.
 *
 * **Placement: `orgAdminSections` (Org Management), not `orgOverviewSections`
 * (Org Dashboard) — a deliberate divergence from where Strategy's/Future
 * State's own org-scoped panels landed (Decided by: Agent).** Checked this
 * module's own Phase 7.1 precedent first: `OrgStrategiesPanel.tsx` reasoned
 * that an org-scoped Strategy is org-level *content* a Strategy Owner/
 * Approver works with day to day, closer to Compliance's dashboards than to
 * a configuration table, and explicitly flagged "revisit if a later
 * sub-phase's own org/project-scoped artefact suggests a different, more
 * consistent placement." Pain Point Type is not that case, though — it is
 * this module's *first* actual configuration-table surface (a type
 * vocabulary an org admin manages, not day-to-day artefact content), the
 * same distinction `DecisionTemplatesPanel.tsx` already draws between an org
 * admin managing a template library on Org Management versus day-to-day
 * Decision content on a project's own working page. `PainPointTypeDefinition`
 * is structurally identical in kind to `DecisionTemplateDefinition`, not to
 * `Strategy`, so it follows that placement instead.
 *
 * Gated on the `pain_point_type_admin` module role, enforced entirely
 * server-side (mutations 403 without it) — this panel itself renders
 * unconditionally to whoever can reach Org Management, matching
 * `DecisionTemplatesPanel.tsx`'s own gating approach (no client-side role
 * check; every mutating control always renders, a 403 surfaces as a toast
 * via `DefinitionList`'s own error handling).
 *
 * **`onDelete` re-throws a plain `Error` on a 409, rather than letting
 * `DefinitionList`'s built-in reassign-on-409 flow open (Decided by:
 * Agent).** `DefinitionList.handleAttemptDelete` treats *any* `ApiError`
 * with `status === 409` as "in use, offer to reassign" — correct for
 * `DecisionTypesPanel.tsx`/`ActionTypesPanel.tsx`, whose backends really do
 * support reassignment on delete. This org tier's own `DELETE .../pain-
 * point-types/{id}` has **no reassignment parameter at all** — Phase 3's own
 * design (`service.delete_org_pain_point_type`'s docstring) blocks outright
 * while any project still references the type, since one org type can be
 * referenced by override rows across many projects at once with no single
 * correct cross-project reassignment target. Silently letting
 * `DefinitionList` open its reassign picker here would let an admin pick a
 * target, click confirm, and watch it 409 again for the same reason,
 * indefinitely — so this catches the 409 here first and re-throws a plain
 * `Error` whose message tells the admin to disable the type instead,
 * routing `DefinitionList` into its plain-error path (`setError`, a red
 * banner) rather than its reassign-picker path.
 */
import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { DefinitionList } from "../../components/DefinitionList";
import { Spinner } from "../../components/Spinner";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgPainPointTypeApi } from "./api";
import type { PainPointTypeDefinition } from "./types";

export function OrgPainPointTypesPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [items, setItems] = useState<PainPointTypeDefinition[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function reload() {
    try {
      setItems(await orgPainPointTypeApi.list(orgId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load Pain Point types."));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (items === null) return <Spinner />;

  return (
    <div className="stack">
      <p className="text-muted">
        The shared Pain Point type vocabulary every project in this organisation sees by default (Market, User, and
        Operator are seeded automatically for a new organisation — §6.2). A project may locally rename, disable, or
        add its own types without affecting this list or any other project.
      </p>
      <DefinitionList<PainPointTypeDefinition>
        items={items}
        fields={[{ key: "name", getValue: (item) => item.name, placeholder: "Pain Point type name", ariaLabel: "Pain Point type name" }]}
        getReassignLabel={(item) => item.name}
        onMove={async (id, direction) => {
          await orgPainPointTypeApi.move(orgId, id, direction);
          await reload();
        }}
        onRename={async (id, values) => {
          await orgPainPointTypeApi.update(orgId, id, { name: values.name });
          await reload();
        }}
        onAdd={async (values) => {
          await orgPainPointTypeApi.create(orgId, values.name);
          showToast("Pain Point type created.");
          await reload();
        }}
        onDelete={async (id) => {
          try {
            await orgPainPointTypeApi.delete(orgId, id);
          } catch (err) {
            if (err instanceof ApiError && err.status === 409) {
              // `{ cause }` is a real runtime `Error` feature this codebase's
              // `tsconfig.json` `lib`/`target` (ES2020) predates the type
              // declarations for — set as a plain property assignment rather
              // than via the constructor's second argument, to preserve the
              // causal chain (`preserve-caught-error`) without bumping the
              // whole frontend's TypeScript lib target for one call site.
              const wrapped = new Error(
                "This type is still used by at least one project. Disable it instead of deleting it.",
              ) as Error & { cause?: unknown };
              wrapped.cause = err;
              throw wrapped;
            }
            throw err;
          }
          showToast("Pain Point type deleted.");
          await reload();
        }}
        deleteLabel="Delete Pain Point type"
        addLabel="Add Pain Point type"
        renderExtra={(item) => (
          <span key="is-active" className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Active</span>
            <ToggleSwitch
              checked={item.is_active}
              label={`Active: ${item.name}`}
              onChange={async (next) => {
                try {
                  await orgPainPointTypeApi.update(orgId, item.id, { is_active: next });
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
