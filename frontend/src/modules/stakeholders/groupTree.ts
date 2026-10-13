/**
 * Module: modules/stakeholders/groupTree
 *
 * Pure helpers over the flat Stakeholder-group list the API returns (Phase 3c):
 * building the tree from `parent_group_id`, ancestor/descendant walks, a
 * group's path label, and a stakeholder's branch under a top-level group.
 * Kept free of React so the list, the picker and the manager share one reading
 * of the tree. Walks are cycle-safe (the backend forbids cycles, but a stale
 * list during a move must not hang the page).
 */
import type { TreeSelectNode } from "../../components/TreeSelect";
import type { StakeholderGroup, StakeholderGroupRef } from "./types";

/** A group with its children, for `TreeView`. */
export interface GroupNode extends StakeholderGroup {
  children: GroupNode[];
}

const MAX_DEPTH = 20;

/** Builds the forest from a flat list; a group whose parent is absent is shown as a root. */
export function buildGroupTree(groups: StakeholderGroup[]): GroupNode[] {
  const nodes = new Map<string, GroupNode>(groups.map((g) => [g.id, { ...g, children: [] }]));
  const roots: GroupNode[] = [];
  for (const g of groups) {
    const node = nodes.get(g.id) as GroupNode;
    const parent = g.parent_group_id ? nodes.get(g.parent_group_id) : undefined;
    (parent ? parent.children : roots).push(node);
  }
  return roots;
}

/** Ancestors of `groupId`, nearest first. */
export function ancestorsOf(groups: StakeholderGroupRef[], groupId: string): StakeholderGroupRef[] {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const out: StakeholderGroupRef[] = [];
  let current = byId.get(groupId);
  while (current?.parent_group_id && out.length < MAX_DEPTH) {
    const parent = byId.get(current.parent_group_id);
    if (!parent || out.some((o) => o.id === parent.id)) break;
    out.push(parent);
    current = parent;
  }
  return out;
}

/** The ids of every group below `groupId`. */
export function descendantIds(groups: StakeholderGroupRef[], groupId: string): Set<string> {
  const found = new Set<string>();
  let frontier = [groupId];
  while (frontier.length > 0 && found.size < groups.length) {
    const next: string[] = [];
    for (const g of groups) {
      if (g.parent_group_id && frontier.includes(g.parent_group_id) && !found.has(g.id) && g.id !== groupId) {
        found.add(g.id);
        next.push(g.id);
      }
    }
    frontier = next;
  }
  return found;
}

/** "Client › Acme › Acme — Finance". */
export function groupPath(groups: StakeholderGroupRef[], groupId: string): string {
  const self = groups.find((g) => g.id === groupId);
  if (!self) return "";
  return [...ancestorsOf(groups, groupId).reverse(), self].map((g) => g.name).join(" › ");
}

/** A tree flattened depth-first with each node's depth, for indented `<option>` lists. */
export function flattenGroupTree(nodes: GroupNode[], depth = 0): { group: GroupNode; depth: number }[] {
  return nodes.flatMap((n) => [{ group: n, depth }, ...flattenGroupTree(n.children, depth + 1)]);
}

/** The names of the branches a stakeholder sits in under the top-level group `rootId` (empty when unassigned). */
export function branchNames(groups: StakeholderGroupRef[], direct: StakeholderGroupRef[], rootId: string): string[] {
  const names = new Set<string>();
  for (const ref of direct) {
    const chain = [ref, ...ancestorsOf(groups, ref.id)];
    const at = chain.findIndex((g) => g.id === rootId);
    if (at > 0) names.add(chain[at - 1].name);
  }
  return [...names].sort((a, b) => a.localeCompare(b));
}

/**
 * `TreeSelect` nodes for the groups of one tier. Groups of the other tier stay in the tree (a
 * project group can sit under an organisation group) but are disabled with `otherTierHint`.
 */
export function groupSelectNodes(nodes: GroupNode[], tier: "organization" | "project", otherTierHint: string): TreeSelectNode[] {
  return nodes.map((n) => ({
    id: n.id,
    label: n.name,
    disabled: n.scope !== tier,
    title: n.scope !== tier ? otherTierHint : undefined,
    children: groupSelectNodes(n.children, tier, otherTierHint),
  }));
}

/** `TreeSelect` nodes for every group, none disabled: where either tier's groups may be chosen (an engagement's audience). */
export function allGroupSelectNodes(nodes: GroupNode[]): TreeSelectNode[] {
  return nodes.map((n) => ({ id: n.id, label: n.name, children: allGroupSelectNodes(n.children) }));
}
