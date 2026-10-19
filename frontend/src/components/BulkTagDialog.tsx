/**
 * Module: components/BulkTagDialog
 *
 * Adds and removes tags on the records selected in a list, in one previewed step: the list's
 * bulk toolbar opens it with the chosen record ids. It reuses the reclassify call (`records`
 * form), so the server applies the usual rules: tag authority for each record, the project's own
 * vocabulary, all or nothing, one audit event per changed record.
 *
 * Only tags the project owns are offered; a project that follows a parent's list has none to pick
 * here, because the parent manages that list (the dialog says so).
 */
import { useCallback, useState } from "react";

import type { ReclassifyResult, TagAdminApi, TagVocabulary } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { FilterField } from "./FilterPanel";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { Spinner } from "./Spinner";

/**
 * @param api The project's tag admin calls (`projectTagAdminApi`).
 * @param artefactType The registered type of the selected records.
 * @param ids The selected records' ids.
 * @param title Dialog title ("Tag 3 selected requirements").
 * @param onClose Called to dismiss without changing anything.
 * @param onApplied Called with the result after the change was written.
 */
export function BulkTagDialog({
  api, artefactType, ids, title, onClose, onApplied,
}: {
  api: TagAdminApi;
  artefactType: string;
  ids: string[];
  title: string;
  onClose: () => void;
  onApplied: (result: ReclassifyResult) => void | Promise<void>;
}) {
  const strings = useStrings();
  const text = strings.tags.admin;
  const [vocabulary, setVocabulary] = useState<TagVocabulary | null>(null);
  const [add, setAdd] = useState<string[]>([]);
  const [remove, setRemove] = useState<string[]>([]);
  const [forecast, setForecast] = useState<ReclassifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setVocabulary(await api.vocabulary());
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    }
  }, [api, strings.common.error]);
  useLoadOnChange(load, [api]);

  const records = ids.map((artefact_id) => ({ artefact_type: artefactType, artefact_id }));
  const request = (dryRun: boolean) => ({ records, add, remove, dry_run: dryRun });

  async function run(dryRun: boolean) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.reclassify(request(dryRun));
      if (dryRun) setForecast(result);
      else await onApplied(result);
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  const choices = (selected: string[], set: (ids: string[]) => void, label: string) => (
    <MultiSelectDropdown
      triggerLabel={label}
      emptyLabel={strings.tags.filter.choose}
      options={(vocabulary?.tags ?? []).filter((t) => t.editable).map((t) => {
        const checked = selected.includes(t.id);
        return {
          value: t.id, label: t.name, checked, optionLabel: t.name,
          onToggle: () => {
            set(checked ? selected.filter((id) => id !== t.id) : [...selected, t.id]);
            setForecast(null);
          },
        };
      })}
    />
  );
  const nothingChosen = add.length === 0 && remove.length === 0;
  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        {!vocabulary && !error && <Spinner />}
        {vocabulary?.inherited && <p className="text-muted" style={{ margin: 0 }}>{text.inheritedNotice}</p>}
        {vocabulary && (
          <>
            <FilterField label={text.reclassifyAdd}>{choices(add, setAdd, text.reclassifyAdd)}</FilterField>
            <FilterField label={text.reclassifyRemove}>{choices(remove, setRemove, text.reclassifyRemove)}</FilterField>
          </>
        )}
        {vocabulary && nothingChosen && <p className="text-muted" style={{ margin: 0 }}>{text.reclassifyNothing}</p>}
        {forecast && <p role="status" style={{ margin: 0 }}>{text.reclassifyForecast(forecast.matched, forecast.added, forecast.removed)}</p>}
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={() => void run(false)}
          saveLabel={text.reclassifyApply}
          saveDisabled={busy || nothingChosen || !forecast}
        >
          <button type="button" className="btn" disabled={busy || nothingChosen} onClick={() => void run(true)}>
            {text.reclassifyPreview}
          </button>
        </FormActions>
      </div>
    </Modal>
  );
}
