/**
 * Module: modules/traceability/ProjectBaselinePanel
 *
 * The "Baseline policy" section of Project Administration: what runs before this project's baselines and where each
 * check and required field comes from, the project's own policy, and a preview of what a baseline taken now would do.
 *
 * Responsibilities:
 * - Show the checks and required fields in force with their sources, each table sortable (the sort in the address, a
 *   distinct key per table so one table's sort never orders another).
 * - For a person who may manage the project's governance: edit the project's own policy as one settings group, return it
 *   to the nearest ancestor project's policy (`OverridePill`), and run the checks against a stage or manual baseline
 *   without writing anything.
 * - Read-only for everyone else, who see neither the editor nor the preview.
 *
 * Dependencies: `projectGovernanceApi`, `BaselineSettingsFields`, `DirectoryTable`, `OverridePill`.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ProjectStage } from "../../api/types";
import { Badge } from "../../components/Badge";
import { CellText } from "../../components/CellText";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { InlineMessage } from "../../components/InlineMessage";
import { LabeledSelect } from "../../components/LabeledSelect";
import { LoadFailed } from "../../components/LoadFailed";
import { OverridePill } from "../../components/OverridePill";
import { SettingsForm } from "../../components/SettingsForm";
import { Spinner } from "../../components/Spinner";
import { cycleSort } from "../../components/sortState";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlSort } from "../../hooks/useUrlFilter";
import { labelOptions } from "../../utils/labelOptions";
import { sortRows, type SortValue } from "../../utils/sortRows";
import { projectGovernanceApi } from "./api";
import { BaselineSettingsFields } from "./BaselineSettingsFields";
import { baselineProblem, DEFAULT_BASELINE_SETTINGS, sameBaseline, sourcesLabel } from "./policyText";
import { BASELINE_KIND_LABEL, type BaselineKind, type BaselinePreview, type BaselineType, type EffectiveBaselineCheck, type EffectiveBaselineField, type ProjectBaseline } from "./types";

/**
 * @param stage Whether a check or field runs before stage baselines.
 * @param manual Whether it runs before manual baselines.
 * @returns The baselines it runs before, in words.
 */
function runsBefore(stage: boolean, manual: boolean): string {
  if (stage && manual) return "Stage and manual baselines";
  if (stage) return "Stage baselines";
  return manual ? "Manual baselines" : "No baseline";
}

/**
 * @param projectId The project whose baseline policy is shown.
 */
export function ProjectBaselinePanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [data, setData] = useState<ProjectBaseline | null>(null);
  const [draft, setDraft] = useState(DEFAULT_BASELINE_SETTINGS);
  const [failure, setFailure] = useState<string | null>(null);

  const adopt = useCallback((loaded: ProjectBaseline) => {
    setData(loaded);
    setDraft(loaded.own ?? DEFAULT_BASELINE_SETTINGS);
  }, []);

  const load = useCallback(async () => {
    try {
      adopt(await projectGovernanceApi.baseline(projectId));
      setFailure(null);
    } catch (err) {
      setFailure(toErrorMessage(err, "The baseline policy could not be loaded."));
    }
  }, [projectId, adopt]);
  useLoadOnChange(load, [projectId]);

  async function save() {
    adopt(await projectGovernanceApi.setBaseline(projectId, draft));
  }

  async function followParent() {
    try {
      adopt(await projectGovernanceApi.setBaseline(projectId, null));
      showToast("The project now follows the baseline policy it inherits.");
    } catch (err) {
      showToast(toErrorMessage(err, "The baseline policy could not be changed."), "error");
    }
  }

  if (failure && !data) return <LoadFailed message={failure} onRetry={() => void load()} />;
  if (!data) return <Spinner />;
  const own = data.own ?? DEFAULT_BASELINE_SETTINGS;

  return (
    <div className="stack">
      <section className="stack" aria-label="Checks in force">
        <h3 style={{ margin: 0 }}>Checks in force</h3>
        <ChecksInForce checks={data.checks} />
      </section>
      <section className="stack" aria-label="Required fields in force">
        <h3 style={{ margin: 0 }}>Required fields in force</h3>
        <FieldsInForce fields={data.required_fields} types={data.types} />
      </section>
      {data.can_manage && (
        <section className="stack" aria-label="Project policy">
          <div className="row" style={{ alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>Project policy</h3>
            <OverridePill
              custom={data.own !== null} onReset={() => void followParent()} resetLabel="Use inherited value"
              defaultLabel={data.inherited_from ? `Inherited from ${data.inherited_from}` : "No policy set by this project"}
            />
          </div>
          <SettingsForm
            dirty={!sameBaseline(draft, own) && baselineProblem(draft) === null} onSave={save} successMessage="Baseline policy saved."
          >
            <BaselineSettingsFields
              settings={draft} onChange={setDraft} checkOptions={data.check_options} types={data.types} fieldOptions={data.field_options}
            />
          </SettingsForm>
        </section>
      )}
      {data.can_manage && <BaselinePreviewSection projectId={projectId} />}
    </div>
  );
}

/**
 * The checks that run before this project's baselines, each with the baselines it runs before and where it comes from.
 *
 * @param checks The effective checks.
 */
function ChecksInForce({ checks }: { checks: EffectiveBaselineCheck[] }) {
  const keys = ["check", "check_runs", "check_source"] as const;
  const [sort, setSort] = useUrlSort(keys);
  const values: Record<string, (row: EffectiveBaselineCheck) => SortValue> = {
    check: (row) => row.name ?? row.key,
    check_runs: (row) => runsBefore(row.stage, row.manual),
    check_source: (row) => sourcesLabel(row.sources),
  };
  const columns: DirectoryColumn<EffectiveBaselineCheck>[] = [
    {
      key: "check", label: "Check", sortable: true, minWidth: "10rem",
      render: (row) => (
        <span className="row" style={{ flexWrap: "nowrap", gap: "var(--space-2)" }}>
          <CellText lines={2}>{row.name ?? row.key}</CellText>
          {!row.available && <Badge tone="warning">Unavailable</Badge>}
        </span>
      ),
    },
    { key: "check_runs", label: "Runs before", sortable: true, render: (row) => runsBefore(row.stage, row.manual) },
    { key: "check_source", label: "Source", sortable: true, render: (row) => <CellText lines={2}>{sourcesLabel(row.sources)}</CellText> },
  ];
  return (
    <DirectoryTable
      ariaLabel="Baseline checks in force" columns={columns} rows={sortRows(checks, sort, values)} rowKey={(row) => row.key}
      sort={sort} onSort={(key) => setSort((current) => cycleSort(current, key as (typeof keys)[number]))}
      emptyState={<p className="text-muted">No baseline check is enabled for this project.</p>}
    />
  );
}

/**
 * The fields a record must have filled before this project's baselines, with where each comes from.
 *
 * @param fields The effective required fields.
 * @param types The record types a baseline can hold, for their names.
 */
function FieldsInForce({ fields, types }: { fields: EffectiveBaselineField[]; types: BaselineType[] }) {
  const typeName = (type: string) => types.find((t) => t.artefact_type === type)?.label ?? type;
  const keys = ["field_type", "field", "field_runs", "field_source"] as const;
  const [sort, setSort] = useUrlSort(keys);
  const values: Record<string, (row: EffectiveBaselineField) => SortValue> = {
    field_type: (row) => typeName(row.artefact_type),
    field: (row) => row.field_label ?? row.field_key,
    field_runs: (row) => runsBefore(row.stage, row.manual),
    field_source: (row) => sourcesLabel(row.sources),
  };
  const columns: DirectoryColumn<EffectiveBaselineField>[] = [
    { key: "field_type", label: "Record type", sortable: true, minWidth: "8rem", render: (row) => <CellText lines={2}>{typeName(row.artefact_type)}</CellText> },
    {
      key: "field", label: "Field", sortable: true,
      render: (row) => row.field_label !== null
        ? <CellText lines={2}>{row.field_label}</CellText>
        : <CellText lines={2}>{`${row.field_key} (not offered in this project)`}</CellText>,
    },
    { key: "field_runs", label: "Runs before", sortable: true, render: (row) => runsBefore(row.stage, row.manual) },
    { key: "field_source", label: "Source", sortable: true, render: (row) => <CellText lines={2}>{sourcesLabel(row.sources)}</CellText> },
  ];
  return (
    <DirectoryTable
      ariaLabel="Required fields in force" columns={columns} rows={sortRows(fields, sort, values)}
      rowKey={(row) => `${row.artefact_type}/${row.field_key}`}
      sort={sort} onSort={(key) => setSort((current) => cycleSort(current, key as (typeof keys)[number]))}
      emptyState={<p className="text-muted">No field is required for this project.</p>}
    />
  );
}

/**
 * Runs the enabled checks against a baseline taken now and lists every failure, writing nothing.
 *
 * @param projectId The project whose checks run.
 */
function BaselinePreviewSection({ projectId }: { projectId: string }) {
  const [kind, setKind] = useState<BaselineKind>("stage");
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [stageId, setStageId] = useState("");
  const [result, setResult] = useState<BaselinePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let live = true;
    api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`).then(
      (loaded) => { if (live) setStages(loaded); },
      () => { if (live) setStages([]); },
    );
    return () => { live = false; };
  }, [projectId]);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setResult(await projectGovernanceApi.previewBaseline(projectId, kind, kind === "stage" ? stageId : undefined));
    } catch (err) {
      setResult(null);
      setError(toErrorMessage(err, "The preview could not be run."));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="stack" aria-label="Preview a baseline">
      <h3 style={{ margin: 0 }}>Preview a baseline</h3>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <LabeledSelect
          helpNotNeeded label="Kind of baseline" value={kind} placeholder={null} autoWidth
          onChange={(next) => { setKind(next as BaselineKind); setResult(null); }} options={labelOptions(BASELINE_KIND_LABEL)}
        />
        {kind === "stage" && (
          <LabeledSelect
            helpNotNeeded label="Stage" value={stageId} autoWidth onChange={(next) => { setStageId(next); setResult(null); }}
            options={stages.map((s) => ({ value: s.id, label: s.name }))}
          />
        )}
        <button type="button" className="btn" disabled={running || (kind === "stage" && !stageId)} onClick={() => void run()}>
          Run preview
        </button>
      </div>
      <InlineMessage>{error}</InlineMessage>
      {result && <PreviewResult result={result} />}
    </section>
  );
}

/**
 * The outcome of a preview: the checks that would run and every failure, or an all-clear message.
 *
 * @param result The preview the server returned.
 */
function PreviewResult({ result }: { result: BaselinePreview }) {
  const keys = ["failure_record", "failure_check", "failure_message"] as const;
  const [sort, setSort] = useUrlSort(keys);
  const values: Record<string, (row: BaselinePreview["failures"][number]) => SortValue> = {
    failure_record: (row) => row.code,
    failure_check: (row) => row.check_name,
    failure_message: (row) => row.message,
  };
  const columns: DirectoryColumn<BaselinePreview["failures"][number]>[] = [
    {
      key: "failure_record", label: "Record", sortable: true, minWidth: "8rem",
      render: (row) => (row.code ? <span className="text-muted">{row.code}</span> : <span className="text-muted">No code</span>),
    },
    { key: "failure_check", label: "Check", sortable: true, render: (row) => <CellText lines={2}>{row.check_name}</CellText> },
    { key: "failure_message", label: "Message", sortable: true, width: "50%", render: (row) => <CellText lines={3}>{row.message}</CellText> },
  ];
  const checks = result.checks.map((c) => c.name).join(", ");
  return (
    <div className="stack" role="region" aria-label="Preview result">
      <p className="text-muted">{checks ? `Checks that would run: ${checks}.` : "No check would run."}</p>
      {result.failures.length === 0 ? (
        <InlineMessage tone="success">The baseline would be written: no check fails.</InlineMessage>
      ) : (
        <DirectoryTable
          ariaLabel="Baseline check failures" columns={columns} rows={sortRows(result.failures, sort, values)}
          rowKey={(row) => `${row.check_key}/${row.artefact_id}/${row.message}`}
          sort={sort} onSort={(key) => setSort((current) => cycleSort(current, key as (typeof keys)[number]))}
          emptyState={null}
        />
      )}
    </div>
  );
}
