/**
 * Module: components/LinkTraceTree
 *
 * The trace tree of one record's links, split into Upstream (where it comes
 * from), Downstream (what depends on it) and Related (no direction), each
 * branch expandable as deep as the user wants.
 *
 * Responsibilities:
 * - Read the depth-1 link graph of the record, then of each branch the user opens
 *   (lazy: nothing beyond what is open is fetched).
 * - Keep a branch's direction: an upstream branch continues only through upstream
 *   edges, so it never doubles back through where it came from.
 * - Skip a record already on the path to it, so a cycle ends instead of repeating.
 *
 * Design decisions:
 * - There is no depth limit in the UI. The server caps one read at a few hops, so each
 *   expansion is its own one-hop read rooted at the opened record; that re-rooting is
 *   what makes the depth unbounded. Records the user cannot see are counted by the
 *   server and never traced through.
 * - Keyboard access is native: each branch is a real button (`aria-expanded`) and each
 *   record a real link, reachable with Tab, so no custom arrow-key widget is needed.
 * - API calls are injectable (`api`) so stories need no network.
 */
import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import { artefactLinksApi, type ArtefactLinksApi, type LinkGraph, type LinkGraphFlow } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { LinkedRecordSummary } from "./LinkedRecordSummary";
import { mostLinksUndirected, nodeKey, type TraceHop } from "./linkTrace";
import { bridgedHops, inactiveFilter } from "./linkTraceBridge";
import { Spinner } from "./Spinner";
import { useLinkGraph } from "./useLinkGraph";

const FLOWS: LinkGraphFlow[] = ["upstream", "downstream", "related"];

export function LinkTraceTree({
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
  const { graph, failed } = useLinkGraph(api, projectId, artefactType, artefactId);
  const rootKey = nodeKey(artefactType, artefactId);
  const [resolved, setResolved] = useState<{ hide: boolean; groups: Record<LinkGraphFlow, TraceHop[]> } | { hide: boolean; failed: true } | null>(null);

  useEffect(() => {
    if (!graph) return;
    let active = true;
    const isHidden = inactiveFilter(hideInactive);
    Promise.all(FLOWS.map((flow) => bridgedHops(api, projectId, graph, artefactType, artefactId, flow, isHidden, [rootKey])))
      .then(([upstream, downstream, related]) => {
        if (active) setResolved({ hide: hideInactive, groups: { upstream, downstream, related } });
      })
      .catch(() => {
        if (active) setResolved({ hide: hideInactive, failed: true });
      });
    return () => {
      active = false;
    };
  }, [api, projectId, graph, artefactType, artefactId, rootKey, hideInactive]);

  if (failed || (resolved && "failed" in resolved && resolved.hide === hideInactive)) {
    return <p className="text-muted">{strings.artefactLinks.loadError}</p>;
  }
  if (!graph || !resolved || "failed" in resolved || resolved.hide !== hideInactive) {
    return <Spinner label={strings.artefactLinks.traceLoading} />;
  }

  const labels: Record<LinkGraphFlow, { title: string; help: string }> = {
    upstream: { title: strings.artefactLinks.traceUpstream, help: strings.artefactLinks.traceUpstreamHelp },
    downstream: { title: strings.artefactLinks.traceDownstream, help: strings.artefactLinks.traceDownstreamHelp },
    related: { title: strings.artefactLinks.traceRelated, help: strings.artefactLinks.traceRelatedHelp },
  };
  const rootPath = [rootKey];
  return (
    <div className="stack link-trace">
      <p className="text-muted link-trace__hint">{strings.artefactLinks.traceTreeHint}</p>
      {mostLinksUndirected(graph) && <p className="link-trace__callout">{strings.artefactLinks.traceUnclassifiedHint}</p>}
      {FLOWS.map((flow) => {
        const hops = resolved.groups[flow];
        const headingId = `link-trace-${flow}`;
        return (
          <section key={flow} aria-labelledby={headingId} className="stack" style={{ gap: "var(--space-2)" }}>
            <h3 id={headingId} className="artefact-links__group">
              {labels[flow].title} <span className="text-muted">· {labels[flow].help}</span>
            </h3>
            {hops.length === 0 ? (
              <p className="text-muted link-trace__none">{strings.artefactLinks.traceEmptyGroup}</p>
            ) : (
              <BranchList hops={hops} flow={flow} projectId={projectId} api={api} path={rootPath} hide={hideInactive} />
            )}
          </section>
        );
      })}
      <TraceNotes graph={graph} />
    </div>
  );
}

/** The notes about what the server left out of a read. */
function TraceNotes({ graph }: { graph: LinkGraph }) {
  const strings = useStrings();
  return (
    <>
      {graph.hidden_count > 0 && <p className="text-muted artefact-links__note">{strings.artefactLinks.traceHiddenNote}</p>}
      {graph.truncated && <p className="text-muted artefact-links__note">{strings.artefactLinks.traceTruncatedNote}</p>}
    </>
  );
}

function BranchList({
  hops,
  flow,
  projectId,
  api,
  path,
  hide,
}: {
  hops: TraceHop[];
  flow: LinkGraphFlow;
  projectId: string;
  api: ArtefactLinksApi;
  /** Keys of the records between the root and this list, so none is repeated below itself. */
  path: string[];
  hide: boolean;
}) {
  return (
    <ul className="link-trace__list">
      {hops.map((hop) => (
        <BranchNode key={hop.edge.id} hop={hop} flow={flow} projectId={projectId} api={api} path={path} hide={hide} />
      ))}
    </ul>
  );
}

type Branch = { state: "idle" } | { state: "loading" } | { state: "failed" } | { state: "loaded"; graph: LinkGraph; hops: TraceHop[] };

/** One record in the tree; opening it reads its own links and continues in `flow`'s direction. */
function BranchNode({
  hop,
  flow,
  projectId,
  api,
  path,
  hide,
}: {
  hop: TraceHop;
  flow: LinkGraphFlow;
  projectId: string;
  api: ArtefactLinksApi;
  path: string[];
  hide: boolean;
}) {
  const strings = useStrings();
  const { node, edge } = hop;
  const key = nodeKey(node.type, node.id);
  const [open, setOpen] = useState(false);
  const [branch, setBranch] = useState<Branch>({ state: "idle" });
  const childPath = [...path, key];

  async function toggle() {
    const opening = !open;
    setOpen(opening);
    if (!opening || branch.state === "loaded" || branch.state === "loading") return;
    setBranch({ state: "loading" });
    try {
      const graph = await api.graph(projectId, node.type, node.id);
      const hops = await bridgedHops(api, projectId, graph, node.type, node.id, flow, inactiveFilter(hide), childPath);
      setBranch({ state: "loaded", graph, hops });
    } catch {
      setBranch({ state: "failed" });
    }
  }

  return (
    <li className="link-trace__item">
      <div className="artefact-links__summary" data-wrap-ok>
        <button
          type="button"
          className="link-trace__toggle"
          aria-expanded={open}
          aria-label={open ? strings.artefactLinks.traceCollapse(node.label) : strings.artefactLinks.traceExpand(node.label)}
          onClick={() => void toggle()}
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <LinkedRecordSummary edge={edge} node={node} currentProjectId={projectId} via={hop.via} />
      </div>
      {open && (
        <div className="link-trace__children">
          {branch.state === "loading" && <Spinner label={strings.artefactLinks.traceLoading} />}
          {branch.state === "failed" && <p className="text-muted link-trace__none">{strings.artefactLinks.traceLoadFailed}</p>}
          {branch.state === "loaded" && (
            <>
              {branch.hops.length === 0 ? (
                <p className="text-muted link-trace__none">{strings.artefactLinks.traceNothingFurther}</p>
              ) : (
                <BranchList hops={branch.hops} flow={flow} projectId={projectId} api={api} path={childPath} hide={hide} />
              )}
              <TraceNotes graph={branch.graph} />
            </>
          )}
        </div>
      )}
    </li>
  );
}
