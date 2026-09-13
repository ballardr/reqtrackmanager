/**
 * Module: modules/compliance/MappingTypesPanel
 *
 * The organisation-scoped cross-standard mapping relationship-type
 * vocabulary (§19 — Equivalent/Satisfies/Derived From/Related To/Overlaps/
 * Conflicts With are examples, not a fixed enum; an org defines its own).
 * Reuses `DefinitionList` for the shared rename/reorder/add/
 * delete-with-reassign shape, extended with its new `renderExtra` slot
 * (added alongside this panel, see `DefinitionList.tsx`) for
 * `implies_equivalence` — a boolean `DefinitionList`'s own text-only
 * `fields` contract can't express. Toggling it is a separate call from
 * renaming (both go through the same `PATCH` endpoint, which replaces both
 * fields together, so each handler always sends the other field's current,
 * unchanged value alongside the one it's actually changing).
 */
import { useEffect, useState } from "react";

import { DefinitionList } from "../../components/DefinitionList";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceMappingRelationshipType } from "./types";

export function MappingTypesPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [items, setItems] = useState<ComplianceMappingRelationshipType[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      setItems(await complianceApi.listMappingRelationshipTypes(orgId));
      setError(null);
    } catch (err) {
      setError(toErrorMessage(err, "Could not load mapping relationship types."));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  if (error) return <div style={{ color: "var(--color-danger)" }}>{error}</div>;
  if (items === null) return <p>Loading…</p>;

  return (
    <div className="stack">
      <p className="text-muted">
        The relationship types available when mapping one compliance requirement to another across standards or
        versions (§19). "Implies equivalence" controls whether a "replaced" pair linked by this type may later be
        offered for assessment carry-forward when a project migrates to a newer standard version (§27).
      </p>
      <DefinitionList<ComplianceMappingRelationshipType>
        items={items}
        fields={[{ key: "name", getValue: (item) => item.name, placeholder: "Relationship type name", ariaLabel: "Relationship type name" }]}
        getReassignLabel={(item) => item.name}
        onMove={async (id, direction) => {
          await complianceApi.moveMappingRelationshipType(orgId, id, direction);
          await reload();
        }}
        onRename={async (id, values) => {
          const current = items.find((i) => i.id === id);
          await complianceApi.updateMappingRelationshipType(orgId, id, values.name, current?.implies_equivalence ?? false);
          await reload();
        }}
        onAdd={async (values) => {
          await complianceApi.createMappingRelationshipType(orgId, values.name, false);
          showToast("Relationship type created.");
          await reload();
        }}
        onDelete={async (id, reassignToId) => {
          await complianceApi.deleteMappingRelationshipType(orgId, id, reassignToId);
          showToast("Relationship type deleted.");
          await reload();
        }}
        deleteLabel="Delete relationship type"
        addLabel="Add relationship type"
        renderExtra={(item) => (
          <span key="implies-equivalence" className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Implies equivalence</span>
            <ToggleSwitch
              checked={item.implies_equivalence}
              label={`Implies equivalence for ${item.name}`}
              onChange={async (next) => {
                try {
                  await complianceApi.updateMappingRelationshipType(orgId, item.id, item.name, next);
                  await reload();
                } catch (err) {
                  showToast(toErrorMessage(err, "Could not update relationship type."), "error");
                }
              }}
            />
          </span>
        )}
      />
    </div>
  );
}
