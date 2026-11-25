/**
 * Module: components/ResourcePickerModal
 *
 * Style guide "Pattern: resource picker dialog": a two-pane `Modal` with a source list on the left and the selected
 * source's files on the right, pickable and attachable to whatever opened the dialog.
 *
 * Design decisions: sources are pluggable through the `sources` prop (`ResourcePickerSource[]`: id, label,
 * `loadFiles()`), so a caller adds a source without changing this component. Selection is multi-file (a checkbox per row)
 * with one "Attach selected" action, matching the shared-resource picker on `ChangeRequestsPage.tsx` and avoiding one
 * round trip per file. `onAttach` receives all selected file ids and decides how to apply them.
 */
import { FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";

import type { FileAsset } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";
import { FormActions } from "./FormActions";
import { CheckboxField } from "./FormFields";
import { useResetOnChange } from "../hooks/useResetOnChange";

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

  useResetOnChange([activeSourceId], () => {
    setFiles(null);
    setSelected(new Set());
  });

  useEffect(() => {
    if (!activeSource) return;
    let cancelled = false;
    activeSource.loadFiles().then((loaded) => {
      if (!cancelled) setFiles(loaded);
    });
    return () => {
      cancelled = true;
    };
    // Re-runs only when the resolved source changes, i.e. when `activeSourceId` picks a different entry.
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
      <div className="row" style={{ alignItems: "stretch", gap: "var(--space-5)" }}>
        <div
          className="stack"
          style={{ minWidth: 200, flexShrink: 0, borderRight: "1px solid var(--color-border)", paddingRight: "var(--space-5)" }}
        >
          {sources.map((s) => (
            <button
              key={s.id}
              className={`btn${s.id === activeSourceId ? " btn-primary" : ""}`}
              style={{ justifyContent: "flex-start" }}
              onClick={() => setActiveSourceId(s.id)}
              aria-pressed={s.id === activeSourceId}
            >
              <FolderOpen /> {s.label}
            </button>
          ))}
        </div>
        <div className="stack" style={{ flex: 1, minWidth: 0 }}>
          {!files && <Spinner />}
          {files && files.length === 0 && (
            <p className="text-muted" style={{ margin: 0 }}>{strings.resourcePicker.noFiles}</p>
          )}
          {files && files.length > 0 && (
            <div className="stack scroll-region" style={{ maxHeight: "50vh" }}>
              {files.map((f) => (
                <CheckboxField helpNotNeeded key={f.id} label={f.filename} checked={selected.has(f.id)} onChange={() => toggle(f.id)} />
              ))}
            </div>
          )}
          <div className="stack" style={{ marginTop: "auto" }}>
            <FormActions
              error={error}
              onCancel={onClose}
              onSave={handleAttach}
              saveLabel={strings.resourcePicker.attachSelected(selected.size)}
              saveDisabled={selected.size === 0 || attaching}
            />
          </div>
        </div>
      </div>
    </Modal>
  );
}
