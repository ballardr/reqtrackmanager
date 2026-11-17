/**
 * Module: modules/architecture/connectionGuidance
 *
 * The soft guidance a connection form gives when a type is chosen: which connection types fit both ends by domain
 * (a type is in any number of domains; one in none fits every domain), which the two ends' element types suggest, and
 * the warning for a choice that does not fit. Guidance only: nothing here refuses a type; the form lists the fitting types first, offers the rest on request
 * and warns, because a firmware service on a board legitimately speaks an API.
 *
 * Pure functions over the vocabulary rows, so the rules are tested without a screen.
 */
import type { TreeSelectNode } from "../../components/TreeSelect";
import type { ArchitectureDomain, ConnectionType, ElementType } from "./types";

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

/**
 * Whether something in the domains `typeDomains` fits an end in `endDomains` (ids): either side is in none (it fits every
 * domain), or the two share a domain. The browser twin of the server's rule for a toggle rule's domains.
 */
export function domainsFit(typeDomains: readonly string[], endDomains: readonly string[]): boolean {
  return typeDomains.length === 0 || endDomains.length === 0 || typeDomains.some((d) => endDomains.includes(d));
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
  const offered = connectionTypes.filter((t) => known.every((e) => domainsFit(t.domain_ids, e.domain_ids)));
  const fitting = new Set(offered.map((t) => t.id));
  const byId = new Map(connectionTypes.map((t) => [t.id, t]));
  const suggestedIds = [...new Set(known.flatMap((e) => e.suggested_connection_type_ids))];
  return {
    offered,
    hidden: connectionTypes.filter((t) => !fitting.has(t.id)),
    suggested: suggestedIds.map((id) => byId.get(id)).filter((t): t is ConnectionType => t !== undefined),
  };
}

/**
 * The connection type a new connection starts with: the first type its ends' element types suggest, else the first top-level
 * type that fits both ends by domain, else the first that fits, else the first type there is. `undefined` only when the project
 * has no connection type at all (a connection cannot exist without one).
 *
 * @param connectionTypes Every connection type the project lists.
 * @param ends The element types at the source and target (`undefined` for one that is not known).
 */
export function defaultConnectionType(
  connectionTypes: ConnectionType[], ends: Array<ElementType | undefined>,
): ConnectionType | undefined {
  const { suggested, offered } = guideConnectionTypes(connectionTypes, ends);
  return suggested[0] ?? offered.find((t) => t.parent_ids.length === 0) ?? offered[0] ?? connectionTypes[0];
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
 * @param domains The project's domains, which give the names the warning uses.
 */
export function mismatchWarning(
  selected: ConnectionType | undefined, ends: Array<ElementType | undefined>, domains: readonly ArchitectureDomain[],
): string | null {
  if (!selected || ends.some((end) => end?.suggested_connection_type_ids.includes(selected.id))) return null;
  const named = (ids: readonly string[]) => ids.map((id) => domains.find((d) => d.id === id)?.name ?? "another domain").join(" and ");
  const names = ["source", "target"];
  const problems = ends.flatMap((end, index) =>
    end && !domainsFit(selected.domain_ids, end.domain_ids)
      ? [`the ${names[index]} element (${end.name}) is in ${named(end.domain_ids)}`]
      : []);
  if (problems.length === 0) return null;
  return `${selected.name} is in ${named(selected.domain_ids)}, but ${problems.join(" and ")}. The connection can still be saved.`;
}
