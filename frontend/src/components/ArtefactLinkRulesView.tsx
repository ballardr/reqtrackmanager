import { useState } from "react";

import { api } from "../api/client";
import type { ArtefactLinkRule, LinkTypeDefinition } from "../api/types";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { ConfirmDialog } from "./ConfirmDialog";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { OverridePill } from "./OverridePill";

const strings = t();

/**
 * "By artefact type": for every artefact type of the organisation, which link
 * types it may use. No rule means any link type (shown as such, with
 * `OverridePill`'s "no override" state); limiting one starts from all link
 * types checked, so nothing changes until a type is unchecked. A rule must keep
 * at least one link type, and removing it asks for a Tier-1 confirmation. Every
 * change is saved at once and confirmed with a Toast; existing links are never
 * touched (rules apply when a link is made).
 */
export function ArtefactLinkRulesView({
  orgId,
  linkTypes,
  rules,
  onChanged,
}: {
  orgId: string;
  linkTypes: LinkTypeDefinition[];
  rules: ArtefactLinkRule[];
  onChanged: () => Promise<void>;
}) {
  const { showToast } = useToast();
  const [removing, setRemoving] = useState<ArtefactLinkRule | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  async function saveRule(rule: ArtefactLinkRule, ids: string[]) {
    setSaving(rule.artefact_type);
    try {
      await api.put(`/api/v1/orgs/${orgId}/artefact-link-rules/${rule.artefact_type}`, { link_type_ids: ids });
      showToast(strings.orgAdmin.artefactRuleUpdated);
      await onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, strings.orgAdmin.artefactRuleFailed), "error");
    } finally {
      setSaving(null);
    }
  }

  async function removeRule(rule: ArtefactLinkRule) {
    setRemoving(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/artefact-link-rules/${rule.artefact_type}`);
      showToast(strings.orgAdmin.artefactRuleRemoved);
      await onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, strings.orgAdmin.artefactRuleFailed), "error");
    }
  }

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.artefactRulesHint}</p>
      {rules.map((rule) => {
        const allowed = rule.link_type_ids;
        const onlyOne = allowed !== null && allowed.length <= 1;
        return (
          <div
            key={rule.artefact_type}
            className="row"
            style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}
          >
            <strong style={{ minWidth: 180 }}>{rule.label}</strong>
            <div className="row">
              <OverridePill
                custom={allowed !== null}
                defaultLabel={strings.orgAdmin.artefactRuleAny}
                resetLabel={strings.orgAdmin.artefactRuleReset}
                onReset={() => setRemoving(rule)}
                disabled={saving === rule.artefact_type}
              />
              <MultiSelectDropdown
                triggerLabel={strings.orgAdmin.artefactRuleLabel(rule.label)}
                emptyLabel={strings.orgAdmin.artefactRuleAny}
                options={linkTypes.map((lt) => {
                  const checked = allowed === null || allowed.includes(lt.id);
                  const lastOne = onlyOne && checked;
                  return {
                    value: lt.id,
                    label: lt.forward_name,
                    checked,
                    disabled: saving === rule.artefact_type || lastOne,
                    title: lastOne ? strings.orgAdmin.artefactRuleLastTypeHint : undefined,
                    optionLabel: `${rule.label}: ${lt.forward_name}`,
                    onToggle: () => {
                      const current = allowed ?? linkTypes.map((x) => x.id);
                      void saveRule(
                        rule,
                        checked ? current.filter((id) => id !== lt.id) : [...current, lt.id],
                      );
                    },
                  };
                })}
              />
            </div>
          </div>
        );
      })}
      {removing && (
        <ConfirmDialog
          title={strings.orgAdmin.artefactRuleRemoveTitle(removing.label)}
          message={strings.orgAdmin.artefactRuleRemoveMessage(removing.label)}
          confirmLabel={strings.orgAdmin.artefactRuleRemoveConfirm}
          onConfirm={() => void removeRule(removing)}
          onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  );
}
