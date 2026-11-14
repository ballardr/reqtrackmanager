/**
 * Module: components/CanvasCommentLayer.fixture
 *
 * A host for the comment layer's stories: a small canvas for a record of a made-up type (not an architecture diagram), with
 * the comment-mode, Show comments and Show resolved switches a real page offers, and anchors keyed `key:<node id>`.
 */
import type { RecordCommentsApi } from "../api/recordComments";
import { useCanvasComments } from "./CanvasCommentLayer";
import { GraphCanvas, type GraphCanvasNode } from "./GraphCanvas";

const NODES: GraphCanvasNode[] = [
  { id: "sensor", label: "Sensor", x: 0, y: 0 },
  { id: "gateway", label: "Gateway", x: 280, y: 0 },
];

/** The story host: spreads the layer's canvas props onto a `GraphCanvas`. */
export function CanvasCommentLayer({ client }: { client: RecordCommentsApi }) {
  const layer = useCanvasComments({
    projectId: "project-1", artefactType: "demo_record", recordId: "record-1", client,
    anchorOf: (place) => (place.anchor_key?.startsWith("key:") ? { kind: place.anchor_kind === "edge" ? "edge" : "node", id: place.anchor_key.slice(4) } : undefined),
    placeOf: (position, anchor) =>
      anchor.kind === "node"
        ? { anchor_kind: "node", anchor_key: `key:${anchor.id}`, x: position.x, y: position.y }
        : { anchor_kind: "none", anchor_key: null, x: position.x, y: position.y },
  });
  return (
    <div className="stack">
      <div className="row">
        <button type="button" className="btn" aria-pressed={layer.commentMode} onClick={() => layer.setCommentMode(!layer.commentMode)}>Comment</button>
        <label><input type="checkbox" checked={layer.showComments} onChange={(e) => layer.setShowComments(e.target.checked)} /> Show comments</label>
        <label><input type="checkbox" checked={layer.showResolved} onChange={(e) => layer.setShowResolved(e.target.checked)} /> Show resolved</label>
      </div>
      <GraphCanvas nodes={NODES} edges={[]} ariaLabel="Demo canvas" showViewToggle={false} height={320} {...layer.canvasProps} />
    </div>
  );
}
