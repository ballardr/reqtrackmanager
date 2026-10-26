/**
 * Module: components/ReportLayoutHistory
 *
 * The designer's History tab: every saved version of a layout and a line-by-line comparison of any two.
 *
 * Responsibilities:
 * - List versions newest first with their note and time.
 * - Compare two versions through their text views (`ReportLayoutApi.formatTree`, so the comparison reads the way
 *   the author writes), marking added and removed lines with a sign as well as a colour.
 * - For an editable layout, put an old version's text in the editor (`onUseVersion`); nothing is saved until the
 *   author saves, which creates a new version, so history is never rewritten.
 *
 * Design decisions: the diff is computed in the browser (`utils/reportLayoutText.diffLines`) from two ordinary
 * reads, so no comparison endpoint is needed; versions are immutable, so a loaded text is cached by number.
 */
import { useCallback, useRef, useState } from "react";

import type { ReportLayoutApi, ReportLayoutVersionSummary } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { diffLines, type DiffLine } from "../utils/reportLayoutText";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { LabeledSelect } from "./LabeledSelect";
import { Spinner } from "./Spinner";

/**
 * @param api The calls, bound to the layout's scope.
 * @param layoutId The layout.
 * @param currentVersion The layout's latest version; a change reloads the list.
 * @param onUseVersion Puts a version's text in the editor; omit it for a read-only layout.
 */
export function ReportLayoutHistory({
  api, layoutId, currentVersion, onUseVersion,
}: {
  api: ReportLayoutApi;
  layoutId: string;
  currentVersion: number;
  onUseVersion?: (version: number, text: string) => void;
}) {
  const text = useStrings().reportLayouts;
  const [versions, setVersions] = useState<ReportLayoutVersionSummary[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [diff, setDiff] = useState<DiffLine[] | null>(null);
  const cache = useRef(new Map<number, string>());

  const textOf = useCallback(async (version: number): Promise<string> => {
    const cached = cache.current.get(version);
    if (cached !== undefined) return cached;
    const loaded = await api.version(layoutId, version);
    const written = await api.formatTree(loaded.tree);
    cache.current.set(version, written);
    return written;
  }, [api, layoutId]);

  const compare = useCallback(async (older: number, newer: number) => {
    try {
      const [a, b] = await Promise.all([textOf(older), textOf(newer)]);
      setDiff(diffLines(a, b));
      setFailed(null);
    } catch (err) {
      setFailed(toErrorMessage(err, text.historyLoadFailed));
    }
  }, [textOf, text.historyLoadFailed]);

  const load = useCallback(async () => {
    try {
      const list = await api.versions(layoutId);
      setVersions(list);
      const newer = list[0]?.version ?? null;
      const older = list[1]?.version ?? newer;
      setTo(newer);
      setFrom(older);
      if (older !== null && newer !== null) await compare(older, newer);
    } catch (err) {
      setFailed(toErrorMessage(err, text.historyLoadFailed));
    }
  }, [api, layoutId, compare, text.historyLoadFailed]);

  useLoadOnChange(load, [layoutId, currentVersion]);

  if (failed && !versions) return <p className="text-muted" role="alert">{failed}</p>;
  if (!versions) return <Spinner />;

  const options = versions.map((v) => ({ value: String(v.version), label: text.compareVersionLabel(v.version) }));

  async function chooseVersion(version: number) {
    try {
      onUseVersion?.(version, await textOf(version));
    } catch (err) {
      setFailed(toErrorMessage(err, text.historyLoadFailed));
    }
  }

  const columns: DirectoryColumn<ReportLayoutVersionSummary>[] = [
    {
      key: "version",
      label: text.historyListLabel,
      render: (v) => `${text.historyVersion(v.version)}${v.version === currentVersion ? ` (${text.historyCurrent})` : ""}`,
    },
    { key: "note", label: text.changeNoteLabel, render: (v) => v.comment || <span className="text-muted">{text.historyNoNote}</span> },
    { key: "when", label: text.updatedHeading, render: (v) => new Date(v.created_at).toLocaleString() },
    ...(onUseVersion
      ? [{
        key: "use",
        label: <span className="sr-only">{text.restoreVersion}</span>,
        render: (v: ReportLayoutVersionSummary) => v.version === currentVersion ? null : (
          <button type="button" className="btn btn-sm" aria-label={`${text.restoreVersion} (${text.historyVersion(v.version)})`} onClick={() => void chooseVersion(v.version)}>
            {text.restoreVersion}
          </button>
        ),
      }]
      : []),
  ];

  const changed = diff?.some((line) => line.kind !== "same") ?? false;

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.historyHint}</p>
      <DirectoryTable ariaLabel={text.historyListLabel} columns={columns} rows={versions} rowKey={(v) => String(v.version)} emptyState={null} />
      {versions.length > 1 && from !== null && to !== null && (
        <div className="row" style={{ alignItems: "flex-end" }}>
          <LabeledSelect helpNotNeeded label={text.compareFrom} value={String(from)} placeholder={null} options={options}
            onChange={(next) => { setFrom(Number(next)); void compare(Number(next), to); }} />
          <LabeledSelect helpNotNeeded label={text.compareTo} value={String(to)} placeholder={null} options={options}
            onChange={(next) => { setTo(Number(next)); void compare(from, Number(next)); }} />
        </div>
      )}
      {failed && <div role="alert" style={{ color: "var(--color-danger)" }}>{failed}</div>}
      {diff && !changed && <p className="text-muted">{text.compareIdentical}</p>}
      {diff && changed && (
        <pre className="layout-diff" aria-label={text.diffLabel}>
          {diff.map((line, index) => (
            <span key={index} className={`layout-diff-line${line.kind === "same" ? "" : ` layout-diff-line--${line.kind}`}`}>
              <span className="sr-only">{line.kind === "add" ? text.compareAdded : line.kind === "remove" ? text.compareRemoved : ""}</span>
              {line.kind === "add" ? "+ " : line.kind === "remove" ? "- " : "  "}
              {line.text}
            </span>
          ))}
        </pre>
      )}
    </div>
  );
}
