import { ChevronDown, ChevronRight, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import type { ProjectTreeNode } from "../api/types";

/**
 * Presentational project hierarchy tree (`GET /projects/tree`) — expand/
 * collapse per node, each name linking to that project's page, with an
 * optional per-node "+" affordance to create a child directly from that
 * node (decision 8 in docs/decisions.md's "Hierarchical projects" entry —
 * the "Add sub-project" workflow shouldn't require navigating away first).
 *
 * No fetch logic of its own — the page owns fetching from `GET /projects/
 * tree` and passes the result down, matching this app's existing page/
 * component split (see `ViewToggle`).
 */
export function ProjectTree({
  nodes,
  onAddChild,
}: {
  nodes: ProjectTreeNode[];
  onAddChild?: (parentId: string, parentName: string) => void;
}) {
  if (nodes.length === 0) {
    return <p className="text-muted">No projects to show.</p>;
  }
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {nodes.map((node) => (
        <ProjectTreeNodeRow key={node.id} node={node} depth={0} onAddChild={onAddChild} />
      ))}
    </ul>
  );
}

function ProjectTreeNodeRow({
  node,
  depth,
  onAddChild,
}: {
  node: ProjectTreeNode;
  depth: number;
  onAddChild?: (parentId: string, parentName: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div
        className="row"
        style={{ gap: "0.25rem", alignItems: "center", paddingLeft: `${depth * 1.5}rem`, minHeight: "2rem" }}
      >
        {hasChildren ? (
          <button
            className="btn"
            style={{ padding: "0.15rem" }}
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? "Collapse" : "Expand"}
            aria-label={expanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
            aria-expanded={expanded}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span style={{ width: "1.65rem", display: "inline-block" }} />
        )}
        <Link
          to={`/projects/${node.id}`}
          style={{ opacity: node.is_archived ? 0.6 : 1, textDecoration: node.is_archived ? "line-through" : undefined }}
        >
          {node.name}
        </Link>
        {onAddChild && (
          <button
            className="btn"
            style={{ padding: "0.15rem" }}
            onClick={() => onAddChild(node.id, node.name)}
            title={`Add a sub-project under ${node.name}`}
            aria-label={`Add a sub-project under ${node.name}`}
          >
            <Plus size={14} />
          </button>
        )}
      </div>
      {hasChildren && expanded && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {node.children.map((child) => (
            <ProjectTreeNodeRow key={child.id} node={child} depth={depth + 1} onAddChild={onAddChild} />
          ))}
        </ul>
      )}
    </li>
  );
}
