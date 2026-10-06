/**
 * Module: components/ReportParamsForm
 *
 * The parameter form of the core report framework's Reports UI (Module 1
 * Phase 13): one labelled control per parameter a report declares (a select
 * for `choices`, a bounded number, a switch, a date, or text for string/uuid),
 * plus the framework-level options: the "include child projects" switch for
 * project reports and, for organisation-wide reports, a "Project" picker that
 * narrows the run to one project (`project_id`, "All projects" when blank). Generated entirely from the catalogue entry, so a new module report
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
import type { ReportParam, ReportRunValues } from "../api/reports";
import { humanise } from "../utils/humanise";
import { LabeledSelect } from "./LabeledSelect";
import { ToggleSwitch } from "./ToggleSwitch";

/**
 * @param params The report's declared parameters.
 * @param values Current values by parameter name (and `include_children`).
 * @param onChange Called with a parameter name and its new value.
 * @param hidden Parameter names to leave out (owned by a custom view).
 * @param supportsIncludeChildren Whether to offer the framework `include_children` switch.
 * @param projectOptions Projects to offer in the `project_id` picker; omitted hides it.
 */
export function ReportParamsForm({
  params, values, onChange, hidden = [], supportsIncludeChildren = false, projectOptions,
}: {
  params: ReportParam[];
  values: ReportRunValues;
  onChange: (name: string, value: string | number | boolean | null) => void;
  hidden?: string[];
  supportsIncludeChildren?: boolean;
  projectOptions?: { value: string; label: string }[];
}) {
  const shown = params.filter((p) => !hidden.includes(p.name));
  if (shown.length === 0 && !supportsIncludeChildren && !projectOptions) return null;
  return (
    <div className="row" style={{ gap: "1rem", flexWrap: "wrap", alignItems: "flex-end" }} role="group" aria-label="Report options">
      {projectOptions && (
        <LabeledSelect
          label="Project"
          value={typeof values.project_id === "string" ? values.project_id : ""}
          onChange={(next) => onChange("project_id", next === "" ? null : next)}
          options={projectOptions}
          placeholder="All projects"
        />
      )}
      {shown.map((param) => (
        <ParamControl key={param.name} param={param} value={values[param.name]} onChange={(v) => onChange(param.name, v)} />
      ))}
      {supportsIncludeChildren && (
        <div className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
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
  if (param.type === "boolean") {
    return (
      <div className="row" style={{ alignItems: "center", gap: "0.5rem" }} title={help}>
        <ToggleSwitch label={label} checked={value === true} onChange={onChange} />
        <span>{label}</span>
      </div>
    );
  }
  if (param.choices && param.choices.length > 0) {
    return (
      <LabeledSelect
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
    <label className="stack" style={{ gap: "0.25rem" }} title={help}>
      <span>{label}</span>
      <input
        className="input"
        type={inputType}
        min={param.type === "integer" ? param.minimum ?? undefined : undefined}
        max={param.type === "integer" ? param.maximum ?? undefined : undefined}
        value={value === undefined || value === null ? "" : String(value)}
        placeholder={param.default !== null && param.default !== undefined ? `Default: ${param.default}` : undefined}
        onChange={(e) => onChange(e.target.value === "" ? null : param.type === "integer" ? Number(e.target.value) : e.target.value)}
      />
    </label>
  );
}
