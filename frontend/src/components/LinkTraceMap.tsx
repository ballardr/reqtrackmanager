/**
 * Module: components/LinkTraceMap
 *
 * The trace map of one record's links: a read-only, layered SVG diagram with
 * upstream records on the left, the record in the centre, downstream records on
 * the right and related records below, each group on its own tinted lane. It scrolls,
 * and grows as the user opens records ("Show more"), so the depth is unlimited.
 *
 * Responsibilities:
 * - Read the record's graph two hops out, then one hop per record the user expands,
 *   folding each read into one accumulated graph.
 * - Draw it with `layoutLinkMap` (pure) as hand-built SVG; every record is a real link
 *   to its page, in reading order, so the map is keyboard-navigable and its text
 *   alternative is the Tree tab.
 *
 * Design decisions:
 * - Layered, not force-directed, and
 *   hand-built SVG: no graph library, and none of the click-through limits of a Mermaid
 *   diagram at its required security level.
 * - Colours come from theme variables (light and dark); direction is carried by position,
 *   lane headings and arrowheads (pointing downstream), never by colour alone. The key
 *   (`LinkTraceLegend`) names every symbol.
 * - "Show more" is a labelled pill hanging off the node's bottom edge, the one place no edge
 *   attaches, with a pending state while it reads and a "No more links" note once it found none.
 *   Hovering or focusing a record highlights its own edges and dims the rest; selecting a record
 *   by click is deliberately absent, because a click on a record is navigation.
 * - API calls are injectable (`api`) so stories need no network.
 */
import { Info } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { artefactLinksApi, type ArtefactLinksApi, type LinkGraph } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { getArtefactPath, getArtefactStatusLabel } from "../modules/artefactPaths";
import { CHIP_H, CHIP_W, ChipFace } from "./LinkTraceChip";
import { LinkTraceLegend } from "./LinkTraceLegend";
import {
  layoutLinkMap, mergeGraphs, mostLinksUndirected, nodeKey, wrapLabel, MAP_NODE_CAP, MAP_NODE_H, MAP_NODE_PAD_X, MAP_NODE_W,
  type MapLane, type MapLayout, type PlacedEdge, type PlacedNode,
} from "./linkTrace";
import { Popover } from "./Popover";
import { inactiveFilter } from "./linkTraceBridge";
import { Spinner } from "./Spinner";

/** Hops read when the map opens; later hops come one record at a time. */
const INITIAL_DEPTH = 2;
/** Approximate width of one 10px edge-label character, for sizing its pill. */
const EDGE_CHAR_W = 5.4;
function clip(text: string, width: number): string {
  return text.length > width ? `${text.slice(0, width - 1)}…` : text;
}

export function LinkTraceMap({
  projectId,
  artefactType,
  artefactId,
  hideInactive = false,
  api = artefactLinksApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  /** Skip superseded, archived and retired records, joining what they link to the record in front. */
  hideInactive?: boolean;
  api?: ArtefactLinksApi;
}) {
  const strings = useStrings();
  const [graph, setGraph] = useState<LinkGraph | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  /** Records whose own links were read and had nothing further. */
  const [exhausted, setExhausted] = useState<Set<string>>(new Set());
  /** The record under the pointer or keyboard focus, whose edges are highlighted. */
  const [active, setActive] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const [moreFailed, setMoreFailed] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);
  const keyButtonRef = useRef<HTMLButtonElement>(null);
  const markerId = useId().replace(/:/g, "");

  useEffect(() => {
    let active = true;
    api.graph(projectId, artefactType, artefactId, INITIAL_DEPTH)
      .then((result) => {
        if (!active) return;
        setGraph(result);
        // Records within the first hops already had their own links read, except that related records stay
        // closed (one hop deep) until the user opens them: there can be many.
        const related = new Set(layoutLinkMap(result).nodes.filter((n) => n.branch === "related").map((n) => n.key));
        setExpanded(
          new Set(
            [result.root, ...result.nodes]
              .filter((n) => n.depth < INITIAL_DEPTH)
              .map((n) => nodeKey(n.type, n.id))
              .filter((key) => !related.has(key)),
          ),
        );
        setAnnounce("");
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType, artefactId]);

  const layoutOptions = useMemo(
    () => ({ hidden: hideInactive ? inactiveFilter(true) : undefined, expanded }),
    [hideInactive, expanded],
  );
  const layout = useMemo(() => (graph ? layoutLinkMap(graph, MAP_NODE_CAP, layoutOptions) : null), [graph, layoutOptions]);

  // A hidden record the layout joined through has to be read before what it links to can be drawn.
  const unreadKey = layout?.unread.join("|") ?? "";
  useEffect(() => {
    if (!unreadKey) return;
    let live = true;
    const keys = unreadKey.split("|");
    Promise.all(
      keys.map(async (key) => {
        const [type, ...rest] = key.split(":");
        try {
          return await api.graph(projectId, type, rest.join(":"), 1);
        } catch {
          return null;
        }
      }),
    ).then((reads) => {
      if (!live) return;
      setGraph((prev) => (prev ? reads.reduce<LinkGraph>((acc, more) => (more ? mergeGraphs(acc, more) : acc), prev) : prev));
      // A failed read is not retried in a loop; the record's links stay out of the map.
      setExpanded((prev) => new Set([...prev, ...keys]));
      if (reads.some((r) => r === null)) setMoreFailed(true);
    });
    return () => {
      live = false;
    };
  }, [unreadKey, api, projectId]);

  async function showMore(placed: PlacedNode) {
    if (!graph || busy) return;
    setBusy(placed.key);
    try {
      const more = await api.graph(projectId, placed.node.type, placed.node.id, 1);
      const merged = mergeGraphs(graph, more);
      const grew = layoutLinkMap(merged, MAP_NODE_CAP, { ...layoutOptions, expanded: new Set([...expanded, placed.key]) }).nodes.length > (layout?.nodes.length ?? 0);
      setGraph(merged);
      setExpanded((prev) => new Set(prev).add(placed.key));
      if (!grew) setExhausted((prev) => new Set(prev).add(placed.key));
      setMoreFailed(false);
      setAnnounce(grew ? "" : strings.artefactLinks.traceNothingFurtherFor(placed.node.label));
    } catch {
      setMoreFailed(true);
      setAnnounce(strings.artefactLinks.traceMapLoadMoreFailed);
    } finally {
      setBusy(null);
    }
  }

  if (failed) return <p className="text-muted">{strings.artefactLinks.loadError}</p>;
  if (!graph || !layout) return <Spinner label={strings.artefactLinks.traceLoading} />;

  const byKey = new Map(layout.nodes.map((n) => [n.key, n]));
  const headingLabel = { upstream: strings.artefactLinks.traceUpstream, downstream: strings.artefactLinks.traceDownstream, focus: strings.artefactLinks.traceFocus, related: strings.artefactLinks.traceRelated };
  return (
    <div className="stack link-trace">
      <div className="row link-trace__hint-row">
        <p className="text-muted link-trace__hint">{strings.artefactLinks.traceMapHint}</p>
        <button
          ref={keyButtonRef}
          type="button"
          className="btn link-trace__key-button"
          aria-haspopup="dialog"
          aria-expanded={keyOpen}
          onClick={() => setKeyOpen((open) => !open)}
        >
          <Info /> {strings.artefactLinks.traceLegendLabel}
        </button>
        {keyOpen && (
          <Popover anchorRef={keyButtonRef} title={strings.artefactLinks.traceLegendLabel} onClose={() => setKeyOpen(false)}>
            <LinkTraceLegend />
          </Popover>
        )}
      </div>
      {mostLinksUndirected(graph) && <p className="link-trace__callout">{strings.artefactLinks.traceUnclassifiedHint}</p>}
      <div
        className="link-trace__map"
        role="region"
        aria-label={strings.artefactLinks.traceMapLabel(graph.root.label)}
        tabIndex={0}
      >
        <svg
          className={active ? "link-trace__svg--tracing" : undefined}
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
        >
          <title>{strings.artefactLinks.traceMapLabel(graph.root.label)}</title>
          <desc>{strings.artefactLinks.traceMapDescription}</desc>
          <defs>
            <marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
              <path className="link-trace__arrow" d="M 0 0 L 10 5 L 0 10 Z" />
            </marker>
          </defs>
          {layout.lanes.map((lane) => (
            <g key={lane.flow} aria-hidden="true">
              <rect className={`link-trace__lane link-trace__lane--${lane.flow}`} x={lane.x} y={lane.y} width={lane.width} height={lane.height} rx={8} />
              <LaneHeading lane={lane} label={headingLabel[lane.flow]} />
            </g>
          ))}
          {layout.edges.map((edge) => (
            <MapEdge
              key={edge.id}
              edge={edge}
              markerId={markerId}
              active={active !== null && (edge.fromKey === active || edge.toKey === active)}
              title={strings.artefactLinks.traceMapEdgeLabel(edge.phrase ?? "", byKey.get(edge.fromKey)?.node.label ?? "", byKey.get(edge.toKey)?.node.label ?? "") + (edge.via.length ? ` (${strings.artefactLinks.traceViaDashedEdge(edge.via.join(", "))})` : "")}
            />
          ))}
          {orderedForReading(layout).map((placed) => (
            <MapNode
              key={placed.key}
              placed={placed}
              projectId={projectId}
              canExpand={!expanded.has(placed.key)}
              busy={busy === placed.key}
              exhausted={exhausted.has(placed.key)}
              onActive={setActive}
              onExpand={() => void showMore(placed)}
            />
          ))}
        </svg>
      </div>
      {layout.nodes.length === 1 && <p className="text-muted artefact-links__note">{strings.artefactLinks.traceMapEmpty}</p>}
      {/* "Nothing further" is shown on the record itself; this announces it (and a failure) to screen readers. */}
      <p className="sr-only" role="status" aria-live="polite">{announce}</p>
      {moreFailed && <p className="text-muted artefact-links__note" aria-hidden="true">{announce}</p>}
      {layout.capped && (
        <p className="text-muted artefact-links__note">{strings.artefactLinks.traceMapCapNote(layout.capped.shown, layout.capped.total)}</p>
      )}
      {graph.hidden_count > 0 && <p className="text-muted artefact-links__note">{strings.artefactLinks.traceHiddenNote}</p>}
      {graph.truncated && <p className="text-muted artefact-links__note">{strings.artefactLinks.traceTruncatedNote}</p>}
    </div>
  );
}

/** A lane's heading: centred over a main lane, at the left of the wide related lane. */
function LaneHeading({ lane, label }: { lane: MapLane; label: string }) {
  const wide = lane.flow === "related";
  return (
    <text
      className="link-trace__heading"
      x={wide ? lane.x + 14 : lane.x + lane.width / 2}
      y={lane.y + 19}
      textAnchor={wide ? "start" : "middle"}
    >
      {label}
    </text>
  );
}

/**
 * One link: a curve with an arrowhead pointing downstream (upstream links are drawn from the
 * focus outwards, so their arrow sits at the start; related links have none) and the relationship
 * as a small pill on it. Decorative: the Tree tab and the record links carry the same facts.
 */
function MapEdge({ edge, markerId, active, title }: { edge: PlacedEdge; markerId: string; active: boolean; title: string }) {
  const marker = `url(#${markerId})`;
  const label = edge.phrase ? clip(edge.phrase, 16) : null;
  const pillW = label ? label.length * EDGE_CHAR_W + 12 : 0;
  return (
    <g className={`link-trace__edge-group ${active ? "link-trace__edge-group--active" : ""}`} aria-hidden="true">
      <path
        className={`link-trace__edge ${edge.via.length > 0 ? "link-trace__edge--joined" : ""}`}
        d={edge.path}
        markerStart={edge.branch === "upstream" ? marker : undefined}
        markerEnd={edge.branch === "downstream" ? marker : undefined}
      />
      {label && (
        <g>
          <title>{title}</title>
          <rect className="link-trace__edge-pill" x={edge.labelX - pillW / 2} y={edge.labelY - 8} width={pillW} height={16} rx={8} />
          <text className="link-trace__edge-label" x={edge.labelX} y={edge.labelY + 3.5} textAnchor="middle">{label}</text>
        </g>
      )}
    </g>
  );
}

/** Upstream, then the focus record, then downstream, then related, nearest first: the order focus moves in. */
function orderedForReading(layout: MapLayout): PlacedNode[] {
  const rank = { upstream: 0, focus: 1, downstream: 2, related: 3 } as const;
  return [...layout.nodes].sort((a, b) => rank[a.branch] - rank[b.branch] || a.level - b.level || a.y - b.y || a.x - b.x);
}

/**
 * One record: a link to its page, plus, while its own links are unread, a "Show more" pill on
 * its bottom edge (a pending pill while it reads, a "No more links" note once it found none).
 */
function MapNode({
  placed,
  projectId,
  canExpand,
  busy,
  exhausted,
  onActive,
  onExpand,
}: {
  placed: PlacedNode;
  projectId: string;
  canExpand: boolean;
  busy: boolean;
  exhausted: boolean;
  /** Reports the record under the pointer or focus (`null` when it leaves). */
  onActive: (key: string | null) => void;
  onExpand: () => void;
}) {
  const strings = useStrings();
  const { node, x, y } = placed;
  const focus = placed.branch === "focus";
  const path = getArtefactPath(node.type, node.project_id ?? projectId, node.id);
  const statusLabel = getArtefactStatusLabel(node.type, node.status);
  const elsewhere = node.project_id !== null && node.project_id !== projectId;
  const kind = clip(statusLabel ? `${node.type_label} · ${statusLabel}` : node.type_label, 26);
  const tooltip = [node.label, node.type_label, statusLabel, elsewhere ? node.project_name : null].filter(Boolean).join(" · ");
  const classes = [
    "link-trace__node",
    `link-trace__node--${placed.branch}`,
    node.is_archived && "link-trace__node--archived",
    elsewhere && "link-trace__node--elsewhere",
  ].filter(Boolean).join(" ");
  const chipX = x + (MAP_NODE_W - CHIP_W) / 2;
  const chipY = y + MAP_NODE_H - CHIP_H / 2;

  const body = (
    <>
      <title>{tooltip}</title>
      {focus && <rect className="link-trace__node-ring" x={x - 4} y={y - 4} width={MAP_NODE_W + 8} height={MAP_NODE_H + 8} rx={9} />}
      <rect className="link-trace__node-box" x={x} y={y} width={MAP_NODE_W} height={MAP_NODE_H} rx={6} />
      {!focus && <path className="link-trace__node-bar" d={`M ${x + 6} ${y} A 6 6 0 0 0 ${x} ${y + 6} L ${x} ${y + MAP_NODE_H - 6} A 6 6 0 0 0 ${x + 6} ${y + MAP_NODE_H} Z`} />}
      <text className="link-trace__node-kind" x={x + MAP_NODE_PAD_X} y={y + 19}>{kind}</text>
      {wrapLabel(node.label).map((line, i) => (
        <text key={i} className="link-trace__node-label" x={x + MAP_NODE_PAD_X} y={y + 37 + i * 14}>{line}</text>
      ))}
    </>
  );

  function onKey(e: KeyboardEvent<SVGGElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onExpand();
    }
  }

  return (
    <g
      className={classes}
      onMouseEnter={() => onActive(placed.key)}
      onMouseLeave={() => onActive(null)}
      onFocus={() => onActive(placed.key)}
      onBlur={() => onActive(null)}
    >
      {path ? <Link to={path} aria-label={tooltip}>{body}</Link> : <g>{body}</g>}
      {canExpand && (
        <g
          className={`link-trace__expand ${busy ? "link-trace__expand--pending" : ""}`}
          role="button"
          tabIndex={0}
          aria-label={strings.artefactLinks.traceMapShowMore(node.label)}
          aria-disabled={busy}
          onClick={onExpand}
          onKeyDown={onKey}
        >
          <title>{strings.artefactLinks.traceMapShowMoreTip}</title>
          <ChipFace x={chipX} y={chipY} pending={busy} label={busy ? strings.artefactLinks.traceMapLoadingMore : strings.artefactLinks.traceMapShowMoreChip} />
        </g>
      )}
      {exhausted && (
        <g className="link-trace__exhausted" aria-hidden="true">
          <rect x={chipX} y={chipY} width={CHIP_W} height={CHIP_H} rx={CHIP_H / 2} />
          <text x={chipX + CHIP_W / 2} y={chipY + CHIP_H / 2} textAnchor="middle" dominantBaseline="central">{strings.artefactLinks.traceMapNoMore}</text>
        </g>
      )}
    </g>
  );
}
