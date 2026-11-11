/**
 * Module: components/ReportParamsForm
 *
 * The parameter form of the core report framework's Reports UI: one labelled control per parameter a report declares (a select
 * for `choices`, a bounded number, a switch, a date, or text for string/uuid),
 * plus the framework-level options: the "include child projects" switch for
 * project reports and, for organisation-wide reports, a "Project" picker that
 * narrows the run to one project (`project_id`, "All projects" when blank), or, for an organisation-wide
 * custom report that runs once per project, a "Projects" selector choosing which are included
 * (`project_ids`, comma-separated; none chosen means all) or, when the report runs for one project (and optionally its
 * child projects), a single-choice "Project" that must be answered (`project_ids` holds the one id). Generated entirely from the catalogue entry, so a new module report
 * needs no UI code for its parameters.
 *
 * Controlled and stateless: values live in the caller (`ReportRunner`); an
 * empty value means "use the server default". Parameters a custom report view
 * draws its own control for are passed in `hidden` so none has two controls.
 * Control and choice labels use the report's declared `label`/`choice_labels`
 * and otherwise fall back to humanising the identifier ("weighted_average" ->
 * "Weighted average"), because core has no label map for a module's own
 * vocabulary; a module that needs exact wording either declares the labels or
 * owns the parameter in its view.
 */
import { useId } from "react";

import type { ReportParam, ReportRunValues } from "../api/reports";
import { humanise } from "../utils/humanise";
import { FieldCaption } from "./FieldHelp";
import { LabeledSelect } from "./LabeledSelect";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { ToggleSwitch } from "./ToggleSwitch";
import { useStrings } from "../context/TerminologyContext";

/**
 * @param params The report's declared parameters.
 * @param values Current values by parameter name (and `include_children`).
 * @param onChange Called with a parameter name and its new value.
 * @param hidden Parameter names to leave out (owned by a custom view).
 * @param supportsIncludeChildren Whether to offer the framework `include_children` switch.
 * @param projectOptions Projects to offer in the `project_id` picker; omitted hides it.
 * @param projectMultiOptions Projects to offer in the `project_ids` selector; omitted hides it.
 * @param projectSingleOptions Projects to offer in the single-choice `project_ids` picker of a report that runs for one
 *   project (no "all projects" choice); omitted hides it.
 */
export function ReportParamsForm({
  params, values, onChange, hidden = [], supportsIncludeChildren = false, projectOptions, projectMultiOptions,
  projectSingleOptions,
}: {
  params: ReportParam[];
  values: ReportRunValues;
  onChange: (name: string, value: string | number | boolean | null) => void;
  hidden?: string[];
  supportsIncludeChildren?: boolean;
  projectOptions?: { value: string; label: string }[];
  projectMultiOptions?: { value: string; label: string }[];
  projectSingleOptions?: { value: string; label: string }[];
}) {
  const strings = useStrings();
  const shown = params.filter((p) => !hidden.includes(p.name));
  if (shown.length === 0 && !supportsIncludeChildren && !projectOptions && !projectMultiOptions && !projectSingleOptions) return null;
  const chosenProjects = new Set(typeof values.project_ids === "string" ? values.project_ids.split(",").filter(Boolean) : []);
  return (
    <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-end" }} role="group" aria-label="Report options">
      {projectOptions && (
        <LabeledSelect helpNotNeeded
          label={strings.filters.project}
          value={typeof values.project_id === "string" ? values.project_id : ""}
          onChange={(next) => onChange("project_id", next === "" ? null : next)}
          options={projectOptions}
          placeholder={strings.filters.allProjects}
        />
      )}
      {projectSingleOptions && (
        <LabeledSelect helpNotNeeded
          label={strings.filters.project}
          required
          value={typeof values.project_ids === "string" ? values.project_ids : ""}
          onChange={(next) => onChange("project_ids", next === "" ? null : next)}
          options={projectSingleOptions}
          placeholder="Choose a project"
        />
      )}
      {projectMultiOptions && (
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span>{strings.filters.projects}</span>
          <MultiSelectDropdown
            triggerLabel={strings.filters.projects}
            emptyLabel={strings.filters.allProjects}
            filterable={projectMultiOptions.length > 8}
            summaryLimit={2}
            options={projectMultiOptions.map((project) => {
              const checked = chosenProjects.has(project.value);
              return {
                value: project.value,
                label: project.label,
                checked,
                optionLabel: project.label,
                onToggle: () => {
                  const next = new Set(chosenProjects);
                  if (checked) next.delete(project.value);
                  else next.add(project.value);
                  // Keep the options' own order so the query (and the saved run) does not depend on click order.
                  const ordered = projectMultiOptions.map((p) => p.value).filter((v) => next.has(v));
                  onChange("project_ids", ordered.length === 0 ? null : ordered.join(","));
                },
              };
            })}
          />
        </div>
      )}
      {shown.map((param) => (
        <ParamControl key={param.name} param={param} value={values[param.name]} onChange={(v) => onChange(param.name, v)} />
      ))}
      {supportsIncludeChildren && (
        <div className="row" style={{ alignItems: "center", gap: "var(--space-3)" }}>
          <ToggleSwitch
            label="Include child projects"
            checked={values.include_children === true}
            onChange={(next) => onChange("include_children", next)}
          />
          <span>Include child projects</span>
        </div>
      )}
    </div>
  );
}

function ParamControl({
  param, value, onChange,
}: {
  param: ReportParam;
  value: ReportRunValues[string];
  onChange: (value: string | number | boolean | null) => void;
}) {
  const label = param.label || humanise(param.name);
  const help = param.description || undefined;
  const controlId = useId();
  if (param.type === "boolean") {
    return (
      <div className="row" style={{ alignItems: "center", gap: "var(--space-3)" }}>
        <ToggleSwitch label={label} checked={value === true} onChange={onChange} />
        <FieldCaption label={label} help={help} />
      </div>
    );
  }
  if (param.choices && param.choices.length > 0) {
    return (
      <LabeledSelect help={help}
        label={label}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(next) => onChange(next === "" ? null : next)}
        options={param.choices.map((c) => ({ value: String(c), label: param.choice_labels?.[String(c)] ?? humanise(c) }))}
        placeholder="Default"
      />
    );
  }
  const inputType = param.type === "integer" ? "number" : param.type === "date" ? "date" : "text";
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption label={label} help={help} htmlFor={controlId} />
      <input
        id={controlId}
        className="input"
        type={inputType}
        min={param.type === "integer" ? param.minimum ?? undefined : undefined}
        max={param.type === "integer" ? param.maximum ?? undefined : undefined}
        value={value === undefined || value === null ? "" : String(value)}
        placeholder={param.default !== null && param.default !== undefined ? `Default: ${param.default}` : undefined}
        onChange={(e) => onChange(e.target.value === "" ? null : param.type === "integer" ? Number(e.target.value) : e.target.value)}
      />
    </div>
  );
}
