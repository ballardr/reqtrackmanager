import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import {
  LINK_FLOW_LABEL,
  LINK_FLOW_VALUES,
  type ArtefactLinkRule,
  type ArtefactTypeOption,
  type LinkFlow,
  type LinkTypeDefinition,
  type LinkTypeDeleteOutcome,
  type LinkTypeUsage,
  type ProjectArtefactLinkRule,
  type ProjectCustomisation,
  type ProjectLinkType,
  type ProjectLinkTypes,
} from "../api/types";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";
import { ArtefactLinkRulesView } from "./ArtefactLinkRulesView";
import { ConfirmDialog } from "./ConfirmDialog";
import { DefinitionList, type DeleteInUseConfig } from "./DefinitionList";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { ProjectLinkTypeRow } from "./ProjectLinkTypeRow";
import { Spinner } from "./Spinner";
import { Tabs, tabPanelProps, type TabDef } from "./Tabs";
import { ToggleSwitch } from "./ToggleSwitch";

type PanelTab = "types" | "rules";

/** Which vocabulary the panel administers: the organisation's own, or what one project sees and may change. */
export type LinkTypesScope =
  | { kind: "organization"; orgId: string }
  | { kind: "project"; orgId: string; projectId: string };

/** The label for an artefact type the registry no longer lists (a restriction
 * saved before its module was uninstalled), so a stored value never shows raw. */
function humaniseArtefactType(type: string): string {
  const text = type.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

interface PanelData {
  /** The types this scope may edit (all of the organisation's; the project's own). */
  editable: LinkTypeDefinition[];
  /** The types shown read-only (a project's organisation-wide and inherited types). */
  others: ProjectLinkType[];
  /** Every type a project reaches (its own included), for choosing in its rules. */
  reachable: ProjectLinkType[];
  /** The organisation forbids project-level changes. */
  locked: boolean;
  artefactTypes: ArtefactTypeOption[];
  rules: Array<ArtefactLinkRule | ProjectArtefactLinkRule>;
  /** Organisation scope only. */
  customisation: ProjectCustomisation | null;
}

/**
 * The link types of one scope: the vocabulary (names for both directions,
 * direction of flow, and which kinds of record each may join) and, on a second
 * tab, which link types each artefact type may use.
 *
 * Organisation scope edits the organisation-wide set and holds the switch that
 * forbids projects from customising. Project scope shows what the project can
 * reach, the organisation's and its parents' types (read-only, each with a
 * Hide/Show toggle), above the project's own types (editable, same row as the
 * organisation's). While the organisation has locked customisation the project
 * view is read-only. One component for both scopes, so there is no second copy.
 *
 * Owns its data and every mutation, each confirmed with a Toast. Deleting a type
 * that is in use opens `DeleteInUseDialog` with usage counts, replacements
 * assessed for fit, a Tier-2 delete-the-links option and, for a type other
 * projects use, the option to keep it for them.
 */
export function LinkTypesPanel({ scope }: { scope: LinkTypesScope }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [data, setData] = useState<PanelData | null>(null);
  const [tab, setTab] = useState<PanelTab>("types");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirmingLock, setConfirmingLock] = useState(false);
  const errorFallback = strings.common.error;

  // Bumped to refetch after any mutation.
  const [version, setVersion] = useState(0);
  const reload = useCallback(async () => setVersion((v) => v + 1), []);

  const isProject = scope.kind === "project";
  const base = isProject ? `/api/v1/projects/${scope.projectId}/link-types` : `/api/v1/orgs/${scope.orgId}/link-types`;
  const rulesBase = isProject
    ? `/api/v1/projects/${scope.projectId}/artefact-link-rules`
    : `/api/v1/orgs/${scope.orgId}/artefact-link-rules`;
  const orgId = scope.orgId;

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      isProject ? api.get<ProjectLinkTypes>(base) : api.get<LinkTypeDefinition[]>(base),
      api.get<ArtefactTypeOption[]>(`/api/v1/orgs/${orgId}/artefact-types`),
      api.get<Array<ArtefactLinkRule | ProjectArtefactLinkRule>>(rulesBase),
      isProject ? Promise.resolve(null) : api.get<ProjectCustomisation>(`/api/v1/orgs/${orgId}/project-customisation`),
    ])
      .then(([types, artefacts, ruleList, customisation]) => {
        if (cancelled) return;
        const projectTypes = isProject ? (types as ProjectLinkTypes) : null;
        setData({
          editable: projectTypes ? projectTypes.items.filter((i) => i.editable) : (types as LinkTypeDefinition[]),
          others: projectTypes ? projectTypes.items.filter((i) => !i.editable) : [],
          reachable: projectTypes ? projectTypes.items : [],
          locked: projectTypes ? projectTypes.locked : false,
          artefactTypes: artefacts,
          rules: ruleList,
          customisation,
        });
        setLoadError(null);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(toErrorMessage(err, errorFallback));
      });
    return () => {
      cancelled = true;
    };
  }, [base, rulesBase, orgId, isProject, version, errorFallback]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!data) return <Spinner />;

  const { editable, others, reachable, locked, artefactTypes, rules, customisation } = data;
  const readOnly = isProject && locked;

  async function addLinkType(forward: string, reverse: string) {
    await api.post(base, { forward_name: forward, reverse_name: reverse });
    showToast(strings.orgAdmin.linkTypeAdded);
    await reload();
  }

  async function moveLinkType(id: string, direction: "up" | "down") {
    await api.post(`${base}/${id}/move`, { direction });
    await reload();
  }

  async function renameLinkType(id: string, forward: string, reverse: string) {
    await api.patch(`${base}/${id}`, { forward_name: forward, reverse_name: reverse });
    showToast(strings.orgAdmin.linkTypeRenamed);
    await reload();
  }

  async function setFlow(item: LinkTypeDefinition, flow: LinkFlow) {
    try {
      await api.patch(`${base}/${item.id}`, { forward_name: item.forward_name, reverse_name: item.reverse_name, flow });
      showToast(strings.orgAdmin.linkTypeFlowUpdated);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.orgAdmin.linkTypeFlowFailed), "error");
    }
  }

  async function setRestriction(
    item: LinkTypeDefinition, field: "allowed_source_types" | "allowed_target_types", next: string[] | null
  ) {
    try {
      await api.patch(`${base}/${item.id}`, { forward_name: item.forward_name, reverse_name: item.reverse_name, [field]: next });
      showToast(strings.orgAdmin.linkTypeRestrictionUpdated);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.orgAdmin.linkTypeRestrictionFailed), "error");
    }
  }

  async function setVisibility(item: ProjectLinkType, hidden: boolean) {
    try {
      await api.put(`${base}/${item.id}/visibility`, { hidden });
      showToast(strings.orgAdmin.linkTypeVisibilityUpdated);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.orgAdmin.linkTypeVisibilityFailed), "error");
    }
  }

  async function deleteLinkType(id: string, reassignToId?: string, keep?: boolean) {
    const params: string[] = [];
    if (reassignToId) params.push("mode=reassign", `reassign_to_id=${reassignToId}`);
    if (keep) params.push("keep_in_projects=true");
    if (params.length === 0) {
      await api.delete(`${base}/${id}`);
      showToast(strings.orgAdmin.linkTypeDeleted);
    } else {
      const outcome = await api.delete<LinkTypeDeleteOutcome>(`${base}/${id}?${params.join("&")}`);
      showToast(strings.orgAdmin.linkTypeDeleteOutcome(outcome));
    }
    await reload();
  }

  async function loadInUse(item: LinkTypeDefinition, message: string, keep = true): Promise<DeleteInUseConfig> {
    const usage = await api.get<LinkTypeUsage>(`${base}/${item.id}/usage?keep_in_projects=${keep}`);
    const keepOption = usage.keep_available
      ? {
          label: strings.orgAdmin.linkTypeKeepLabel(usage.keep_project_count ?? 0),
          description: strings.orgAdmin.linkTypeKeepDescription,
          nothingElseToMove: usage.moved_link_count === 0,
        }
      : undefined;
    const keeping = keep && keepOption !== undefined;
    const details: string[] = [];
    if (usage.pending_change_requests > 0) details.push(strings.orgAdmin.linkTypeUsagePending(usage.pending_change_requests));
    if (usage.approved_requirement_links > 0) details.push(strings.orgAdmin.linkTypeUsageApproved(usage.approved_requirement_links));
    if (usage.rule_artefact_types.length > 0) {
      details.push(strings.orgAdmin.linkTypeUsageRules(usage.rule_artefact_types.map((a) => a.label).join(", ")));
    }
    const emptied = usage.emptied_rule_artefact_types.map((a) => a.label).join(", ");
    const unmanageable =
      !keeping && usage.unmanageable_project_count > 0
        ? strings.orgAdmin.linkTypeKeepUnmanageable(usage.unmanageable_project_count)
        : undefined;
    const blockedReason =
      unmanageable ??
      (usage.pending_change_requests > 0
        ? strings.orgAdmin.linkTypeUsagePending(usage.pending_change_requests)
        : usage.emptied_rule_artefact_types.length > 0
          ? strings.orgAdmin.linkTypeUsageEmptied(emptied)
          : undefined);
    return {
      summary: usage.link_count > 0 ? strings.orgAdmin.linkTypeUsageLinks(usage.link_count, usage.project_count) : message,
      details,
      candidates: usage.candidates.map((c) => ({
        id: c.id,
        label: c.forward_name,
        disabledReason: c.compatible ? undefined : (c.reason ?? undefined),
        warning: c.flow_differs ? strings.orgAdmin.linkTypeFlowDiffers : undefined,
      })),
      keep: keepOption,
      reload: (nextKeep) => loadInUse(item, message, nextKeep),
      moveBlockedReason: unmanageable,
      remove:
        usage.moved_link_count > 0
          ? {
              description: strings.orgAdmin.linkTypeRemoveDescription(usage.moved_link_count),
              blockedReason,
              confirmText: item.forward_name,
              confirmMessage: strings.orgAdmin.linkTypeRemoveConfirmMessage(item.forward_name, usage.moved_link_count),
              confirmLabel: strings.orgAdmin.linkTypeRemoveConfirmLabel,
              onRemove: async (keepForOthers) => {
                const outcome = await api.delete<LinkTypeDeleteOutcome>(
                  `${base}/${item.id}?mode=remove_links${keepForOthers ? "&keep_in_projects=true" : ""}`,
                );
                showToast(strings.orgAdmin.linkTypeDeleteOutcome(outcome));
                await reload();
              },
            }
          : undefined,
    };
  }

  /** Restriction options: every artefact type of the organisation, plus any type already stored on this link type that the registry no longer lists. */
  function restrictionOptions(item: LinkTypeDefinition, field: "allowed_source_types" | "allowed_target_types") {
    const current = item[field] ?? [];
    const known = new Set(artefactTypes.map((a) => a.type));
    const all = [...artefactTypes, ...current.filter((c) => !known.has(c)).map((c) => ({ type: c, label: humaniseArtefactType(c) }))];
    const ariaLabel = field === "allowed_source_types" ? strings.orgAdmin.linkTypeCanLinkFromLabel : strings.orgAdmin.linkTypeCanLinkToLabel;
    return all.map((a) => ({
      value: a.type,
      label: a.label,
      checked: current.includes(a.type),
      optionLabel: `${ariaLabel(item.forward_name)}: ${a.label}`,
      onToggle: () => {
        const next = current.includes(a.type) ? current.filter((x) => x !== a.type) : [...current, a.type];
        void setRestriction(item, field, next.length === 0 ? null : next);
      },
    }));
  }

  async function setLocked(nextLocked: boolean) {
    setConfirmingLock(false);
    try {
      await api.put(`/api/v1/orgs/${orgId}/project-customisation`, { locks: nextLocked ? ["link_types"] : [] });
      showToast(strings.orgAdmin.projectCustomisationUpdated);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.orgAdmin.projectCustomisationFailed), "error");
    }
  }

  const tabs: TabDef<PanelTab>[] = [
    { key: "types", label: strings.orgAdmin.linkTypesTab },
    { key: "rules", label: strings.orgAdmin.linkTypesByArtefactTab },
  ];

  const definitionList = (
    <DefinitionList
      items={editable}
      fields={[
        { key: "forward", getValue: (i) => i.forward_name, placeholder: strings.orgAdmin.forwardName, ariaLabel: strings.orgAdmin.forwardName, maxWidth: 200 },
        { key: "reverse", getValue: (i) => i.reverse_name, placeholder: strings.orgAdmin.reverseName, ariaLabel: strings.orgAdmin.reverseName, maxWidth: 200 },
      ]}
      getReassignLabel={(i) => i.forward_name}
      onMove={moveLinkType}
      onRename={(id, values) => renameLinkType(id, values.forward, values.reverse)}
      onAdd={(values) => addLinkType(values.forward, values.reverse)}
      onDelete={deleteLinkType}
      loadInUse={(item, message) => loadInUse(item, message)}
      deleteLabel={strings.orgAdmin.deleteLinkType}
      addLabel={strings.orgAdmin.newLinkType}
      minItems={isProject ? 0 : 1}
      renderExtra={(item) => (
        <select
          key="flow"
          className="input"
          style={{ maxWidth: 180 }}
          aria-label={strings.orgAdmin.linkTypeFlowLabel(item.forward_name)}
          value={item.flow}
          onChange={(e) => void setFlow(item, e.target.value as LinkFlow)}
        >
          {LINK_FLOW_VALUES.map((flow) => (
            <option key={flow} value={flow}>{LINK_FLOW_LABEL[flow]}</option>
          ))}
        </select>
      )}
      renderDetails={(item) =>
        item.dedicated_endpoint ? (
          <span className="text-muted">{strings.orgAdmin.linkTypeDedicatedNote}</span>
        ) : (
          <div className="row" style={{ gap: "0.5rem" }}>
            <span className="text-muted">{strings.orgAdmin.linkTypeCanLinkFrom}</span>
            <div style={{ minWidth: 200 }}>
              <MultiSelectDropdown
                triggerLabel={strings.orgAdmin.linkTypeCanLinkFromLabel(item.forward_name)}
                emptyLabel={strings.orgAdmin.anyArtefact}
                options={restrictionOptions(item, "allowed_source_types")}
              />
            </div>
            <span className="text-muted">{strings.orgAdmin.linkTypeCanLinkTo}</span>
            <div style={{ minWidth: 200 }}>
              <MultiSelectDropdown
                triggerLabel={strings.orgAdmin.linkTypeCanLinkToLabel(item.forward_name)}
                emptyLabel={strings.orgAdmin.anyArtefact}
                options={restrictionOptions(item, "allowed_target_types")}
              />
            </div>
          </div>
        )
      }
    />
  );

  return (
    <div className="stack">
      <Tabs idPrefix="link-types" tabs={tabs} active={tab} onChange={setTab} />
      {tab === "types" && (
        <div className="stack" {...tabPanelProps("link-types", "types")}>
          {isProject ? (
            <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.projectLinkTypesHint}</p>
          ) : (
            <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.linkTypesHint}</p>
          )}
          {readOnly && (
            <div role="status" className="badge" style={{ alignSelf: "flex-start" }}>
              {strings.orgAdmin.projectLinkTypesLocked}
            </div>
          )}
          {!isProject && customisation && (
            <div className="stack" style={{ gap: "0.25rem" }}>
              <div className="row" style={{ gap: "0.75rem" }}>
                <ToggleSwitch
                  checked={!customisation.locks.includes("link_types")}
                  label={strings.orgAdmin.projectCustomisationLinkTypes}
                  onChange={(allowed) => (allowed ? void setLocked(false) : setConfirmingLock(true))}
                />
                <strong>{strings.orgAdmin.projectCustomisationLinkTypes}</strong>
              </div>
              <span className="text-muted">{strings.orgAdmin.projectCustomisationHint}</span>
              <span className="text-muted">
                {strings.orgAdmin.projectCustomisationAffected(
                  customisation.local_link_type_count, customisation.local_link_type_project_count,
                )}
              </span>
            </div>
          )}
          <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.linkTypeFlowHint}</p>
          <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.linkTypeRestrictionHint}</p>
          {isProject ? (
            <>
              <section className="stack" aria-label={strings.orgAdmin.projectLinkTypesAvailableHeading}>
                <strong>{strings.orgAdmin.projectLinkTypesAvailableHeading}</strong>
                {others.map((item) => (
                  <ProjectLinkTypeRow key={item.id} item={item} canChange={!readOnly} onSetHidden={(hidden) => setVisibility(item, hidden)} />
                ))}
              </section>
              {!readOnly && (
                <section className="stack" aria-label={strings.orgAdmin.projectLinkTypesOwnHeading}>
                  <strong>{strings.orgAdmin.projectLinkTypesOwnHeading}</strong>
                  {definitionList}
                </section>
              )}
            </>
          ) : (
            definitionList
          )}
        </div>
      )}
      {tab === "rules" && (
        <div {...tabPanelProps("link-types", "rules")}>
          <ArtefactLinkRulesView
            scope={scope}
            linkTypes={isProject ? reachable.filter((i) => i.shadowed_by_scope === null) : editable}
            rules={rules}
            readOnly={readOnly}
            onChanged={reload}
          />
        </div>
      )}
      {confirmingLock && customisation && (
        <ConfirmDialog
          title={strings.orgAdmin.projectCustomisationLockTitle}
          message={strings.orgAdmin.projectCustomisationLockMessage(
            customisation.local_link_type_count, customisation.local_link_type_project_count,
          )}
          confirmLabel={strings.orgAdmin.projectCustomisationLockConfirm}
          onConfirm={() => void setLocked(true)}
          onCancel={() => setConfirmingLock(false)}
        />
      )}
    </div>
  );
}
