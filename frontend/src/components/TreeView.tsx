/**
 * Module: components/TreeView
 *
 * The one expand/collapse tree shell: an indented list where every node with
 * children gets a chevron toggle and the caller renders each node's own
 * content (a link, a checkbox, a row of actions). Extracted from
 * `ProjectTree` so the project hierarchy, the Stakeholder group manager and
 * `TreeSelect` share one implementation of the chevron, indentation, ARIA
 * (`aria-expanded`, named toggle) and expand state instead of three copies.
 *
 * Presentational: it owns only which nodes are expanded; the data and every
 * mutation stay with the caller (the page/component split `ViewToggle` set).
 */
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";

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
}: {
  nodes: N[];
  /** Plain-text name of a node, for the toggle's accessible name ("Collapse Acme"). */
  nodeLabel: (node: N) => string;
  /** The node's own content, shown after the chevron. */
  renderNode: (node: N) => ReactNode;
  emptyText?: string;
  /** Whether nodes start expanded. */
  defaultExpanded?: boolean;
}) {
  if (nodes.length === 0) return <p className="text-muted">{emptyText}</p>;
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {nodes.map((node) => (
        <TreeViewRow key={node.id} node={node} depth={0} nodeLabel={nodeLabel} renderNode={renderNode} defaultExpanded={defaultExpanded} />
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
}: {
  node: N;
  depth: number;
  nodeLabel: (node: N) => string;
  renderNode: (node: N) => ReactNode;
  defaultExpanded: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const hasChildren = node.children.length > 0;
  const label = nodeLabel(node);

  return (
    <li>
      <div className="row" style={{ gap: "0.25rem", alignItems: "center", paddingLeft: `${depth * 1.5}rem`, minHeight: "2rem" }}>
        {hasChildren ? (
          <button
            className="btn"
            style={{ padding: "0.15rem" }}
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? "Collapse" : "Expand"}
            aria-label={expanded ? `Collapse ${label}` : `Expand ${label}`}
            aria-expanded={expanded}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span style={{ width: "1.65rem", display: "inline-block" }} />
        )}
        {renderNode(node)}
      </div>
      {hasChildren && expanded && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {node.children.map((child) => (
            <TreeViewRow
              key={child.id} node={child} depth={depth + 1} nodeLabel={nodeLabel} renderNode={renderNode}
              defaultExpanded={defaultExpanded}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
