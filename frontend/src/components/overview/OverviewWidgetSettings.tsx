/**
 * Module: components/overview/OverviewWidgetSettings
 *
 * The settings form of one overview widget: its title, size and project scope, then what its type needs (a metric, a
 * record type and its filters, a chart kind, a gauge's range and levels, how many activity entries, a note's text).
 *
 * Responsibilities:
 * - Edit a widget as a controlled value (`onChange` gets the whole widget); nothing is saved here.
 * - Offer only what the server's catalogue lists: a metric of the right kind, a record type the caller may
 *   read, the filters that type's list accepts.
 *
 * Design decisions:
 * - Components and categories are chosen from the project's tree but stored by prefix (`SW`, `SW/PERF`), so the
 *   setting survives a bundle, a template and a child project; an organisation default has no tree, so it offers
 *   no component, category or tag filter.
 * - Provider-specific filters (a status, say) are free name and value rows limited to the names the type's list
 *   takes; the server refuses any other.
 */
import { X } from "lucide-react";
import { useEffect, useId, useState } from "react";

import type { Category, Component, OverviewCatalogue, OverviewScope, OverviewWidget } from "../../api/types";
import { recordPlacementsApi } from "../../api/placements";
import { useStrings } from "../../context/TerminologyContext";
import { isScopedType, OVERVIEW_COLUMNS, OVERVIEW_MAX_ROWS } from "../../utils/overviewWidgets";
import { CommaListField } from "../CommaListField";
import { FieldShell } from "../FieldHelp";
import { TextAreaField, TextField } from "../FormFields";
import { LabeledSelect } from "../LabeledSelect";
import { MultiSelectDropdown } from "../MultiSelectDropdown";

type Config = Record<string, unknown>;
type Filters = Record<string, string[]>;

/** Metric types that read one scalar and so suit a tile or gauge, and those with a breakdown for a chart. */
const SCALAR_TYPES = ["metric_tile", "gauge"];

function paramsOf(config: Config): Config {
  return (config.params as Config | undefined) ?? {};
}

function filtersOf(config: Config): Filters {
  return (paramsOf(config).filters as Filters | undefined) ?? {};
}

/** `config` with its record-count filters replaced (an empty set removes them). */
function withFilters(config: Config, filters: Filters): Config {
  const params = { ...paramsOf(config) };
  if (Object.keys(filters).length > 0) params.filters = filters;
  else delete params.filters;
  return { ...config, params };
}

/** A whole-number field that keeps what is typed (so a box can be cleared and retyped) and applies it once it is a valid size. */
function SizeField({ label, help, value, max, onCommit }: { label: string; help: string; value: number; max: number; onCommit: (value: number) => void }) {
  const [typed, setTyped] = useState<string | null>(null);
  return (
    <TextField
      label={label} help={help} inputProps={{ type: "number", min: 1, max, onBlur: () => setTyped(null) }}
      value={typed ?? String(value)}
      onChange={(text) => {
        setTyped(text);
        const parsed = Number(text);
        if (text.trim() !== "" && Number.isInteger(parsed) && parsed >= 1 && parsed <= max) onCommit(parsed);
      }}
    />
  );
}

/**
 * @param widget The widget being edited.
 * @param onChange Called with the edited widget.
 * @param catalogue What the server offers.
 * @param projectId The project, whose component tree is offered; omit for an organisation default.
 * @param scopes The project scopes the widget may take (the ones this project offers; all four for an organisation).
 */
export function OverviewWidgetSettings({
  widget, onChange, catalogue, projectId, scopes,
}: { widget: OverviewWidget; onChange: (next: OverviewWidget) => void; catalogue: OverviewCatalogue; projectId?: string; scopes: OverviewScope[] }) {
  const strings = useStrings();
  const t = strings.overviewWidgets;
  const config = widget.config;
  const metricKey = typeof config.metric === "string" ? config.metric : "";
  const setConfig = (next: Config) => onChange({ ...widget, config: next });
  const [tree, setTree] = useState<{ components: Component[]; categories: Category[] } | null>(null);
  const componentsId = useId();
  const categoriesId = useId();

  useEffect(() => {
    if (!projectId) return undefined;
    let active = true;
    recordPlacementsApi.tree(projectId).then((loaded) => active && setTree(loaded)).catch(() => active && setTree(null));
    return () => {
      active = false;
    };
  }, [projectId]);

  const usesMetric = ["metric_tile", "gauge", "status_chart"].includes(widget.type);
  const metrics = catalogue.metrics.filter((m) => (SCALAR_TYPES.includes(widget.type) ? m.scalar : m.breakdown));
  const metricInfo = catalogue.metrics.find((m) => m.key === metricKey);
  const countsRecords = metricKey === "record_count";
  const recordType = typeof paramsOf(config).record_type === "string" ? (paramsOf(config).record_type as string) : "";
  const typeInfo = catalogue.record_types.find((r) => r.type === recordType);
  const filters = filtersOf(config);
  const providerFilters = Object.keys(filters).filter((name) => typeInfo?.filter_params.includes(name));
  const setFilter = (name: string, values: string[]) => {
    const next = { ...filters };
    if (values.length > 0) next[name] = values;
    else delete next[name];
    setConfig(withFilters(config, next));
  };
  const toggleIn = (name: string, value: string) => {
    const current = filters[name] ?? [];
    setFilter(name, current.includes(value) ? current.filter((v) => v !== value) : [...current, value]);
  };
  const addableNames = (typeInfo?.filter_params ?? []).filter((name) => !(name in filters));
  const number = (key: string) => (typeof config[key] === "number" ? String(config[key]) : "");
  const setNumber = (key: string, text: string) => {
    const next = { ...config };
    const parsed = Number(text);
    if (text.trim() === "" || Number.isNaN(parsed)) delete next[key];
    else next[key] = parsed;
    setConfig(next);
  };

  return (
    <div className="stack" data-widget-settings={widget.id}>
      <TextField helpNotNeeded label={t.title} value={widget.title ?? ""} placeholder={t.titlePlaceholder} onChange={(v) => onChange({ ...widget, title: v || null })} />
      <div className="row">
        <SizeField label={t.width} help={strings.help.overviewWidgetSize} value={widget.width} max={OVERVIEW_COLUMNS} onCommit={(width) => onChange({ ...widget, width })} />
        <SizeField label={t.height} help={strings.help.overviewWidgetSize} value={widget.height} max={OVERVIEW_MAX_ROWS} onCommit={(height) => onChange({ ...widget, height })} />
      </div>
      {isScopedType(widget.type) && scopes.length > 1 && (
        <LabeledSelect
          label={strings.projectScope.label} help={strings.help.overviewWidgetScope} placeholder={null} value={widget.scope ?? ""}
          options={[{ value: "", label: t.followOverview }, ...scopes.map((scope) => ({ value: scope, label: strings.projectScope.options[scope] }))]}
          onChange={(v) => onChange({ ...widget, scope: v === "" ? null : (v as OverviewScope) })}
        />
      )}

      {usesMetric && (
        <LabeledSelect
          required label={t.metric} help={strings.help.overviewMetric} placeholder={t.validation.metric} value={metricKey}
          options={metrics.map((m) => ({ value: m.key, label: m.label }))}
          onChange={(v) => setConfig({ ...config, metric: v, params: {} })}
        />
      )}

      {usesMetric && countsRecords && (
        <>
          <LabeledSelect
            required label={t.recordType} help={strings.help.overviewRecordType} placeholder={t.chooseRecordType} value={recordType}
            options={catalogue.record_types.map((r) => ({ value: r.type, label: r.label }))}
            onChange={(v) => setConfig({ ...config, params: { record_type: v } })}
          />
          {recordType && projectId && (
            <>
              <CommaListField
                label={t.tags} help={strings.help.overviewFilterTags} value={filters.tag ?? []}
                onChange={(next) => setFilter("tag", next as string[])}
              />
              {(filters.tag ?? []).length > 1 && (
                <LabeledSelect
                  label={t.tagMode} help={strings.help.overviewFilterTagMode} placeholder={null} value={filters.tag_mode?.[0] ?? "any"}
                  options={[{ value: "any", label: t.tagAny }, { value: "all", label: t.tagAll }]}
                  onChange={(v) => setFilter("tag_mode", v === "any" ? [] : [v])}
                />
              )}
              {tree && tree.components.length > 0 && (
                <>
                  <FieldShell label={t.components} controlId={componentsId} help={strings.help.overviewFilterComponents}>
                    <MultiSelectDropdown
                      id={componentsId} triggerLabel={t.components} summaryLimit={2}
                      options={tree.components.map((c) => ({
                        value: c.prefix, label: c.name, optionLabel: c.name, checked: (filters.component ?? []).includes(c.prefix),
                        onToggle: () => toggleIn("component", c.prefix),
                      }))}
                    />
                  </FieldShell>
                  <FieldShell label={t.categories} controlId={categoriesId} help={strings.help.overviewFilterCategories}>
                    <MultiSelectDropdown
                      id={categoriesId} triggerLabel={t.categories} summaryLimit={2} filterable
                      options={tree.categories.map((c) => {
                        const component = tree.components.find((x) => x.id === c.component_id);
                        const key = `${component?.prefix ?? ""}/${c.prefix}`;
                        return {
                          value: key, label: c.name, hint: component?.name, optionLabel: `${component?.name ?? ""} ${c.name}`.trim(),
                          checked: (filters.category ?? []).includes(key), onToggle: () => toggleIn("category", key),
                        };
                      })}
                    />
                  </FieldShell>
                </>
              )}
            </>
          )}
          {typeInfo && (providerFilters.length > 0 || addableNames.length > 0) && (
            <fieldset className="stack" style={{ border: "none", padding: 0, margin: 0 }}>
              <legend><span className="field-caption">{t.otherFilters}</span></legend>
              {providerFilters.map((name) => (
                <div key={name} className="row" style={{ alignItems: "flex-end" }}>
                  <TextField
                    helpNotNeeded label={name} value={(filters[name] ?? []).join(", ")}
                    onChange={(v) => setFilter(name, v.split(",").map((p) => p.trim()).filter(Boolean))}
                  />
                  <button type="button" className="btn btn-icon" aria-label={t.removeFilter(name)} onClick={() => setFilter(name, [])}>
                    <X />
                  </button>
                </div>
              ))}
              {addableNames.length > 0 && (
                <LabeledSelect
                  helpNotNeeded label={t.addFilter} placeholder={t.filterName} value=""
                  options={addableNames.map((name) => ({ value: name, label: name }))}
                  onChange={(name) => name && setFilter(name, [""])}
                />
              )}
            </fieldset>
          )}
        </>
      )}

      {widget.type === "status_chart" && (
        <LabeledSelect
          label={t.chartType} help={strings.help.overviewChartType} placeholder={null} value={String(config.chart ?? "pie")}
          options={[{ value: "pie", label: t.chartPie }, { value: "bar", label: t.chartBar }]}
          onChange={(v) => setConfig({ ...config, chart: v })}
        />
      )}

      {widget.type === "gauge" && (
        <>
          <div className="row">
            <TextField label={t.minimum} help={strings.help.overviewGaugeRange} inputProps={{ type: "number" }} value={number("minimum")} onChange={(v) => setNumber("minimum", v)} />
            <TextField label={t.maximum} help={strings.help.overviewGaugeRange} inputProps={{ type: "number" }} value={number("maximum")} onChange={(v) => setNumber("maximum", v)} />
          </div>
          <div className="row">
            <TextField label={t.warning} help={strings.help.overviewGaugeLevel} inputProps={{ type: "number" }} value={number("warning")} onChange={(v) => setNumber("warning", v)} />
            <TextField label={t.critical} help={strings.help.overviewGaugeLevel} inputProps={{ type: "number" }} value={number("critical")} onChange={(v) => setNumber("critical", v)} />
          </div>
          <LabeledSelect
            label={t.direction} help={strings.help.overviewGaugeDirection} placeholder={null} value={String(config.direction ?? "above")}
            options={[{ value: "above", label: t.directionAbove }, { value: "below", label: t.directionBelow }]}
            onChange={(v) => setConfig({ ...config, direction: v })}
          />
        </>
      )}

      {widget.type === "activity" && (
        <TextField
          label={t.activityLimit} help={strings.help.overviewActivityLimit} inputProps={{ type: "number", min: 1, max: 25 }}
          value={number("limit")} onChange={(v) => setNumber("limit", v)}
        />
      )}

      {widget.type === "text" && (
        <TextAreaField
          label={t.textContent} help={strings.help.overviewText} rows={6}
          value={String(config.markdown ?? "")} onChange={(v) => setConfig({ ...config, markdown: v })}
          inputProps={{ maxLength: 4000 }}
        />
      )}

      {!usesMetric && !["gauge", "activity", "stage_progress", "record_totals", "text"].includes(widget.type) && (
        <p className="text-muted">{t.moduleWidgetNote}</p>
      )}
      {metricInfo === undefined && usesMetric && metricKey !== "" && <p style={{ color: "var(--color-danger)" }}>{t.widgetUnknown}</p>}
    </div>
  );
}
