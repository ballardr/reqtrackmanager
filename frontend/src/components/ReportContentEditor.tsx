import { useState } from "react";

import { ALL_REPORTS_KEY } from "../api/types";
import type { ReportContentEntry, ReportTypeOption } from "../api/types";
import { t } from "../i18n/strings";
import { OverridePill } from "./OverridePill";
import type { InheritedContent, ReportContentField } from "./reportContentInheritance";
import { ReportChapterListEditor } from "./ReportChapterListEditor";
import { RichTextEditor } from "./RichTextEditor";

const strings = t();

const PLACEHOLDERS: { token: string; description: string }[] = [
  { token: "{{project_name}}", description: strings.reports.placeholderProjectName },
  { token: "{{report_title}}", description: strings.reports.placeholderReportTitle },
  { token: "{{generated_on}}", description: strings.reports.placeholderGeneratedOn },
  { token: "{{organisation}}", description: strings.reports.placeholderOrganisation },
];

function isBlank(entry: ReportContentEntry | undefined): boolean {
  return !entry || (!entry.intro.trim() && entry.chapters.length === 0 && entry.appendices.length === 0);
}

/**
 * The one editor for the introduction, chapters and appendices a scope holds
 * per report type — used by the organisation's report defaults, a report
 * template and a project's Report Setup so the three surfaces cannot drift. A drop-down of report types (the
 * requirements report, each enabled module report; a dozen or more, so not
 * tabs), led by "All reports": the
 * content used by any type without its own at the same level.
 *
 * Controlled: `value` is every entry the scope owns; a type with nothing is
 * simply absent (the server stores no blank rows). `inherited`, where a scope
 * has something to inherit (a project), shows per field where a blank field
 * will get its content from, with {@link OverridePill} offering the way back
 * ("Use inherited") once the scope has set its own.
 *
 * `onActiveChange` tells the page which type is showing so it can load that
 * type's inherited values on demand.
 */
export function ReportContentEditor({
  idPrefix,
  reportTypes,
  value,
  onChange,
  organizationId,
  inherited,
  onActiveChange,
}: {
  idPrefix: string;
  reportTypes: ReportTypeOption[];
  value: ReportContentEntry[];
  onChange: (entries: ReportContentEntry[]) => void;
  organizationId?: string;
  inherited?: Record<string, InheritedContent | undefined>;
  onActiveChange?: (reportKey: string) => void;
}) {
  const types: ReportTypeOption[] = [
    { key: ALL_REPORTS_KEY, title: strings.reports.allReports, module_name: null },
    ...reportTypes,
  ];
  const [active, setActive] = useState<string>(types[0].key);
  const activeType = types.find((tp) => tp.key === active) ?? types[0];
  const entry = value.find((e) => e.report_key === activeType.key);
  const inheritedHere = inherited?.[activeType.key];

  function select(key: string) {
    setActive(key);
    onActiveChange?.(key);
  }

  function update(patch: Partial<Omit<ReportContentEntry, "report_key">>) {
    const next: ReportContentEntry = {
      report_key: activeType.key, intro: "", chapters: [], appendices: [], ...entry, ...patch,
    };
    const others = value.filter((e) => e.report_key !== activeType.key);
    onChange(isBlank(next) ? others : [...others, next]);
  }

  const withContent = types.filter((tp) => !isBlank(value.find((e) => e.report_key === tp.key))).map((tp) => tp.title);

  /** The label (the chapter lists draw their own) and, where there is something to inherit, the pill. */
  function fieldHeader(label: string | null, field: ReportContentField, hasOwn: boolean, reset: () => void) {
    const inheritedField = inheritedHere?.[field];
    if (!label && !inheritedHere) return null;
    return (
      <div className="row" style={{ justifyContent: "space-between" }}>
        {label ? <strong>{label}</strong> : <span />}
        {inheritedHere && (
          <OverridePill
            custom={hasOwn}
            onReset={reset}
            defaultLabel={inheritedField?.label ?? strings.reports.nothingInherited}
            resetLabel={strings.reports.useInherited}
          />
        )}
      </div>
    );
  }

  function inheritedPreview(field: ReportContentField, hasOwn: boolean) {
    const inheritedField = inheritedHere?.[field];
    if (hasOwn || !inheritedField?.preview) return null;
    return (
      <div role="note" className="text-muted" style={{ fontSize: "0.85rem", whiteSpace: "pre-wrap" }} aria-label={strings.reports.inheritedPreview}>
        {inheritedField.preview}
      </div>
    );
  }

  return (
    <div className="stack">
      <label className="stack" style={{ gap: "0.25rem", maxWidth: 360 }}>
        {strings.reports.contentTypes}
        <select id={`${idPrefix}-type`} className="input" value={activeType.key} onChange={(e) => select(e.target.value)}>
          {types.map((tp) => (
            <option key={tp.key} value={tp.key}>
              {isBlank(value.find((e) => e.report_key === tp.key)) ? tp.title : strings.reports.typeWithContent(tp.title)}
            </option>
          ))}
        </select>
      </label>
      <div className="stack">
        <span className="text-muted" style={{ fontSize: "0.85rem" }}>
          {activeType.key === ALL_REPORTS_KEY ? strings.reports.allReportsHint : strings.reports.typeHint(activeType.title)}{" "}
          {withContent.length > 0 ? strings.reports.contentSetFor(withContent.join(", ")) : strings.reports.noContentSet}
        </span>

        <div className="stack" style={{ gap: "0.25rem" }}>
          {fieldHeader(strings.reports.introduction, "intro", Boolean(entry?.intro.trim()), () => update({ intro: "" }))}
          <RichTextEditor
            rows={3}
            value={entry?.intro ?? ""}
            onChange={(intro) => update({ intro })}
            organizationId={organizationId}
          />
          {inheritedPreview("intro", Boolean(entry?.intro.trim()))}
        </div>

        <div className="stack" style={{ gap: "0.25rem" }}>
          {fieldHeader(null, "chapters", (entry?.chapters.length ?? 0) > 0, () => update({ chapters: [] }))}
          <ReportChapterListEditor
            label={strings.reports.bodyChapters}
            list={entry?.chapters ?? []}
            setList={(chapters) => update({ chapters })}
            organizationId={organizationId}
          />
          {inheritedPreview("chapters", (entry?.chapters.length ?? 0) > 0)}
        </div>

        <div className="stack" style={{ gap: "0.25rem" }}>
          {fieldHeader(null, "appendices", (entry?.appendices.length ?? 0) > 0, () => update({ appendices: [] }))}
          <ReportChapterListEditor
            label={strings.reports.appendices}
            list={entry?.appendices ?? []}
            setList={(appendices) => update({ appendices })}
            organizationId={organizationId}
          />
          {inheritedPreview("appendices", (entry?.appendices.length ?? 0) > 0)}
        </div>

        <details>
          <summary>{strings.reports.placeholdersTitle}</summary>
          <p className="text-muted" style={{ margin: "0.25rem 0" }}>{strings.reports.placeholdersHint}</p>
          <ul style={{ margin: 0 }}>
            {PLACEHOLDERS.map((p) => (
              <li key={p.token}>
                <code>{p.token}</code> — {p.description}
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  );
}
