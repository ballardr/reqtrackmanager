import { Pencil, Power, Trash2 } from "lucide-react";
import { ImportWarnings } from "../components/ImportWarnings";
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Organization, OrgCreationChoice, OrgImportResult } from "../api/types";
import { ActionMenu } from "../components/ActionMenu";
import { BundleImportDialog } from "../components/BundleImportDialog";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FilterBadge } from "../components/FilterBadge";
import { FilterPanel } from "../components/FilterPanel";
import { FilterSelect } from "../components/FilterSelect";
import { ListPageLayout } from "../components/ListPageLayout";
import { Modal } from "../components/Modal";
import { Spinner } from "../components/Spinner";
import { SplitButtonTrigger } from "../components/SplitButtonTrigger";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { useToast } from "../context/ToastContext";
import { FormActions } from "../components/FormActions";
import { FormGrid } from "../components/FormGrid";
import { TextField, CheckboxField } from "../components/FormFields";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useUrlChoice, useUrlText } from "../hooks/useUrlFilter";

/**
 * Server-admin console listing every organisation on the deployment
 * (`GET /orgs` already returns all orgs for a server admin, scoped to the
 * caller's own memberships for everyone else) plus creation, and the two
 * lifecycle actions available for an existing one:
 *
 * - **Disable/enable**: reversible, no data touched — blocks every org/
 *   project-scoped request for everyone, including the org's own admins,
 *   until re-enabled (e.g. a hosting customer stopped paying).
 * - **Delete**: irreversible, gated behind typing the organisation's exact
 *   name to confirm — permanently removes everything it owns (projects,
 *   requirements, files, ...). See docs/decisions.md's "Organisation
 *   disable and hard delete" section for the full design.
 */
type StatusFilter = "active" | "disabled" | "all";
const STATUS_PARAMS: readonly StatusFilter[] = ["disabled", "all"];

export function ServerOrganisationsPage() {
  const strings = useStrings();
  const navigate = useNavigate();
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const orgLabelPlural = useOrgLabelPlural();
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  // Search and the status filter live in the URL so the list comes back as it was left after a visit to an organisation.
  const [search, setSearch] = useUrlText("q");
  // Defaults to "active" (C-A-13-adjacent hygiene): a deployment that's
  // been running a while accumulates disabled orgs (non-payment, offboarded
  // customers, ...) that would otherwise dominate a plain, unfiltered list.
  const [statusParam, setStatusParam] = useUrlChoice("status", STATUS_PARAMS);
  const statusFilter: StatusFilter = statusParam || "active";
  const setStatusFilter = (next: StatusFilter) => setStatusParam(next === "active" ? "" : next);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [showImportForm, setShowImportForm] = useState(false);
  // Every registered module's
  // optional org-creation seeding choices (e.g. Decision Management's ADR
  // template packs), fetched once and rendered generically; this page has
  // no hardcoded knowledge of what any of them are. `null` selected keys
  // means "not yet initialised from the fetched defaults."
  const [creationChoices, setCreationChoices] = useState<OrgCreationChoice[] | null>(null);
  const [selectedChoiceKeys, setSelectedChoiceKeys] = useState<Set<string> | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [importWarnings, setImportWarnings] = useState<string[] | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletingOrgId, setDeletingOrgId] = useState<string | null>(null);
  // ConfirmDialog (Tier 1) state for disable — converted from
  // `window.confirm` per the sixth-pass audit's "Confirmation and feedback
  // rollout, precisely" list. Delete already uses ConfirmDialog (Tier 2).
  const [disablingOrgId, setDisablingOrgId] = useState<string | null>(null);
  const { showToast } = useToast();

  async function reload() {
    setOrgs(await api.get<Organization[]>("/api/v1/orgs"));
  }

  useLoadOnChange(reload, []);

  useEffect(() => {
    // Fetched once, independent of the modal opening — the checkboxes only
    // need to be ready by the time a server admin opens the "New Org" form,
    // and this page's own load is a rare, admin-only action so the extra
    // request is not worth deferring behind `showNewForm`.
    api.get<OrgCreationChoice[]>("/api/v1/orgs/creation-choices").then((choices) => {
      setCreationChoices(choices);
      setSelectedChoiceKeys(new Set(choices.filter((c) => c.default_selected).map((c) => c.key)));
    });
  }, []);

  function toggleChoiceKey(key: string) {
    setSelectedChoiceKeys((prev) => {
      const next = new Set(prev ?? []);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function createOrg() {
    setCreateError(null);
    try {
      await api.post("/api/v1/orgs", {
        name: newName,
        module_choice_keys: selectedChoiceKeys ? Array.from(selectedChoiceKeys) : undefined,
      });
      setNewName("");
      setShowNewForm(false);
      reload();
      showToast(strings.serverOrgs.createdToast(orgLabelCap));
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  /**
   * Full-fidelity organisation bundle import (`services.org_export`): creates a brand-new organisation from an
   * exported bundle (settings, members, report layouts and every project's structure and history), for backup
   * restore, offboarding or cross-instance migration. Module-contributed creation choices do not apply: the
   * bundle carries its own settings, so there is nothing fresh to seed. An error is thrown to
   * `BundleImportDialog`, which shows it.
   */
  async function importOrg(file: File, skipFiles: boolean) {
    const result = await api.postFile<OrgImportResult>("/api/v1/orgs/import", file, {
      name: newName, ...(skipFiles ? { skip_files: "true" } : {}),
    });
    if (result.warnings.length > 0) setImportWarnings(result.warnings);
    setNewName("");
    setShowImportForm(false);
    reload();
    showToast(strings.serverOrgs.createdToast(orgLabelCap));
  }

  async function runAction(action: () => Promise<void>, successMessage?: string) {
    setActionError(null);
    try {
      await action();
      await reload();
      if (successMessage) showToast(successMessage);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  function disableOrg(org: Organization) {
    setDisablingOrgId(org.id);
  }

  function confirmDisable(org: Organization) {
    setDisablingOrgId(null);
    runAction(() => api.post(`/api/v1/orgs/${org.id}/disable`), strings.serverOrgs.disabledToast(orgLabelCap));
  }

  function enableOrg(org: Organization) {
    runAction(() => api.post(`/api/v1/orgs/${org.id}/enable`), strings.serverOrgs.enabledToast(orgLabelCap));
  }

  function startDelete(org: Organization) {
    setActionError(null);
    setDeletingOrgId(org.id);
  }

  function cancelDelete() {
    setDeletingOrgId(null);
  }

  async function confirmDelete(org: Organization) {
    await runAction(async () => {
      await api.delete(`/api/v1/orgs/${org.id}`, { confirm_name: org.name });
    }, strings.serverOrgs.deletedToast(orgLabelCap));
    setDeletingOrgId(null);
  }

  if (!orgs) return <Spinner />;

  const filteredOrgs = orgs.filter((o) => {
    if (statusFilter === "active" && !o.is_active) return false;
    if (statusFilter === "disabled" && o.is_active) return false;
    if (search && !o.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="stack">
      <ListPageLayout
        title={strings.orgAdmin.organizations(orgLabelPlural)}
        actions={
          <SplitButtonTrigger
            icon={<Plus />}
            label={strings.serverOrgs.newOrganization(orgLabel)}
            onDefaultAction={() => setShowNewForm(true)}
            menuTitle={strings.serverOrgs.newOrganization(orgLabel)}
            moreOptionsLabel={strings.common.moreOptions}
            alternatives={[{ label: strings.serverOrgs.importOrganization(orgLabel), onSelect: () => setShowImportForm(true) }]}
          />
        }
        filter={
          <FilterPanel sectionKey="serverOrganisationsFilters">
            <FilterSelect
              label={strings.filters.status}
              value={statusFilter}
              onChange={setStatusFilter}
              options={[{ value: "active", label: strings.serverOrgs.active }, { value: "disabled", label: strings.serverOrgs.disabled }, { value: "all", label: strings.serverOrgs.filterAll }]}
            />
          </FilterPanel>
        }
      >
        {/* Style guide "Pattern: modal dialog for entity create/rename" —
            a brand-new entity opens in a Modal, not a permanently-visible
            inline block that reflows the list underneath it. */}
        {showNewForm && (
          <Modal title={strings.serverOrgs.newOrganization(orgLabel)} onClose={() => setShowNewForm(false)} size="lg">
            <div className="stack">
              <FormGrid minColumn="18rem">
                <TextField helpNotNeeded required
                  label={strings.serverOrgs.organizationName(orgLabelCap)}
                  value={newName}
                  onChange={setNewName}
                  inputProps={{ autoFocus: true }}
                />
              </FormGrid>
              {/* Every registered
                  module's optional org-creation seeding choices, grouped by
                  `group_label`; this page has no hardcoded knowledge of what
                  any of them are. */}
              {creationChoices && creationChoices.length > 0 && (
                <div className="stack" style={{ gap: "var(--space-3)" }}>
                  {[...new Set(creationChoices.map((c) => c.group_label))].map((groupLabel) => (
                    <div key={groupLabel} className="stack" style={{ gap: "var(--space-1)" }}>
                      <strong>{groupLabel}</strong>
                      {creationChoices
                        .filter((c) => c.group_label === groupLabel)
                        .map((choice) => (
                          <CheckboxField helpNotNeeded
                            key={choice.key}
                            label={choice.label}
                            title={choice.description}
                            checked={selectedChoiceKeys?.has(choice.key) ?? false}
                            onChange={() => toggleChoiceKey(choice.key)}
                          />
                        ))}
                    </div>
                  ))}
                </div>
              )}
              <FormActions
                error={createError}
                onCancel={() => setShowNewForm(false)}
                onSave={createOrg}
                saveLabel={strings.common.create}
                saveDisabled={!newName}
              />
            </div>
          </Modal>
        )}
        {showImportForm && (
          <BundleImportDialog
            title={strings.serverOrgs.importOrganization(orgLabel)}
            fileLabel={strings.serverOrgs.bundleFile(orgLabelCap)}
            fileHelp={strings.help.importOrganizationBundle(orgLabel)}
            onClose={() => setShowImportForm(false)}
            onImport={importOrg}
          >
            <TextField help={strings.help.importOrganizationName(orgLabel)}
              label={strings.serverOrgs.organizationName(orgLabelCap)}
              value={newName}
              onChange={setNewName}
              inputProps={{ autoFocus: true }}
            />
          </BundleImportDialog>
        )}
        <ImportWarnings warnings={importWarnings} title={strings.projects.importWarnings} />

        {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}
          <div className="stack">
            <input
              className="input"
              style={{ maxWidth: 280 }}
              placeholder={strings.serverOrgs.search(orgLabelPlural)}
              aria-label={strings.serverOrgs.search(orgLabelPlural)}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />

            <div className="card" style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredOrgs.map((o) => (
                    <tr key={o.id}>
                      <td>{o.name}</td>
                      <td>
                        {o.is_active ? (
                          <FilterBadge active={statusFilter === "active"} onClick={() => setStatusFilter("active")}>
                            {strings.serverOrgs.active}
                          </FilterBadge>
                        ) : (
                          <FilterBadge
                            active={statusFilter === "disabled"}
                            onClick={() => setStatusFilter("disabled")}
                            style={{ color: "var(--color-danger)", borderColor: "var(--color-danger)" }}
                          >
                            {strings.serverOrgs.disabled}
                          </FilterBadge>
                        )}
                      </td>
                      <td className="text-muted">{new Date(o.created_at).toLocaleDateString()}</td>
                      <td>
                        <div className="row" style={{ justifyContent: "flex-end" }}>
                          {/* Style guide "Pattern: action menu" — three
                              standalone row buttons (Edit/Disable-Enable/
                              Delete) consolidated into one `ActionMenu`, per
                              the addendum applying the same two-or-more-
                              actions threshold inside a table row. Each item
                              still opens the exact same dialog/navigation as
                              before — the menu is just the entry point, not a
                              replacement for either `ConfirmDialog` tier. */}
                          <ActionMenu
                            triggerLabel={strings.serverOrgs.actionsFor(o.name)}
                            items={[
                              { label: strings.common.edit, icon: <Pencil size={14} />, onSelect: () => navigate(`/orgs/${o.id}/admin`) },
                              o.is_active
                                ? { label: strings.serverOrgs.disable, icon: <Power size={14} />, onSelect: () => disableOrg(o) }
                                : { label: strings.serverOrgs.enable, icon: <Power size={14} />, onSelect: () => enableOrg(o) },
                              { label: strings.serverOrgs.delete, icon: <Trash2 size={14} />, onSelect: () => startDelete(o) },
                            ]}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {orgs.length === 0 && <p className="text-muted">No {orgLabelPlural.toLowerCase()} yet.</p>}
              {orgs.length > 0 && filteredOrgs.length === 0 && <p className="text-muted">{strings.serverOrgs.empty(orgLabelPlural)}</p>}
            </div>
          </div>
      </ListPageLayout>

      {deletingOrgId &&
        (() => {
          const org = orgs.find((o) => o.id === deletingOrgId);
          if (!org) return null;
          return (
            <ConfirmDialog
              title={strings.serverOrgs.deleteTitle(orgLabel)}
              message={strings.serverOrgs.deleteHint(org.name, orgLabel)}
              confirmLabel={strings.serverOrgs.deleteConfirmButton}
              requireTypedText={org.name}
              onConfirm={() => confirmDelete(org)}
              onCancel={cancelDelete}
            />
          );
        })()}

      {disablingOrgId &&
        (() => {
          const org = orgs.find((o) => o.id === disablingOrgId);
          if (!org) return null;
          return (
            <ConfirmDialog
              title={strings.serverOrgs.disableTitle.replace("{name}", org.name)}
              message={strings.serverOrgs.disableConfirm}
              confirmLabel={strings.serverOrgs.disable}
              onConfirm={() => confirmDisable(org)}
              onCancel={() => setDisablingOrgId(null)}
            />
          );
        })()}
    </div>
  );
}
