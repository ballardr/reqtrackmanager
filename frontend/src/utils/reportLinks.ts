/**
 * Module: utils/reportLinks
 *
 * Turns a report figure's route-neutral `ReportLink` into an app URL, so a
 * report can say "this number opens the Pain Points list filtered to
 * Blockers" without a collector, or core, hard-coding UI routes.
 *
 * Figures link only inside a *project* report: the module pages they open
 * (lists of Pain Points, Open Questions, ...) are per project, so an
 * organisation-wide report, which spans projects, has no single page to open
 * and shows plain numbers (`reportLinkResolver` returns `undefined`).
 */
import type { ReportLink } from "../api/reports";
import { humanise } from "./humanise";

/** Resolves a figure's link to an in-app path. */
export type ReportLinkResolver = (link: ReportLink) => string;

function queryString(query: Record<string, string>): string {
  const params = new URLSearchParams(query);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/**
 * @param scope What the report ran against.
 * @param moduleKey The module that owns the report (its project pages live under `/modules/<key>/`).
 * @returns A resolver for a project report, or `undefined` for an organisation report.
 */
export function reportLinkResolver(
  scope: { kind: "project" | "organization"; id: string },
  moduleKey: string,
): ReportLinkResolver | undefined {
  if (scope.kind !== "project") return undefined;
  return (link) => {
    if (link.kind === "module") {
      return `/projects/${scope.id}/modules/${moduleKey}/${link.target}${queryString(link.query)}`;
    }
    const params = new URLSearchParams({ report: link.target, ...link.query });
    if (link.section) params.set("section", link.section);
    return `/projects/${scope.id}/reports?${params.toString()}`;
  };
}

/**
 * One line saying where a figure's link leads, for its tooltip.
 *
 * @param link The figure's link.
 * @param label The figure's label, used when the link applies filters.
 * @returns For example `Opens the Pain points list, filtered to "Blockers"`.
 */
export function describeReportLink(link: ReportLink, label: string): string {
  const name = humanise(link.target.replace(/-/g, "_")).toLowerCase();
  if (link.kind === "report") return `Opens the ${name} report at the table that lists these`;
  return Object.keys(link.query).length > 0 ? `Opens the ${name} list, filtered to "${label}"` : `Opens the ${name} list`;
}
