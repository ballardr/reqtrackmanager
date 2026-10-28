/**
 * Module: components/ReportLayoutWidgetEditor
 *
 * The three controls of a `widget` block: which report component it embeds, that component's settings and how
 * its table is sorted.
 *
 * Responsibilities:
 * - Component: a choice of the components the scope offers, labelled with the module and report they come from;
 *   a stored key the scope no longer offers stays visible and selected, marked as not available.
 * - Settings: the report's own parameters through the shared parameter form; a setting bound to a layout
 *   variable (`{var: name}`) is listed and kept, not drawn as a plain control.
 * - Sort: up to three column headings, each ascending or descending.
 *
 * Design decisions: the component's settings come from the widget list the server publishes, so a module's
 * component needs no code here. A sort heading is typed, because a table's columns are only known when the
 * report runs (the server reports a heading that matches none at run time).
 */
import type { ReportWidget } from "../api/reportLayouts";
import type { ReportRunValues } from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { CheckboxField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { ReportParamsForm } from "./ReportParamsForm";

/** Most sort keys a widget takes. */
const MAX_SORT_KEYS = 3;

/**
 * @param widgets The components the scope offers.
 * @param value The stored component key.
 * @param onChange Called with the chosen key.
 * @param disabled Read-only.
 */
export function WidgetKeyField({
  widgets, value, onChange, disabled, help,
}: { widgets: ReportWidget[]; value: string; onChange: (key: string) => void; disabled?: boolean; help?: string }) {
  const text = useStrings().reportOutline;
  const options = widgets.map((w) => ({ value: w.key, label: `${w.module_name}: ${w.title}` }));
  if (value !== "" && !widgets.some((w) => w.key === value)) options.unshift({ value, label: text.widgetUnknown(value) });
  return (
    <LabeledSelect
      label={text.widgetKey} value={value} placeholder={text.widgetNone} disabled={disabled} options={options} onChange={onChange}
      help={help} required
    />
  );
}

const isReference = (value: unknown): value is { var: string } =>
  value !== null && typeof value === "object" && typeof (value as { var?: unknown }).var === "string";

/**
 * @param widget The chosen component, if the scope offers it.
 * @param value The stored settings.
 * @param onChange Called with the edited settings (`undefined` when none are left).
 * @param disabled Read-only.
 */
export function WidgetParamsField({
  widget, value, onChange, disabled,
}: { widget: ReportWidget | undefined; value: Record<string, unknown>; onChange: (next: Record<string, unknown> | undefined) => void; disabled?: boolean }) {
  const text = useStrings().reportOutline;
  const bound = Object.entries(value).filter(([, v]) => isReference(v)) as [string, { var: string }][];
  const literal: ReportRunValues = Object.fromEntries(Object.entries(value).filter(([, v]) => !isReference(v))) as ReportRunValues;
  if (!widget || (widget.params.length === 0 && bound.length === 0)) return <p className="text-muted" style={{ margin: 0 }}>{text.widgetNoSettings}</p>;

  function set(name: string, next: string | number | boolean | null) {
    const copy = { ...value };
    if (next === null || next === "") delete copy[name];
    else copy[name] = next;
    onChange(Object.keys(copy).length === 0 ? undefined : copy);
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <ReportParamsForm params={widget.params.filter((p) => !bound.some(([name]) => name === p.name))} values={literal} onChange={set} />
      {bound.map(([name, ref]) => (
        <span key={name} className="row" style={{ gap: "var(--space-2)" }}>
          <span>{name}: <span className="text-muted">{text.variableValue(ref.var)}</span></span>
          {!disabled && <button type="button" className="btn btn-sm" onClick={() => set(name, null)}>{text.useValue}</button>}
        </span>
      ))}
    </div>
  );
}

interface SortKey {
  column?: string;
  descending?: boolean;
}

/**
 * @param value The stored sort keys.
 * @param onChange Called with the edited keys (`undefined` when none are left, so the report's own order applies).
 * @param disabled Read-only.
 */
export function WidgetSortField({
  value, onChange, disabled,
}: { value: SortKey[]; onChange: (next: SortKey[] | undefined) => void; disabled?: boolean }) {
  const text = useStrings().reportOutline;
  const set = (next: SortKey[]) => onChange(next.length === 0 ? undefined : next);
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      {value.map((key, i) => (
        <span key={i} className="row" style={{ gap: "var(--space-2)", alignItems: "flex-end" }}>
          <TextField helpNotNeeded
            label={text.widgetColumn(i + 1)} value={key.column ?? ""} disabled={disabled}
            onChange={(column) => set(value.map((k, j) => (j === i ? { ...k, column } : k)))}
          />
          <CheckboxField helpNotNeeded
            label={text.descending} ariaLabel={`${text.widgetColumn(i + 1)}: ${text.descending}`} checked={key.descending === true} disabled={disabled}
            onChange={(on) => set(value.map((k, j) => (j === i ? { column: k.column, ...(on ? { descending: true } : {}) } : k)))}
          />
          {!disabled && <button type="button" className="btn btn-sm" onClick={() => set(value.filter((_, j) => j !== i))}>{text.removeSort(i + 1)}</button>}
        </span>
      ))}
      {!disabled && value.length < MAX_SORT_KEYS && (
        <div><button type="button" className="btn btn-sm" onClick={() => set([...value, { column: "" }])}>{text.addSort}</button></div>
      )}
    </div>
  );
}
