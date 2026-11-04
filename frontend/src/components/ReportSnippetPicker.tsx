/**
 * Module: components/ReportSnippetPicker
 *
 * The dialog that inserts a report snippet (a named fragment of a layout: a cover page, a logo, record images) into the
 * layout being edited, from the Blocks view and from the Text view.
 *
 * Responsibilities:
 * - List the snippets the scope offers with a search box and a category filter (the last category is remembered per
 *   person); a snippet for the other layout family is shown disabled with the reason, not hidden.
 * - Show the selected snippet: what it adds, the output formats it is true in, an outline of its blocks, and a form
 *   for its parameters (a library picture, a record type, a short text) built from the snippet's own schema with the
 *   shared field components.
 * - Say where it will land (the caller's stated place, or a choice between the places the caller offers) and ask the
 *   server to apply it to the draft tree; a refusal is shown with its reasons and the dialog stays open.
 *
 * Design decisions: the server builds and validates the result (`ReportLayoutApi.applySnippet`), so both views get the
 * same tree and the dialog holds no tree rules; the caller places the result in its own view. The fragment is drawn as
 * an outline of block names, not a rendered sample, because a sample would mean running a report. Selecting a snippet
 * and pressing Insert is one step even when it has no parameters, so nothing is inserted by a stray click.
 */
import { useEffect, useMemo, useState } from "react";

import {
  LAYOUT_FAMILY_LABEL, LAYOUT_ORIGIN_LABEL, SNIPPET_FORMAT_LABEL, type BlockType, type LayoutFamily, type ReportImageLibrary, type ReportLayoutApi, type ReportSnippet,
  type SnippetApplyResult, type SnippetParameter,
} from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useUiPreference } from "../hooks/useUiPreference";
import type { Tree } from "../utils/reportLayoutTree";
import { filterSnippets, initialValues, missingParameters, outlineLines, snippetCategories, suitsFamily } from "../utils/reportSnippets";
import { Badge } from "./Badge";
import { FormActions } from "./FormActions";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { ReportImageField } from "./ReportImageField";
import { Spinner } from "./Spinner";

/** A place a snippet can go: a list of blocks of the tree, the position in it (`null`: the end) and the words that say so. */
export interface SnippetPlace {
  container: string;
  index: number | null;
  label: string;
}

/** A snippet parameter as a form field. */
function ParameterField({
  parameter, value, onChange, images,
}: {
  parameter: SnippetParameter;
  value: string;
  onChange: (value: string) => void;
  images: { library: ReportImageLibrary; scope: "organization" | "project" };
}) {
  const text = useStrings().reportSnippets;
  if (parameter.kind === "image") {
    return (
      <ReportImageField
        label={parameter.label} value={value} library={images.library} scope={images.scope} onChange={onChange}
        help={parameter.help} required={parameter.required}
      />
    );
  }
  if (parameter.kind === "record_type") {
    return (
      <LabeledSelect
        label={parameter.label} value={value} onChange={onChange} help={parameter.help} required={parameter.required}
        placeholder={text.choose} options={parameter.choices}
      />
    );
  }
  return (
    <TextField
      label={parameter.label} value={value} onChange={onChange} help={parameter.help} required={parameter.required}
      placeholder={parameter.default ?? undefined} inputProps={{ maxLength: parameter.max_length ?? undefined }}
    />
  );
}

/**
 * @param api The snippet calls (the layout API's, so a story supplies a few snippets).
 * @param family The open layout's family; a snippet for the other one is disabled.
 * @param blockTypes The block catalogue, for the outline's block names.
 * @param tree The draft tree the snippet is applied to (as it stands when the dialog opens).
 * @param places Where the snippet can go; one place is stated, several are chosen between.
 * @param images The picture library an image parameter chooses from, and the scope an upload goes to.
 * @param onClose Called by Cancel.
 * @param onInserted Called with the applied result and the snippet; the caller puts the result in its view and closes.
 */
export function ReportSnippetPicker({
  api, family, blockTypes, tree, places, images, onClose, onInserted,
}: {
  api: Pick<ReportLayoutApi, "snippets" | "applySnippet">;
  family: LayoutFamily;
  blockTypes: readonly BlockType[];
  tree: Tree;
  places: SnippetPlace[];
  images: { library: ReportImageLibrary; scope: "organization" | "project" };
  onClose: () => void;
  onInserted: (result: SnippetApplyResult, snippet: ReportSnippet) => void;
}) {
  const text = useStrings().reportSnippets;
  const [snippets, setSnippets] = useState<ReportSnippet[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [remembered, setRemembered] = useUiPreference<string>("report_snippet_category", "");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [placeIndex, setPlaceIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    api.snippets().then(
      (found) => { if (!cancelled) setSnippets(found); },
      () => { if (!cancelled) setLoadFailed(true); },
    );
    return () => { cancelled = true; };
  }, [api]);

  const categories = useMemo(() => snippetCategories(snippets ?? []), [snippets]);
  // A category the scope no longer offers (remembered from another layout) shows everything.
  const category = categories.includes(remembered) ? remembered : "";
  const shown = useMemo(() => filterSnippets(snippets ?? [], search, category), [snippets, search, category]);
  const selected = snippets?.find((s) => s.key === selectedKey) ?? null;
  const place = places[Math.min(placeIndex, places.length - 1)];
  const suits = selected !== null && suitsFamily(selected, family);
  const missing = selected ? missingParameters(selected, values) : [];

  function choose(snippet: ReportSnippet) {
    setSelectedKey(snippet.key);
    setValues(initialValues(snippet));
    setErrors([]);
  }

  async function insert() {
    if (!selected || !place) return;
    setBusy(true);
    setErrors([]);
    try {
      const given = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== "").map(([k, v]) => [k, v.trim()]));
      const result = await api.applySnippet(selected.key, { tree, parameters: given, target: { container: place.container, index: place.index } });
      if (result.ok) onInserted(result, selected);
      else setErrors(result.errors.map((e) => e.message));
    } catch (err) {
      setErrors([toErrorMessage(err, text.insertFailed)]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={text.title} size="lg" onClose={onClose}>
      <FormActions
        saveLabel={text.insert} onSave={() => void insert()} onCancel={onClose} cancelDisabled={busy}
        saveDisabled={busy || !suits || missing.length > 0 || !place}
      />
      {loadFailed ? (
        <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{text.loadFailed}</p>
      ) : snippets === null ? (
        <Spinner />
      ) : snippets.length === 0 ? (
        <p className="text-muted" style={{ margin: 0 }}>{text.none}</p>
      ) : (
        <div className="snippet-picker">
          <div className="stack snippet-list">
            <TextField label={text.searchLabel} helpNotNeeded value={search} onChange={setSearch} inputProps={{ type: "search" }} />
            <LabeledSelect
              label={text.categoryLabel} helpNotNeeded value={category} onChange={setRemembered} placeholder={text.allCategories}
              options={categories.map((c) => ({ value: c, label: c }))}
            />
            {shown.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{text.noMatches}</p>}
            <ul className="snippet-rows" aria-label={text.listLabel}>
              {shown.map((snippet) => {
                const fits = suitsFamily(snippet, family);
                return (
                  <li key={snippet.key}>
                    <button
                      type="button" className="snippet-row" aria-pressed={snippet.key === selectedKey} disabled={!fits}
                      aria-label={text.selectLabel(snippet.name)} onClick={() => choose(snippet)}
                    >
                      <strong>{snippet.name}</strong>
                      <span className="text-muted">{snippet.description}</span>
                      {snippet.saved_id && snippet.origin && <span className="text-muted">{text.savedBadge(LAYOUT_ORIGIN_LABEL[snippet.origin])}</span>}
                      {!fits && <span className="text-muted">{text.wrongFamily(LAYOUT_FAMILY_LABEL[snippet.family].toLowerCase(), LAYOUT_FAMILY_LABEL[family].toLowerCase())}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="stack snippet-detail" aria-label={text.detailLabel} role="region">
            {selected === null ? (
              <p className="text-muted" style={{ margin: 0 }}>{text.selectPrompt}</p>
            ) : (
              <>
                <strong>{selected.name}</strong>
                <p style={{ margin: 0 }}>{selected.description}</p>
                <div className="row" aria-label={text.formatsLabel} role="group">
                  <span className="text-muted">{text.worksIn}</span>
                  {selected.formats.map((format) => <Badge key={format}>{SNIPPET_FORMAT_LABEL[format]}</Badge>)}
                </div>
                <div>
                  <strong>{text.outlineTitle}</strong>
                  <ul className="snippet-outline" aria-label={text.outlineLabel(selected.name)}>
                    {outlineLines(selected.blocks, blockTypes).map((line, index) => (
                      <li key={index} style={{ paddingLeft: `calc(${line.depth} * var(--space-4))` }}>{line.label}</li>
                    ))}
                  </ul>
                </div>
                {selected.parameters.map((parameter) => (
                  <ParameterField
                    key={parameter.key} parameter={parameter} value={values[parameter.key] ?? ""} images={images}
                    onChange={(next) => setValues((current) => ({ ...current, [parameter.key]: next }))}
                  />
                ))}
                {places.length > 1 ? (
                  <LabeledSelect
                    label={text.whereLabel} helpNotNeeded value={String(placeIndex)} placeholder={null} onChange={(v) => setPlaceIndex(Number(v))}
                    options={places.map((p, index) => ({ value: String(index), label: p.label }))}
                  />
                ) : (
                  place && <p className="text-muted" role="status" style={{ margin: 0 }}>{place.label}</p>
                )}
              </>
            )}
            {errors.length > 0 && (
              <ul className="outline-field-problems" role="alert">{errors.map((message, index) => <li key={index}>{message}</li>)}</ul>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
