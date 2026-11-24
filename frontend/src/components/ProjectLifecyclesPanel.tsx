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
 *
 * Design decisions: only a type with at least one optional state is listed; an approval state is never offered. The
 * preview draws the steps that are on, so the person sees the path Promote will follow.
 */
import { useCallback, useState } from "react";

import { lifecyclesApi, type LifecyclesApi, type ProjectLifecycle } from "../api/lifecycles";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { Badge } from "./Badge";
import { CheckboxField } from "./FormFields";
import { LifecycleTrack } from "./LifecycleTrack";
import { OverridePill } from "./OverridePill";
import { Spinner } from "./Spinner";

/**
 * @param projectId The project whose lifecycles are configured.
 * @param api The calls (the live ones by default).
 */
export function ProjectLifecyclesPanel({ projectId, api = lifecyclesApi }: { projectId: string; api?: LifecyclesApi }) {
  const strings = useStrings();
  const text = strings.lifecycleSettings;
  const { showToast } = useToast();
  const [data, setData] = useState<{ canManage: boolean; hasParent: boolean; lifecycles: ProjectLifecycle[] } | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await api.project(projectId);
      setData({ canManage: result.can_manage, hasParent: result.has_parent, lifecycles: result.lifecycles });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, projectId]);
  useLoadOnChange(load, [api, projectId]);

  async function save(artefactType: string, disabled: string[] | null) {
    try {
      const result = await api.setProject(projectId, artefactType, disabled);
      setData({ canManage: result.can_manage, hasParent: result.has_parent, lifecycles: result.lifecycles });
      showToast(text.saved);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (failed && !data) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!data) return <Spinner />;
  const configurable = data.lifecycles.filter((l) => l.path.some((s) => s.optional));
  if (configurable.length === 0) return <p className="text-muted">{text.noTypes}</p>;

  return (
    <div className="stack">
      {configurable.map((lifecycle) => (
        <LifecycleTypeRow key={lifecycle.artefact_type} lifecycle={lifecycle} canManage={data.canManage} onSave={save} />
      ))}
    </div>
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
  const steps = lifecycle.path.filter((s) => !disabled.has(s.key)).map((s) => ({ key: s.key, label: s.label }));
  const inherited = lifecycle.own_disabled === null;
  const sourceLabel = lifecycle.source === "parent_project" ? text.inheritedParent : text.allStates;

  function toggle(key: string, use: boolean) {
    const off = new Set(lifecycle.own_disabled ?? lifecycle.disabled);
    if (use) off.delete(key);
    else off.add(key);
    void onSave(lifecycle.artefact_type, optional.map((s) => s.key).filter((k) => off.has(k)));
  }

  return (
    <section className="stack" aria-label={lifecycle.label}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>{text.typeOf(lifecycle.label, lifecycle.module_name)}</h3>
        <OverridePill
          custom={!inherited} defaultLabel={sourceLabel} disabled={!canManage}
          resetLabel={lifecycle.source === "parent_project" || lifecycle.own_disabled !== null ? text.resetToInherited : text.resetToDefault}
          onReset={() => void onSave(lifecycle.artefact_type, null)}
        />
      </div>
      <div className="row" style={{ alignItems: "flex-start" }}>
        {optional.map((state) => (
          <div key={state.key} className="stack" style={{ gap: "var(--space-1)" }}>
            <CheckboxField
              label={text.useState(state.label)} checked={!disabled.has(state.key)} help={strings.help.lifecycleStates}
              disabled={!canManage || (required.has(state.key) && !lifecycle.exempt)}
              onChange={(use) => toggle(state.key, use)}
            />
            {required.has(state.key) && <Badge>{text.requiredByOrganisation}</Badge>}
          </div>
        ))}
        {lifecycle.exempt && <Badge tone="info">{text.exempt}</Badge>}
      </div>
      <LifecycleTrack steps={steps} current="" />
    </section>
  );
}
