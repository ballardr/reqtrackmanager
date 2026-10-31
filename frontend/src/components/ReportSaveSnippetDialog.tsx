/**
 * Module: components/ReportSaveSnippetDialog
 *
 * The dialog that saves a selection of the layout being edited (a block with everything inside it, or a run of top-level
 * blocks) as a reusable snippet for the project or the organisation.
 *
 * Responsibilities:
 * - Ask the server what saving the selection would store as the level changes (`ReportSnippetStoreApi.check`): how many
 *   blocks, the page styles and variables it carries, or the reasons it cannot be saved (it needs something defined outside
 *   the selection; a project picture cannot go to the organisation, and is named).
 * - Collect the name (required), description and category (suggesting those already in use), save, and hand the saved
 *   snippet to the caller.
 *
 * Design decisions: the server decides every rule (names, pictures, permissions, what a selection needs), so the check
 * and the save cannot disagree; a person without the organisation's right sees the server's refusal when they choose that
 * level, not a guess made here. A saved snippet has no parameters in this version; changing its blocks later is the
 * snippet editor's job (`ReportSnippetEditorDialog`). Follows the form header pattern (`FormActions` in the dialog header) and
 * the required-field and field-help patterns.
 */
import { useEffect, useRef, useState } from "react";

import { treeProblems, type ReportLayoutTree } from "../api/reportLayouts";
import {
  SNIPPET_LEVEL_LABEL, type ReportSnippetStoreApi, type SavedSnippet, type SnippetCheck, type SnippetLevel, type SnippetSelection,
} from "../api/reportSnippets";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { ApiError } from "../api/client";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { ReportSnippetCheckSummary } from "./ReportSnippetCheckSummary";
import { ReportSnippetFields } from "./ReportSnippetFields";

const CHECK_DELAY_MS = 150;

/**
 * @param api The calls, bound to the organisation or project the layout belongs to.
 * @param tree The draft layout tree the selection is taken from.
 * @param selection The blocks to save.
 * @param selectionLabel Words naming the selection ("Saving Heading – Requirements.").
 * @param onClose Called by Cancel.
 * @param onSaved Called with the saved snippet after the toast; the caller closes the dialog.
 */
export function ReportSaveSnippetDialog({
  api, tree, selection, selectionLabel, onClose, onSaved,
}: {
  api: ReportSnippetStoreApi;
  tree: ReportLayoutTree;
  selection: SnippetSelection;
  selectionLabel: string;
  onClose: () => void;
  onSaved: (saved: SavedSnippet) => void;
}) {
  const strings = useStrings();
  const text = strings.reportSnippetSave;
  const { showToast } = useToast();
  const inProject = api.scope.kind === "project";
  const [level, setLevel] = useState<SnippetLevel>(inProject ? "project" : "organization");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  /** The latest check and the level it was for, so a check for another level is not shown. */
  const [checked, setChecked] = useState<{ level: SnippetLevel; result: SnippetCheck } | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const latest = useRef(0);

  // The categories already in use are only suggestions, so a failed load is not worth reporting.
  useEffect(() => {
    let cancelled = false;
    api.list().then(
      (found) => { if (!cancelled) setCategories([...new Set(found.map((s) => s.category))]); },
      () => undefined,
    );
    return () => { cancelled = true; };
  }, [api]);

  useEffect(() => {
    const ticket = ++latest.current;
    const timer = window.setTimeout(() => {
      api.check(tree, selection, level).then(
        (found) => { if (ticket === latest.current) { setChecked({ level, result: found }); setCheckError(null); } },
        (err) => { if (ticket === latest.current) setCheckError(toErrorMessage(err, text.checkFailed)); },
      );
    }, CHECK_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [api, tree, selection, level, text.checkFailed]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.save({ name: name.trim(), description: description.trim(), category: category.trim(), tree, selection }, level);
      showToast(text.saved(saved.name));
      onSaved(saved);
    } catch (err) {
      const reasons = treeProblems(err).map((p) => p.message);
      setError(err instanceof ApiError && err.status === 409 ? text.nameTaken : reasons.length > 0 ? reasons.join(" ") : toErrorMessage(err, text.failed));
    } finally {
      setBusy(false);
    }
  }

  const check = checked?.level === level ? checked.result : null;
  const canSave = !busy && name.trim() !== "" && check?.ok === true;
  return (
    <Modal title={text.title} onClose={onClose}>
      <div className="stack">
        <FormActions
          error={error} onCancel={onClose} onSave={() => void save()} saveLabel={busy ? text.saving : text.saveButton}
          saveDisabled={!canSave} cancelDisabled={busy}
        />
        <p className="text-muted" style={{ margin: 0 }}>{selectionLabel}</p>
        {inProject && (
          <LabeledSelect
            label={text.levelLabel} help={strings.help.reportSnippetLevel} value={level} placeholder={null}
            onChange={(value: string) => setLevel(value as SnippetLevel)}
            options={(Object.keys(SNIPPET_LEVEL_LABEL) as SnippetLevel[]).map((key) => ({ value: key, label: SNIPPET_LEVEL_LABEL[key] }))}
          />
        )}
        <ReportSnippetFields
          name={name} description={description} category={category} categories={categories}
          onName={setName} onDescription={setDescription} onCategory={setCategory}
        />
        <ReportSnippetCheckSummary check={check} error={checkError} />
      </div>
    </Modal>
  );
}
