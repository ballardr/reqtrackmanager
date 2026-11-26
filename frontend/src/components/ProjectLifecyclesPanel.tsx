/**
 * Module: components/ProjectLifecyclesPanel
 *
 * The Lifecycles group of Project Administration: for each record type of an enabled module that has optional states, a
 * checkbox per state (turn a state off and a record moves past it), the state the organisation requires shown locked, a
 * read-only track of the resulting path and, in a nested project, whether the choice is its own or inherited.
 *
 * Responsibilities:
 * - Read the project's lifecycles and save one type's choice at a time (`LifecyclesApi`); `api` is injectable for stories.
 * - Show a state the organisation requires as locked with its reason (never an editable box that fails on save), and a
 *   project the organisation exempts as free to turn it off.
 * - Offer the project's one switch for skipping steps on a record, locked when the organisation or a governance profile forbids it.
 * - Name the governance profiles that require a state or forbid skipping, and keep such a state locked for a project the organisation exempts (an exemption lifts only the organisation's own requirement).
 * - Show the Approval section (`ApprovalSeparationSection`) after the types.
 *
 * Design decisions: there is no Custom or reset control; a nested project that has made no choice shows a read-only note that it follows its parent, and its first change becomes its own choice. Only a type with at least one optional state is listed; an approval state is never offered. The
 * preview draws the steps that are on, so the person sees the path Promote will follow. The skipping switch is one
 * setting for the whole project, not one per type, and shows before the types.
 */
import { useCallback, useState } from "react";

import { approvalSeparationApi, type ApprovalSeparationApi } from "../api/approvalSeparation";
import { lifecyclesApi, type LifecyclesApi, type ProjectLifecycle, type ProjectLifecycles, type ProjectSkip } from "../api/lifecycles";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { ApprovalSeparationSection } from "./ApprovalSeparationSection";
import { Badge } from "./Badge";
import { CheckboxField } from "./FormFields";
import { LifecycleTrack } from "./LifecycleTrack";
import { Spinner } from "./Spinner";

/**
 * @param projectId The project whose lifecycles are configured.
 * @param api The calls (the live ones by default).
 * @param separationApi The approval separation calls (the live ones by default).
 */
export function ProjectLifecyclesPanel({
  projectId, api = lifecyclesApi, separationApi = approvalSeparationApi,
}: { projectId: string; api?: LifecyclesApi; separationApi?: ApprovalSeparationApi }) {
  const strings = useStrings();
  const text = strings.lifecycleSettings;
  const { showToast } = useToast();
  const [data, setData] = useState<ProjectLifecycles | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.project(projectId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, projectId]);
  useLoadOnChange(load, [api, projectId]);

  async function save(artefactType: string, disabled: string[] | null) {
    try {
      setData(await api.setProject(projectId, artefactType, disabled));
      showToast(text.saved);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function saveSkip(allowed: boolean) {
    try {
      setData(await api.setProjectSkip(projectId, allowed));
      showToast(text.saved);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (failed && !data) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!data) return <Spinner />;
  const configurable = data.lifecycles.filter((l) => l.path.some((s) => s.optional));

  return (
    <div className="stack">
      <SkipStepsRow skip={data.skip} canManage={data.can_manage} onSave={saveSkip} />
      {configurable.length === 0 && <p className="text-muted">{text.noTypes}</p>}
      {configurable.map((lifecycle) => (
        <LifecycleTypeRow key={lifecycle.artefact_type} lifecycle={lifecycle} canManage={data.can_manage} onSave={save} />
      ))}
      <ApprovalSeparationSection projectId={projectId} api={separationApi} />
    </div>
  );
}

/** The project's switch for skipping steps on a record: locked when the organisation forbids it, with the source named when nested. */
function SkipStepsRow({
  skip, canManage, onSave,
}: { skip: ProjectSkip; canManage: boolean; onSave: (allowed: boolean) => Promise<void> }) {
  const strings = useStrings();
  const text = strings.lifecycleSettings;
  return (
    <section className="stack" aria-label={text.skipHeading}>
      <h3 style={{ margin: 0 }}>{text.skipHeading}</h3>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <CheckboxField
          label={text.allowSkip} checked={skip.chosen} help={strings.help.lifecycleSkip}
          disabled={!canManage || skip.forbidden} onChange={(on) => void onSave(on)}
        />
        {skip.forbidden && skip.forbidden_by_profiles.length === 0 && <Badge>{text.skipBannedByOrganisation}</Badge>}
        {skip.forbidden_by_profiles.length > 0 && <Badge>{text.skipBannedByProfiles(skip.forbidden_by_profiles)}</Badge>}
        {skip.exempt && <Badge tone="info">{text.skipExempt}</Badge>}
        {skip.source === "parent_project" && <Badge>{text.skipInherited}</Badge>}
      </div>
    </section>
  );
}

/** One record type: its states with a checkbox each for the optional ones, the source of the choice and the path preview. */
function LifecycleTypeRow({
  lifecycle, canManage, onSave,
}: { lifecycle: ProjectLifecycle; canManage: boolean; onSave: (artefactType: string, disabled: string[] | null) => Promise<void> }) {
  const strings = useStrings();
  const text = strings.lifecycleSettings;
  const optional = lifecycle.path.filter((s) => s.optional);
  const disabled = new Set(lifecycle.disabled);
  const required = new Set(lifecycle.required);
  const requiredBy = (key: string): string[] => lifecycle.required_by_profiles[key] ?? [];
  const steps = lifecycle.path.filter((s) => !disabled.has(s.key)).map((s) => ({ key: s.key, label: s.label }));

  function toggle(key: string, use: boolean) {
    const off = new Set(lifecycle.own_disabled ?? lifecycle.disabled);
    if (use) off.delete(key);
    else off.add(key);
    void onSave(lifecycle.artefact_type, optional.map((s) => s.key).filter((k) => off.has(k)));
  }

  return (
    <section className="stack" aria-label={lifecycle.label}>
      <div className="row" style={{ alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>{text.typeOf(lifecycle.label, lifecycle.module_name)}</h3>
        {lifecycle.source === "parent_project" && <Badge>{text.inheritedParent}</Badge>}
      </div>
      <div className="row" style={{ alignItems: "flex-start" }}>
        {optional.map((state) => (
          <div key={state.key} className="stack" style={{ gap: "var(--space-1)" }}>
            <CheckboxField
              label={text.useState(state.label)} checked={!disabled.has(state.key)} help={strings.help.lifecycleStates}
              disabled={!canManage || (required.has(state.key) && (requiredBy(state.key).length > 0 || !lifecycle.exempt))}
              onChange={(use) => toggle(state.key, use)}
            />
            {requiredBy(state.key).length > 0
              ? <Badge>{text.requiredByProfiles(requiredBy(state.key))}</Badge>
              : required.has(state.key) && <Badge>{text.requiredByOrganisation}</Badge>}
          </div>
        ))}
        {lifecycle.exempt && <Badge tone="info">{text.exempt}</Badge>}
      </div>
      <LifecycleTrack steps={steps} current="" />
    </section>
  );
}
