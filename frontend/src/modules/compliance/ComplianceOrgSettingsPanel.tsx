/**
 * Module: modules/compliance/ComplianceOrgSettingsPanel
 *
 * The org-level Compliance settings panel (docs/compliance-module-plan.md
 * Phase 22) — so far, one field: this organisation's designated **default
 * compliance-managers group**, the SSO-friendly fallback that keeps a
 * standard from ever being left with no `standards_manager` at all (§3).
 * Every current member of the picked `OrgGroup` counts as an effective
 * standards manager for any standard in this org with no explicit grant of
 * its own — see `StandardMembersSection.tsx`'s own "last manager" disabled-
 * checkbox treatment for where this is actually consumed.
 *
 * A one-field "pick an existing group, or none" is a plain `<select>`, not
 * a bespoke picker component — mirrors `OrgGroup.granted_org_role`'s own
 * settings-surface simplicity one level down.
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { OrgGroup } from "../../api/types";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceOrgSettings } from "./types";

export function ComplianceOrgSettingsPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [settings, setSettings] = useState<ComplianceOrgSettings | null>(null);
  const [groups, setGroups] = useState<OrgGroup[] | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setSettings(null);
    setGroups(null);
    complianceApi.getComplianceOrgSettings(orgId).then(setSettings);
    api.get<OrgGroup[]>(`/api/v1/orgs/${orgId}/groups`).then(setGroups);
  }, [orgId]);

  async function handleChange(groupId: string) {
    setSaving(true);
    try {
      const updated = await complianceApi.updateComplianceOrgSettings(orgId, {
        default_standards_manager_group_id: groupId || null,
      });
      setSettings(updated);
      showToast("Compliance settings updated.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update the fallback group."), "error");
    } finally {
      setSaving(false);
    }
  }

  if (settings === null || groups === null) return <p>Loading…</p>;

  return (
    <div className="stack">
      <p className="text-muted">
        Every standard in this organisation must always have at least one Standards Manager. Where roles are
        SSO-managed, designate a fallback group here instead of assigning managers one at a time — every current
        member of this group counts as a Standards Manager for any standard with no explicit manager of its own.
      </p>
      <label className="stack" style={{ gap: "0.25rem", maxWidth: "24rem" }}>
        Default compliance-managers group
        <select
          className="input"
          value={settings.default_standards_manager_group_id ?? ""}
          disabled={saving}
          onChange={(e) => handleChange(e.target.value)}
        >
          <option value="">None configured</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
