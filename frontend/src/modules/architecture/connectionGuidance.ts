/**
 * Module: modules/architecture/connectionGuidance
 *
 * The soft guidance a connection form gives when a type is chosen: which connection types fit both ends by domain
 * (hardware, software or any), which the two ends' element types suggest, and the warning for a choice that does not
 * fit. Guidance only: nothing here refuses a type; the form lists the fitting types first, offers the rest on request
 * and warns, because a firmware service on a board legitimately speaks an API.
 *
 * Pure functions over the vocabulary rows, so the rules are tested without a screen.
 */
import type { TreeSelectNode } from "../../components/TreeSelect";
import { DOMAIN_LABEL, type ConnectionType, type Domain, type ElementType } from "./types";

/** The id of the "Suggested" group the picker shows above the tree (never a connection type's id). */
export const SUGGESTED_GROUP_ID = "__suggested__";

/** What the guidance says about a pair of ends. */
export interface ConnectionGuidance {
  /** The types that fit both ends, in picker order. */
  offered: ConnectionType[];
  /** The types the domain filter hides until "Show all types" is on. */
  hidden: ConnectionType[];
  /** The types the ends' element types suggest (source's first, none twice), whatever their domain. */
  suggested: ConnectionType[];
}

/** Whether something of `typeDomain` fits an end of `endDomain`: either side `any`, or the same domain. */
export function domainFits(typeDomain: Domain, endDomain: Domain): boolean {
  return typeDomain === "any" || endDomain === "any" || typeDomain === endDomain;
}

/**
 * @param connectionTypes Every connection type the project lists.
 * @param ends The element types at the source and target; `undefined` for an end not chosen or whose type is not in
 *   the project's list (it then imposes no domain and suggests nothing).
 */
export function guideConnectionTypes(
  connectionTypes: ConnectionType[], ends: Array<ElementType | undefined>,
): ConnectionGuidance {
  const known = ends.filter((e): e is ElementType => e !== undefined);
  const offered = connectionTypes.filter((t) => known.every((e) => domainFits(t.domain, e.domain)));
  const fitting = new Set(offered.map((t) => t.id));
  const byId = new Map(connectionTypes.map((t) => [t.id, t]));
  const suggestedIds = [...new Set(known.flatMap((e) => e.suggested_connection_type_ids))];
  return {
    offered,
    hidden: connectionTypes.filter((t) => !fitting.has(t.id)),
    suggested: suggestedIds.map((id) => byId.get(id)).filter((t): t is ConnectionType => t !== undefined),
  };
}

/** The "Suggested" group for the top of the picker's tree: each suggested type once, as a leaf. */
export function suggestedGroup(suggested: ConnectionType[]): TreeSelectNode[] {
  if (suggested.length === 0) return [];
  return [{
    id: SUGGESTED_GROUP_ID, label: "Suggested", disabled: true, title: "Suggested for the element types of the chosen elements.",
    children: suggested.map((t) => ({ id: t.id, label: t.name, children: [] })),
  }];
}

/**
 * The warning for a chosen type, or `null` when it fits both ends by domain or either end's element type suggests it (a
 * firmware service on a board legitimately speaks an API, so a suggestion excuses the pair).
 *
 * @param selected The chosen connection type.
 * @param ends The element types at the source and target, in that order.
 */
export function mismatchWarning(selected: ConnectionType | undefined, ends: Array<ElementType | undefined>): string | null {
  if (!selected || ends.some((end) => end?.suggested_connection_type_ids.includes(selected.id))) return null;
  const names = ["source", "target"];
  const problems = ends.flatMap((end, index) =>
    end && !domainFits(selected.domain, end.domain)
      ? [`the ${names[index]} element (${end.name}) is ${DOMAIN_LABEL[end.domain].toLowerCase()}`]
      : []);
  if (problems.length === 0) return null;
  return `${selected.name} is a ${DOMAIN_LABEL[selected.domain].toLowerCase()} connection type, but ${problems.join(" and ")}. The connection can still be saved.`;
}
