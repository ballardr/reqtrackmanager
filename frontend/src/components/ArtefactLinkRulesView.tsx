import { useState } from "react";

import { api } from "../api/client";
import type { ArtefactLinkRule, LinkTypeDefinition, ProjectArtefactLinkRule } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { ConfirmDialog } from "./ConfirmDialog";
import type { LinkTypesScope } from "./LinkTypesPanel";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { OverridePill } from "./OverridePill";

/** A project-scope rule carries where it comes from; an organisation rule does not. */
function isProjectRule(rule: ArtefactLinkRule | ProjectArtefactLinkRule): rule is ProjectArtefactLinkRule {
  return "own" in rule;
}

/**
 * "By artefact type": for every artefact type, which link types it may use.
 * No rule means any link type (shown as such, with `OverridePill`'s "no
 * override" state); limiting one starts from all link types checked, so nothing
 * changes until a type is unchecked. A rule must keep at least one link type,
 * and removing it asks for a Tier-1 confirmation. Every change is saved at once
 * and confirmed with a Toast; existing links are never touched (rules apply when
 * a link is made).
 *
 * Organisation scope edits the organisation's rules. Project scope shows the
 * rule each artefact type resolves to for the project (its own, else a parent's,
 * else the organisation's: the nearest wins and replaces the farther one
 * entirely, so a project can allow more as well as less); the pill names the
 * source and "Use inherited rule" drops the project's own. `readOnly` while the
 * organisation locks customisation.
 */
export function ArtefactLinkRulesView({
  scope,
  linkTypes,
  rules,
  readOnly = false,
  onChanged,
}: {
  scope: LinkTypesScope;
  linkTypes: LinkTypeDefinition[];
  rules: Array<ArtefactLinkRule | ProjectArtefactLinkRule>;
  readOnly?: boolean;
  onChanged: () => Promise<void>;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [removing, setRemoving] = useState<ArtefactLinkRule | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const rulesBase =
    scope.kind === "project" ? `/api/v1/projects/${scope.projectId}/artefact-link-rules` : `/api/v1/orgs/${scope.orgId}/artefact-link-rules`;

  async function saveRule(rule: ArtefactLinkRule, ids: string[]) {
    setSaving(rule.artefact_type);
    try {
      await api.put(`${rulesBase}/${rule.artefact_type}`, { link_type_ids: ids });
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
      await api.delete(`${rulesBase}/${rule.artefact_type}`);
      showToast(strings.orgAdmin.artefactRuleRemoved);
      await onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, strings.orgAdmin.artefactRuleFailed), "error");
    }
  }

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>
        {scope.kind === "project" ? strings.orgAdmin.artefactRuleProjectHint : strings.orgAdmin.artefactRulesHint}
      </p>
      {readOnly && (
        <div role="status" className="badge" style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.projectLinkTypesRulesLocked}
        </div>
      )}
      {rules.map((rule) => {
        const allowed = rule.link_type_ids;
        const onlyOne = allowed !== null && allowed.length <= 1;
        const projectRule = isProjectRule(rule) ? rule : null;
        // Organisation scope: a rule exists or not. Project scope: the rule is "custom" only when this
        // project holds it; one from a parent or the organisation is inherited, and says so.
        const custom = projectRule ? projectRule.own : allowed !== null;
        const sourceLabel = !projectRule || projectRule.source === null
          ? strings.orgAdmin.artefactRuleAny
          : projectRule.source === "organization"
            ? strings.orgAdmin.artefactRuleSourceOrganization
            : strings.orgAdmin.artefactRuleSourceInherited(projectRule.source_project_name);
        return (
          <div
            key={rule.artefact_type}
            className="row"
            style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}
          >
            <strong style={{ minWidth: 180 }}>{rule.label}</strong>
            <div className="row">
              <OverridePill
                custom={custom}
                defaultLabel={sourceLabel}
                resetLabel={projectRule ? strings.orgAdmin.artefactRuleUseInherited : strings.orgAdmin.artefactRuleReset}
                onReset={readOnly ? undefined : () => setRemoving(rule)}
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
                    disabled: readOnly || saving === rule.artefact_type || lastOne,
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
          title={scope.kind === "project" ? strings.orgAdmin.artefactRuleUseInheritedTitle(removing.label) : strings.orgAdmin.artefactRuleRemoveTitle(removing.label)}
          message={scope.kind === "project" ? strings.orgAdmin.artefactRuleUseInheritedMessage(removing.label) : strings.orgAdmin.artefactRuleRemoveMessage(removing.label)}
          confirmLabel={scope.kind === "project" ? strings.orgAdmin.artefactRuleUseInherited : strings.orgAdmin.artefactRuleRemoveConfirm}
          onConfirm={() => void removeRule(removing)}
          onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  );
}
