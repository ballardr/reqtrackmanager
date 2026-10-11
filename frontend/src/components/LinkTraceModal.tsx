/**
 * Module: components/LinkTraceModal
 *
 * The large dialog that traces one record's links, opened from the Links panel's
 * "Trace" button: a Tree tab (every branch expandable without limit) and a Map tab
 * (a scrollable layered diagram that grows as records are opened).
 *
 * Responsibilities:
 * - Host the shared `Tabs` over the two views (style guide: a `Modal` whose body is `Tabs`).
 * - Own the "Hide inactive records" switch, shared by both views, so the choice survives a tab change.
 * - Close when a record link inside is followed, so the dialog never lingers over the
 *   page it just navigated to.
 */
import { useState } from "react";

import { artefactLinksApi, type ArtefactLinksApi } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { LinkTraceMap } from "./LinkTraceMap";
import { LinkTraceTree } from "./LinkTraceTree";
import { Modal } from "./Modal";
import { Tabs, tabPanelProps } from "./Tabs";

type TraceView = "tree" | "map";

export function LinkTraceModal({
  projectId,
  artefactType,
  artefactId,
  rootLabel,
  onClose,
  api = artefactLinksApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  /** The traced record's label, for the dialog title. */
  rootLabel: string;
  onClose: () => void;
  api?: ArtefactLinksApi;
}) {
  const strings = useStrings();
  const [view, setView] = useState<TraceView>("tree");
  const [hideInactive, setHideInactive] = useState(false);
  return (
    <Modal title={strings.artefactLinks.traceTitle(rootLabel)} onClose={onClose} size="lg">
      {/* Following a record link navigates away, so the dialog closes with it. */}
      <div
        className="stack"
        onClickCapture={(e) => {
          if ((e.target as Element).closest("a")) onClose();
        }}
      >
        <Tabs
          idPrefix="link-trace"
          tabs={[
            { key: "tree", label: strings.artefactLinks.traceTabTree },
            { key: "map", label: strings.artefactLinks.traceTabMap },
          ]}
          active={view}
          onChange={setView}
        />
        <label className="row link-trace__filter" title={strings.artefactLinks.traceHideInactiveHelp}>
          <input type="checkbox" checked={hideInactive} onChange={(e) => setHideInactive(e.target.checked)} />
          {strings.artefactLinks.traceHideInactive}
        </label>
        <div {...tabPanelProps("link-trace", view)}>
          {view === "tree" ? (
            <LinkTraceTree projectId={projectId} artefactType={artefactType} artefactId={artefactId} hideInactive={hideInactive} api={api} />
          ) : (
            <LinkTraceMap projectId={projectId} artefactType={artefactType} artefactId={artefactId} hideInactive={hideInactive} api={api} />
          )}
        </div>
      </div>
    </Modal>
  );
}
