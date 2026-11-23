import { Plus } from "lucide-react";
import { Link } from "react-router-dom";

import type { ProjectTreeNode } from "../api/types";
import { TreeView } from "./TreeView";

/**
 * Presentational project hierarchy tree (`GET /projects/tree`): expand/collapse per node, each name linking to that
 * project's page, with an optional per-node "+" to create a child directly from that node ("Hierarchical
 * projects" in docs/decisions.md).
 *
 * The chevron, indent and expand shell is the shared `TreeView`; this supplies each project's link and "+" button.
 * It has no fetch logic: the page fetches `GET /projects/tree` and passes the result down (see `ViewToggle`).
 */
export function ProjectTree({
  nodes,
  onAddChild,
}: {
  nodes: ProjectTreeNode[];
  onAddChild?: (parentId: string, parentName: string) => void;
}) {
  return (
    <TreeView
      nodes={nodes}
      emptyText="No projects to show."
      nodeLabel={(node) => node.name}
      renderNode={(node) => (
        <>
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
              <Plus />
            </button>
          )}
        </>
      )}
    />
  );
}
