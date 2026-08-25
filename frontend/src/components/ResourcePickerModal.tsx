/**
 * Module: components/ResourcePickerModal
 *
 * Style guide "Pattern: resource picker dialog" (2026-08 UX audit roadmap
 * row 508, "Shared org resources have almost no way to consume them"): a
 * two-pane `Modal` — a source list on the left, the selected source's
 * files on the right, pickable and attachable to whatever opened the
 * dialog.
 *
 * Built pluggable via the `sources` prop (`ResourcePickerSource[]`, each
 * just an id/label/`loadFiles()`) rather than hardcoded to "organisation
 * shared resources" specifically, so a future source (a project's own
 * uploaded files, a report chapter's existing image pool) can be added by
 * a caller without a rewrite of this component — today only one source is
 * wired up (`RequirementDetailPage.tsx`'s Attachments card), per this
 * pass's scope, but the shape doesn't assume there's only ever one.
 *
 * Selection is multi-file (a checkbox per row) with one "Attach selected"
 * action at the end, rather than attaching on click-per-row — this matches
 * the existing shared-resource checkbox picker on `ChangeRequestsPage.tsx`
 * (proposed-attachment selection) more closely than a single-click-and-
 * close flow would, and avoids a chain of individual network round trips
 * each closing/reopening the dialog. The caller's `onAttach` receives the
 * full set of selected file ids and decides how to apply them (e.g. one
 * `POST .../files/link` call per id).
 */
import { FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";

import type { FileAsset } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

export interface ResourcePickerSource {
  id: string;
  label: string;
  loadFiles: () => Promise<FileAsset[]>;
}

export function ResourcePickerModal({
  title,
  sources,
  onClose,
  onAttach,
}: {
  title: string;
  sources: ResourcePickerSource[];
  onClose: () => void;
  /** Called with the selected file ids when "Attach selected" is pressed.
   * The dialog closes automatically once this resolves; a thrown/rejected
   * error is shown inline instead, and the dialog stays open. */
  onAttach: (fileIds: string[]) => Promise<void>;
}) {
  const strings = useStrings();
  const [activeSourceId, setActiveSourceId] = useState(sources[0]?.id ?? "");
  const [files, setFiles] = useState<FileAsset[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [attaching, setAttaching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeSource = sources.find((s) => s.id === activeSourceId) ?? null;

  useEffect(() => {
    setFiles(null);
    setSelected(new Set());
    if (!activeSource) return;
    let cancelled = false;
    activeSource.loadFiles().then((loaded) => {
      if (!cancelled) setFiles(loaded);
    });
    return () => {
      cancelled = true;
    };
    // `activeSource` is derived from `sources`/`activeSourceId` each render;
    // re-running whenever the resolved source object changes (i.e. whenever
    // `activeSourceId` actually picks a different entry) is what we want.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSourceId]);

  function toggle(fileId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  }

  async function handleAttach() {
    setError(null);
    setAttaching(true);
    try {
      await onAttach(Array.from(selected));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    } finally {
      setAttaching(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose} size="lg">
      <div className="row" style={{ alignItems: "stretch", gap: "1rem" }}>
        <div
          className="stack"
          style={{ minWidth: 200, flexShrink: 0, borderRight: "1px solid var(--color-border)", paddingRight: "1rem" }}
        >
          {sources.map((s) => (
            <button
              key={s.id}
              className={`btn${s.id === activeSourceId ? " btn-primary" : ""}`}
              style={{ justifyContent: "flex-start" }}
              onClick={() => setActiveSourceId(s.id)}
              aria-pressed={s.id === activeSourceId}
            >
              <FolderOpen size={14} /> {s.label}
            </button>
          ))}
        </div>
        <div className="stack" style={{ flex: 1, minWidth: 0 }}>
          {!files && <Spinner />}
          {files && files.length === 0 && (
            <p className="text-muted" style={{ margin: 0 }}>{strings.resourcePicker.noFiles}</p>
          )}
          {files && files.length > 0 && (
            <div className="stack" style={{ maxHeight: "50vh", overflowY: "auto" }}>
              {files.map((f) => (
                <label key={f.id} className="row">
                  <input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} />
                  {f.filename}
                </label>
              ))}
            </div>
          )}
          {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
          <div className="row" style={{ justifyContent: "flex-end", marginTop: "auto" }}>
            <button className="btn" onClick={onClose}>{strings.common.cancel}</button>
            <button className="btn btn-primary" onClick={handleAttach} disabled={selected.size === 0 || attaching}>
              {strings.resourcePicker.attachSelected(selected.size)}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
