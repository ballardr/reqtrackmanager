/**
 * Module: components/RequirementAliasSettingsPanel
 *
 * The "Requirement aliases" setting for one tier: Organisation Administration (the default every project starts from)
 * and Project Administration (the project's own value, with the source of an inherited value and a way back to it).
 * Allowed lets a requirement sit in further components and categories, each with its own code; Disabled stops new ones.
 * Existing aliases keep working either way.
 *
 * Responsibilities:
 * - Read and write the setting (`RequirementAliasesApi`), naming the tier an inherited value came from (`OverridePill`).
 * - For a project, count its aliases and offer to make them all independent (confirmed first; irreversible) and report
 *   how many were made and refused. `api` is injectable for stories.
 */
import { useCallback, useState } from "react";

import {
  requirementAliasesApi, type AliasMode, type AliasSettings, type AliasModeSource, type RequirementAliasesApi,
} from "../api/requirementAliases";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { ConfirmDialog } from "./ConfirmDialog";
import { LabeledSelect } from "./LabeledSelect";
import { OverridePill } from "./OverridePill";
import { Spinner } from "./Spinner";

/** Where the panel reads and writes: an organisation's default, or one project's own value. */
export type AliasSettingsScope = { kind: "organization"; organizationId: string } | { kind: "project"; projectId: string };

/**
 * @param scope The tier to administer.
 * @param canEdit Whether the person may change the setting (an organisation administrator or a project manager).
 * @param api The calls (the live ones by default).
 */
export function RequirementAliasSettingsPanel({
  scope, canEdit = true, api = requirementAliasesApi,
}: { scope: AliasSettingsScope; canEdit?: boolean; api?: RequirementAliasesApi }) {
  const strings = useStrings();
  const text = strings.requirementAliases.settings;
  const { showToast } = useToast();
  const [organizationMode, setOrganizationMode] = useState<AliasMode | null>(null);
  const [project, setProject] = useState<AliasSettings | null>(null);
  const [failed, setFailed] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);

  const reload = useCallback(async () => {
    try {
      if (scope.kind === "organization") setOrganizationMode(await api.organizationMode(scope.organizationId));
      else setProject(await api.settings(scope.projectId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, scope]);
  useLoadOnChange(reload, [api, scope.kind, scope.kind === "organization" ? scope.organizationId : scope.projectId]);

  async function save(next: AliasMode | null) {
    try {
      if (scope.kind === "organization") setOrganizationMode(await api.setOrganizationMode(scope.organizationId, next ?? "allowed"));
      else setProject(await api.setProjectMode(scope.projectId, next));
      showToast(text.saved);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function makeAllIndependent(projectId: string) {
    setConfirmAll(false);
    let made = 0;
    let refused = 0;
    try {
      // Each request takes a batch; stop when none remain or a round makes no progress (every refusal repeats).
      for (;;) {
        const round = await api.makeAllIndependent(projectId);
        made += round.made.length;
        refused += round.failed.length;
        if (round.made.length === 0 || round.made.length + round.failed.length < 100) break;
      }
      showToast(text.makeAllDone(made, refused), refused > 0 ? "error" : undefined);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
    await reload();
  }

  const loaded = scope.kind === "organization" ? organizationMode : project;
  if (failed && !loaded) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!loaded) return <Spinner />;

  const modeOptions: Array<{ value: string; label: string }> = [
    ...(scope.kind === "project" ? [{ value: "inherit", label: text.inherit }] : []),
    { value: "allowed", label: text.allowed },
    { value: "disabled", label: text.disabled },
  ];
  const value = scope.kind === "organization" ? (organizationMode ?? "allowed") : (project?.own_mode ?? "inherit");
  const sourceLabel = (source: AliasModeSource) =>
    source === "project" ? text.sourceProject : source === "parent_project" ? text.sourceParent : text.sourceOrganization;

  return (
    <div className="stack">
      <div className="row" style={{ alignItems: "flex-end" }}>
        <LabeledSelect
          help={strings.help.requirementAliasMode} label={text.modeLabel} value={value} placeholder={null}
          options={modeOptions} disabled={!canEdit}
          onChange={(next) => void save(next === "inherit" ? null : (next as AliasMode))}
        />
        {scope.kind === "project" && project && (
          <OverridePill
            custom={project.own_mode !== null} defaultLabel={sourceLabel(project.source)}
            resetLabel={strings.codePrefixes.restoreLabel} disabled={!canEdit} onReset={() => void save(null)}
          />
        )}
      </div>
      {scope.kind === "project" && project && (
        <>
          <div className="row">
            <span>{project.alias_count > 0 ? text.count(project.alias_count) : text.noAliases}</span>
            {project.alias_count > 0 && canEdit && (
              <button type="button" className="btn" onClick={() => setConfirmAll(true)}>{text.makeAll}</button>
            )}
          </div>
          {confirmAll && (
            <ConfirmDialog
              title={text.makeAllTitle} message={text.makeAllMessage(project.alias_count)} confirmLabel={text.makeAllConfirm}
              requireTypedText={String(project.alias_count)}
              onConfirm={() => void makeAllIndependent(scope.projectId)} onCancel={() => setConfirmAll(false)}
            />
          )}
        </>
      )}
    </div>
  );
}
