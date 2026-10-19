/**
 * Module: pages/ServerModulesTab
 *
 * The "Modules" group of Server Management: the three server-tier levers over which modules
 * exist for whom.
 * - The default entitlement policy (open or closed).
 * - The server-wide default module states (available, and on for new projects), with an
 *   explicit "apply to all organisations" action.
 * - Per-organisation availability: grant or withdraw a module for one organisation and see
 *   which tier decides its effective state.
 *
 * Design decisions:
 * - Rows are the shared `ModuleSettingsList` and the three-state `ModuleAvailabilitySelect`
 *   the organisation and project pages use, so a module reads the same at every tier.
 * - Every control saves at once and ends in a toast; "apply to all" is Tier 2 because it
 *   overwrites other organisations' own choices (style guide, confirmation tiers).
 * - Nothing here names a module: the lists come from the API (module boundary).
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type {
  ApplyServerModuleDefaultsResult,
  ModuleEntitlementPolicy,
  Organization,
  OrgModuleEntitlement,
  ServerModuleDefault,
} from "../api/types";
import {
  fromModuleAvailability,
  MODULE_ENABLED_SOURCE_LABEL,
  MODULE_ENTITLEMENT_POLICY_LABEL,
  toModuleAvailability,
} from "../api/types";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LabeledSelect } from "../components/LabeledSelect";
import { ModuleAvailabilitySelect, ModuleSettingsList } from "../components/ModuleSettingsList";
import { Spinner } from "../components/Spinner";
import { ToggleSwitch } from "../components/ToggleSwitch";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { t } from "../i18n/strings";

const strings = t();

const POLICY_OPTIONS = (Object.keys(MODULE_ENTITLEMENT_POLICY_LABEL) as ModuleEntitlementPolicy[]).map((value) => ({
  value,
  label: MODULE_ENTITLEMENT_POLICY_LABEL[value],
}));

/** The default entitlement policy: a select that saves when changed. */
function EntitlementPolicySection() {
  const { showToast } = useToast();
  const orgLabelPlural = useOrgLabelPlural().toLowerCase();
  const [policy, setPolicy] = useState<ModuleEntitlementPolicy | null>(null);

  useEffect(() => {
    api
      .get<{ default_module_entitlement_policy: ModuleEntitlementPolicy }>("/api/v1/system/module-entitlement-policy")
      .then((r) => setPolicy(r.default_module_entitlement_policy))
      .catch((err) => showToast(toErrorMessage(err, strings.serverModules.loadError), "error"));
  }, [showToast]);

  async function change(next: ModuleEntitlementPolicy) {
    try {
      await api.put("/api/v1/system/module-entitlement-policy", { default_module_entitlement_policy: next });
      setPolicy(next);
      showToast(strings.serverModules.policySaved);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (policy === null) return <Spinner />;
  return (
    <CollapsibleSection sectionKey="serverModules.policy" title={strings.serverModules.policyTitle}>
      <p className="text-muted">{strings.serverModules.policyHint(orgLabelPlural)}</p>
      <LabeledSelect
        label={strings.serverModules.policyLabel}
        value={policy}
        onChange={(next) => change(next as ModuleEntitlementPolicy)}
        options={POLICY_OPTIONS}
        placeholder={null}
      />
    </CollapsibleSection>
  );
}

/** The server-wide default module states and the "apply to all organisations" action. */
function ServerDefaultsSection() {
  const { showToast } = useToast();
  const orgLabelPlural = useOrgLabelPlural().toLowerCase();
  const [defaults, setDefaults] = useState<ServerModuleDefault[] | null>(null);
  const [confirmApply, setConfirmApply] = useState(false);

  useEffect(() => {
    api
      .get<ServerModuleDefault[]>("/api/v1/system/module-defaults")
      .then(setDefaults)
      .catch((err) => showToast(toErrorMessage(err, strings.serverModules.loadError), "error"));
  }, [showToast]);

  async function change(module: ServerModuleDefault, availability: Parameters<typeof fromModuleAvailability>[0]) {
    const { enabled, default_project_enabled } = fromModuleAvailability(availability);
    try {
      const updated = await api.put<ServerModuleDefault>(`/api/v1/system/module-defaults/${module.module_key}`, {
        org_enabled: enabled,
        project_default_enabled: default_project_enabled,
      });
      setDefaults((prev) => prev && prev.map((d) => (d.module_key === updated.module_key ? updated : d)));
      showToast(strings.serverModules.defaultsToastSaved(module.name));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function apply() {
    setConfirmApply(false);
    try {
      const result = await api.post<ApplyServerModuleDefaultsResult>("/api/v1/system/module-defaults/apply", {});
      showToast(strings.serverModules.applyDone(result.organizations_changed, result.rows_written));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (defaults === null) return <Spinner />;
  return (
    <CollapsibleSection sectionKey="serverModules.defaults" title={strings.serverModules.defaultsTitle}>
      <p className="text-muted">{strings.serverModules.defaultsHint(orgLabelPlural)}</p>
      <ModuleSettingsList
        items={defaults.map((d) => ({
          key: d.module_key,
          name: d.name,
          description: d.description,
          hint: d.has_override ? strings.serverModules.serverDefault : strings.serverModules.builtInDefault,
          control: (
            <ModuleAvailabilitySelect
              value={toModuleAvailability(d.org_enabled, d.project_default_enabled)}
              label={strings.serverModules.availabilityLabel(d.name)}
              onChange={(next) => change(d, next)}
            />
          ),
        }))}
      />
      <div className="stack">
        <p className="text-muted">{strings.serverModules.applyHint(orgLabelPlural)}</p>
        <button className="btn" onClick={() => setConfirmApply(true)} style={{ alignSelf: "flex-start" }}>
          {strings.serverModules.applyButton(orgLabelPlural)}
        </button>
      </div>
      {confirmApply && (
        <ConfirmDialog
          title={strings.serverModules.applyTitle(orgLabelPlural)}
          message={strings.serverModules.applyMessage(orgLabelPlural, strings.serverModules.applyTyped)}
          confirmLabel={strings.serverModules.applyConfirm}
          requireTypedText={strings.serverModules.applyTyped}
          onConfirm={apply}
          onCancel={() => setConfirmApply(false)}
        />
      )}
    </CollapsibleSection>
  );
}

/** Per-organisation availability: pick an organisation, grant or withdraw each module. */
function OrganisationAvailabilitySection() {
  const { showToast } = useToast();
  const orgLower = useOrgLabel();
  const orgCapitalized = useOrgLabelCapitalized();
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [orgId, setOrgId] = useState("");
  // Rows are stored with the organisation they were loaded for, so a stale list is never shown
  // for a newly chosen organisation and no reset is needed when the choice changes.
  const [loaded, setLoaded] = useState<{ orgId: string; rows: OrgModuleEntitlement[] } | null>(null);
  const modules = loaded && loaded.orgId === orgId ? loaded.rows : null;

  useEffect(() => {
    api
      .get<Organization[]>("/api/v1/orgs")
      .then(setOrgs)
      .catch((err) => showToast(toErrorMessage(err, strings.serverModules.loadError), "error"));
  }, [showToast]);

  useEffect(() => {
    if (!orgId) return;
    let current = true;
    api
      .get<OrgModuleEntitlement[]>(`/api/v1/system/orgs/${orgId}/module-entitlements`)
      .then((rows) => current && setLoaded({ orgId, rows }))
      .catch((err) => showToast(toErrorMessage(err, strings.serverModules.loadError), "error"));
    return () => {
      current = false;
    };
  }, [orgId, showToast]);

  async function setEntitled(module: OrgModuleEntitlement, entitled: boolean) {
    try {
      await api.put(`/api/v1/system/orgs/${orgId}/module-entitlements/${module.module_key}`, { entitled });
      // The effective state of every module can depend on this one, so reload the whole list.
      const rows = await api.get<OrgModuleEntitlement[]>(`/api/v1/system/orgs/${orgId}/module-entitlements`);
      setLoaded({ orgId, rows });
      showToast(strings.serverModules.entitledToast(module.name, entitled));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  return (
    <CollapsibleSection sectionKey="serverModules.organisations" title={strings.serverModules.orgTitle(orgLower)}>
      <p className="text-muted">{strings.serverModules.orgHint(orgLower)}</p>
      {orgs === null ? (
        <Spinner />
      ) : (
        <LabeledSelect
          label={orgCapitalized}
          value={orgId}
          onChange={setOrgId}
          options={orgs.map((o) => ({ value: o.id, label: o.name }))}
          placeholder={strings.serverModules.orgPickerPlaceholder(orgLower)}
        />
      )}
      {orgId && modules === null && <Spinner />}
      {modules && (
        <ModuleSettingsList
          items={modules.map((m) => ({
            key: m.module_key,
            name: m.name,
            hint: `${strings.serverModules.stateSummary(m.enabled, MODULE_ENABLED_SOURCE_LABEL[m.enabled_source])} · ${
              m.has_override ? strings.serverModules.overridden : strings.serverModules.followsPolicy
            }`,
            control: (
              <ToggleSwitch
                checked={m.entitled}
                label={strings.serverModules.entitledLabel(m.name)}
                onChange={(next) => setEntitled(m, next)}
              />
            ),
          }))}
        />
      )}
    </CollapsibleSection>
  );
}

/** The Server Management "Modules" group. */
export function ServerModulesTab() {
  return (
    <div className="stack">
      <EntitlementPolicySection />
      <ServerDefaultsSection />
      <OrganisationAvailabilitySection />
    </div>
  );
}
