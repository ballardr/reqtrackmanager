/**
 * Module: components/TreeView
 *
 * The one expand/collapse tree shell: an indented list where every node with
 * children gets a chevron toggle and the caller renders each node's own
 * content (a link, a checkbox, a row of actions); the chevron is the shared plain `TreeToggle`. Extracted from
 * `ProjectTree` so the project hierarchy, the Stakeholder group manager and
 * `TreeSelect` share one implementation of the chevron, indentation (one step of `--tree-indent` per level, the same
 * token `FolderTreeList` and the link trace use), ARIA
 * (`aria-expanded`, named toggle) and expand state instead of three copies.
 *
 * Presentational: it owns only which nodes are expanded (or, in controlled mode, none of it: the caller passes
 * `expanded` and `onToggle`, as the report picker does to open every folder while a search is active); a chevron shows its
 * name in a shared `Tooltip` unless `toggleTooltip` is false (a picker's list must not be covered); the data and
 * every mutation stay with the caller (the page/component split `ViewToggle` set).
 */
import { useState, type ReactNode } from "react";

import { TreeToggle, TreeToggleGap } from "./TreeToggle";

/** The minimum a node must be: an id and its children. */
export interface TreeViewNode<N> {
  id: string;
  children: N[];
}

export function TreeView<N extends TreeViewNode<N>>({
  nodes,
  nodeLabel,
  renderNode,
  emptyText = "Nothing to show.",
  defaultExpanded = true,
  expanded,
  onToggle,
  toggleTooltip = true,
}: {
  nodes: N[];
  /** Plain-text name of a node, for the toggle's accessible name ("Collapse Acme"). */
  nodeLabel: (node: N) => string;
  /** The node's own content, shown after the chevron. */
  renderNode: (node: N) => ReactNode;
  emptyText?: string;
  /** Whether nodes start expanded (uncontrolled mode). */
  defaultExpanded?: boolean;
  /** Controlled mode: the ids of the expanded nodes. The caller then owns the state (to expand everything while a
   * search is active, say) and `onToggle` is told what to flip. */
  expanded?: ReadonlySet<string>;
  onToggle?: (id: string, expanded: boolean) => void;
  /** Whether a chevron shows its name in a tooltip (default true); a picker, whose list a tooltip would cover, passes false. */
  toggleTooltip?: boolean;
}) {
  if (nodes.length === 0) return <p className="text-muted">{emptyText}</p>;
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {nodes.map((node) => (
        <TreeViewRow
          key={node.id} node={node} depth={0} nodeLabel={nodeLabel} renderNode={renderNode} defaultExpanded={defaultExpanded}
          expanded={expanded} onToggle={onToggle} toggleTooltip={toggleTooltip}
        />
      ))}
    </ul>
  );
}

function TreeViewRow<N extends TreeViewNode<N>>({
  node,
  depth,
  nodeLabel,
  renderNode,
  defaultExpanded,
  expanded: controlled,
  onToggle,
  toggleTooltip,
}: {
  node: N;
  depth: number;
  nodeLabel: (node: N) => string;
  renderNode: (node: N) => ReactNode;
  defaultExpanded: boolean;
  expanded?: ReadonlySet<string>;
  onToggle?: (id: string, expanded: boolean) => void;
  toggleTooltip: boolean;
}) {
  const [ownExpanded, setOwnExpanded] = useState(defaultExpanded);
  const expanded = controlled ? controlled.has(node.id) : ownExpanded;
  const setExpanded = (update: (current: boolean) => boolean) => {
    const next = update(expanded);
    if (controlled) onToggle?.(node.id, next);
    else setOwnExpanded(next);
  };
  const hasChildren = node.children.length > 0;
  const label = nodeLabel(node);

  return (
    <li>
      <div className="row" style={{ gap: "var(--space-1)", alignItems: "center", paddingLeft: `calc(${depth} * var(--tree-indent))`, minHeight: "2rem" }}>
        {hasChildren ? (
          <TreeToggle expanded={expanded} name={label} onToggle={() => setExpanded((e) => !e)} tooltip={toggleTooltip} />
        ) : (
          <TreeToggleGap />
        )}
        {renderNode(node)}
      </div>
      {hasChildren && expanded && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {node.children.map((child) => (
            <TreeViewRow
              key={child.id} node={child} depth={depth + 1} nodeLabel={nodeLabel} renderNode={renderNode}
              defaultExpanded={defaultExpanded} expanded={controlled} onToggle={onToggle} toggleTooltip={toggleTooltip}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
