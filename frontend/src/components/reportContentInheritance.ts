/**
 * Module: components/reportContentInheritance
 *
 * What a scope's blank report-content field would inherit, described for the
 * `ReportContentEditor` (Phase 10 of the platform enhancements plan): the
 * inherited-value shapes, a plain-text preview of chapters, words naming where
 * an effective value came from, and the conversion from the server's
 * effective-content response. Kept out of the component file so that file
 * exports only a component (fast refresh).
 */
import type { EffectiveReportContent, ReportChapter, ReportContentSource } from "../api/types";
import { t } from "../i18n/strings";

const strings = t();

/** What a field would use if this scope left it blank: where it comes from, and the content. */
export interface InheritedField {
  /** Words naming the source, e.g. "Inherited from Platform" (see {@link describeContentSource}). */
  label: string;
  /** Plain-text preview of the inherited value. */
  preview: string;
}

/** Inherited values for one report type, per field; a missing field inherits nothing. */
export type InheritedContent = Partial<Record<ReportContentField, InheritedField>>;

export type ReportContentField = "intro" | "chapters" | "appendices";

/** A plain-text preview of chapters: one `title` line each. */
export function chaptersPreview(chapters: ReportChapter[]): string {
  return chapters.map((c) => c.title).filter(Boolean).join(" · ");
}

/** Words naming where an effective value came from, relative to the project viewing it. */
export function describeContentSource(source: ReportContentSource): string {
  switch (source.scope_type) {
    case "organization":
      return strings.reports.inheritedOrganisation(source.scope_name);
    case "template":
      return strings.reports.inheritedTemplate(source.scope_name);
    case "project_summary":
      return strings.reports.inheritedDescription(source.scope_name);
    default:
      return strings.reports.inheritedFrom(source.scope_name);
  }
}

/**
 * The inherited values the project editor shows for one report type, from the
 * effective-content endpoint. A field whose source is the project itself has
 * nothing further to inherit, so it is left out (the editor then shows the
 * project's own value).
 */
export function inheritedFromEffective(effective: EffectiveReportContent, projectId: string): InheritedContent {
  const out: InheritedContent = {};
  const fields: [ReportContentField, ReportContentSource | null, string][] = [
    ["intro", effective.intro_source, effective.intro],
    ["chapters", effective.chapters_source, chaptersPreview(effective.chapters)],
    ["appendices", effective.appendices_source, chaptersPreview(effective.appendices)],
  ];
  for (const [field, source, preview] of fields) {
    if (source && !(source.scope_type === "project" && source.scope_id === projectId)) {
      out[field] = { label: describeContentSource(source), preview };
    }
  }
  return out;
}

