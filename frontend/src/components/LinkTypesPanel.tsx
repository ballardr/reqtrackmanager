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
} from "../api/types";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { ArtefactLinkRulesView } from "./ArtefactLinkRulesView";
import { DefinitionList, type DeleteInUseConfig } from "./DefinitionList";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { Spinner } from "./Spinner";
import { Tabs, tabPanelProps, type TabDef } from "./Tabs";

const strings = t();

type PanelTab = "types" | "rules";

/** The label for an artefact type the registry no longer lists (a restriction
 * saved before its module was uninstalled), so a stored value never shows raw. */
function humaniseArtefactType(type: string): string {
  const text = type.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The organisation's link types: the vocabulary (names for both directions,
 * direction of flow, and which kinds of record each may join) and, on a second
 * tab, which link types each artefact type may use. Owns its own data and every
 * mutation, each confirmed with a Toast. Deleting a type that is in use opens
 * `DeleteInUseDialog` with usage counts, replacements assessed for fit, and a
 * Tier-2 delete-the-links option.
 */
export function LinkTypesPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [linkTypes, setLinkTypes] = useState<LinkTypeDefinition[] | null>(null);
  const [artefactTypes, setArtefactTypes] = useState<ArtefactTypeOption[]>([]);
  const [rules, setRules] = useState<ArtefactLinkRule[]>([]);
  const [tab, setTab] = useState<PanelTab>("types");
  const [loadError, setLoadError] = useState<string | null>(null);

  // Bumped to refetch after any mutation.
  const [version, setVersion] = useState(0);
  const reload = useCallback(async () => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get<LinkTypeDefinition[]>(`/api/v1/orgs/${orgId}/link-types`),
      api.get<ArtefactTypeOption[]>(`/api/v1/orgs/${orgId}/artefact-types`),
      api.get<ArtefactLinkRule[]>(`/api/v1/orgs/${orgId}/artefact-link-rules`),
    ])
      .then(([types, artefacts, ruleList]) => {
        if (cancelled) return;
        setLinkTypes(types);
        setArtefactTypes(artefacts);
        setRules(ruleList);
        setLoadError(null);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(toErrorMessage(err, strings.common.error));
      });
    return () => {
      cancelled = true;
    };
  }, [orgId, version]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!linkTypes) return <Spinner />;

  const base = `/api/v1/orgs/${orgId}/link-types`;

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

  async function deleteLinkType(id: string, reassignToId?: string) {
    if (reassignToId) {
      const outcome = await api.delete<LinkTypeDeleteOutcome>(`${base}/${id}?mode=reassign&reassign_to_id=${reassignToId}`);
      showToast(strings.orgAdmin.linkTypeMoved(outcome.moved, outcome.merged));
    } else {
      await api.delete(`${base}/${id}`);
      showToast(strings.orgAdmin.linkTypeDeleted);
    }
    await reload();
  }

  async function loadInUse(item: LinkTypeDefinition, message: string): Promise<DeleteInUseConfig> {
    const usage = await api.get<LinkTypeUsage>(`${base}/${item.id}/usage`);
    const details: string[] = [];
    if (usage.pending_change_requests > 0) details.push(strings.orgAdmin.linkTypeUsagePending(usage.pending_change_requests));
    if (usage.approved_requirement_links > 0) details.push(strings.orgAdmin.linkTypeUsageApproved(usage.approved_requirement_links));
    if (usage.rule_artefact_types.length > 0) {
      details.push(strings.orgAdmin.linkTypeUsageRules(usage.rule_artefact_types.map((a) => a.label).join(", ")));
    }
    const emptied = usage.emptied_rule_artefact_types.map((a) => a.label).join(", ");
    const blockedReason =
      usage.pending_change_requests > 0
        ? strings.orgAdmin.linkTypeUsagePending(usage.pending_change_requests)
        : usage.emptied_rule_artefact_types.length > 0
          ? strings.orgAdmin.linkTypeUsageEmptied(emptied)
          : undefined;
    return {
      summary: usage.link_count > 0 ? strings.orgAdmin.linkTypeUsageLinks(usage.link_count, usage.project_count) : message,
      details,
      candidates: usage.candidates.map((c) => ({
        id: c.id,
        label: c.forward_name,
        disabledReason: c.compatible ? undefined : (c.reason ?? undefined),
        warning: c.flow_differs ? strings.orgAdmin.linkTypeFlowDiffers : undefined,
      })),
      remove:
        usage.link_count > 0
          ? {
              description: strings.orgAdmin.linkTypeRemoveDescription(usage.link_count),
              blockedReason,
              confirmText: item.forward_name,
              confirmMessage: strings.orgAdmin.linkTypeRemoveConfirmMessage(item.forward_name, usage.link_count),
              confirmLabel: strings.orgAdmin.linkTypeRemoveConfirmLabel,
              onRemove: async () => {
                const outcome = await api.delete<LinkTypeDeleteOutcome>(`${base}/${item.id}?mode=remove_links`);
                showToast(strings.orgAdmin.linkTypeLinksRemoved(outcome.removed));
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

  const tabs: TabDef<PanelTab>[] = [
    { key: "types", label: strings.orgAdmin.linkTypesTab },
    { key: "rules", label: strings.orgAdmin.linkTypesByArtefactTab },
  ];

  return (
    <div className="stack">
      <Tabs idPrefix="link-types" tabs={tabs} active={tab} onChange={setTab} />
      {tab === "types" && (
        <div className="stack" {...tabPanelProps("link-types", "types")}>
          <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.linkTypesHint}</p>
          <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.linkTypeFlowHint}</p>
          <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.linkTypeRestrictionHint}</p>
          <DefinitionList
            items={linkTypes}
            fields={[
              { key: "forward", getValue: (i) => i.forward_name, placeholder: strings.orgAdmin.forwardName, ariaLabel: strings.orgAdmin.forwardName, maxWidth: 200 },
              { key: "reverse", getValue: (i) => i.reverse_name, placeholder: strings.orgAdmin.reverseName, ariaLabel: strings.orgAdmin.reverseName, maxWidth: 200 },
            ]}
            getReassignLabel={(i) => i.forward_name}
            onMove={moveLinkType}
            onRename={(id, values) => renameLinkType(id, values.forward, values.reverse)}
            onAdd={(values) => addLinkType(values.forward, values.reverse)}
            onDelete={deleteLinkType}
            loadInUse={loadInUse}
            deleteLabel={strings.orgAdmin.deleteLinkType}
            addLabel={strings.orgAdmin.newLinkType}
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
        </div>
      )}
      {tab === "rules" && (
        <div {...tabPanelProps("link-types", "rules")}>
          <ArtefactLinkRulesView orgId={orgId} linkTypes={linkTypes} rules={rules} onChanged={reload} />
        </div>
      )}
    </div>
  );
}
