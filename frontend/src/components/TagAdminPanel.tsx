/**
 * Module: components/TagAdminPanel
 *
 * The tag administration surface, one component for a project (Project Admin) and for the
 * organisation (Org Admin, for organisation-owned records): who may add a new tag, the vocabulary
 * (add, rename, colour, merge, reclassify, delete) and, per tag, its usage by kind of record.
 *
 * Responsibilities:
 * - Show and set the mode: free, restricted, and for a project "follow the parent project".
 * - Maintain the vocabulary through `TagAdminApi`; a vocabulary inherited from a parent project
 *   is read-only here (adding a tag gives the project a list of its own). A new tag is made in a dialog
 *   (`TagCreateModal`) opened by the "New tag" button, never in fields drawn above the table.
 * - Show where a tag is used in a dialog (`TagUsageModal`) opened from the record count in the Used on
 *   column, and launch "reclassify" for a tag, optionally limited to one kind of record.
 * - Follow the style guide's confirmation tiers: delete is Tier 2 (type the tag's name) and names
 *   how many records lose it; merge and reclassify confirm with a count and, for reclassify, a
 *   preview before anything is written. Every change ends in a toast.
 *
 * `api` is injectable for stories; the factories in `api/tags` bind it to a project or the organisation.
 */
import { Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import type { ReclassifyResult, Tag, TagAdminApi, TagMode, TagUsage, TagVocabulary } from "../api/tags";
import { TAG_NAME_MAX_LENGTH, tagNameProblem } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useTableSort } from "../hooks/useTableSort";
import type { SortValue } from "../utils/sortRows";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { ActionMenu } from "./ActionMenu";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { FilterField } from "./FilterPanel";
import { ColorField, TextField } from "./FormFields";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";
import { TagChip } from "./TagChip";
import { TagCreateModal } from "./TagCreateModal";
import { TagUsageModal } from "./TagUsageModal";
import { Tooltip } from "./Tooltip";
import { TAG_COLOURS } from "./tagColours";

type Dialog =
  | { kind: "rename"; tag: Tag }
  | { kind: "colour"; tag: Tag }
  | { kind: "merge"; tag: Tag }
  | { kind: "delete"; tag: Tag }
  | { kind: "usage"; tag: Tag }
  | { kind: "reclassify"; tag: Tag; artefactType?: string };

const NO_TAGS: Tag[] = [];

/** Sortable value of each sortable column of the tag table. */
const TAG_SORT_VALUES: Record<string, (tag: Tag) => SortValue> = {
  name: (tag) => tag.name,
  colour: (tag) => tag.colour,
  used: (tag) => tag.usage_count,
};

/**
 * @param api The calls, bound to a project or to the organisation.
 * @param scope `"project"` offers "follow the parent project" and a parent's inherited list;
 *   `"organisation"` is the organisation's own vocabulary.
 */
export function TagAdminPanel({ api, scope }: { api: TagAdminApi; scope: "project" | "organisation" }) {
  const strings = useStrings();
  const text = strings.tags.admin;
  const { showToast } = useToast();
  const [vocabulary, setVocabulary] = useState<TagVocabulary | null>(null);
  const [usage, setUsage] = useState<TagUsage | null>(null);
  const [failed, setFailed] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [creating, setCreating] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [v, u] = await Promise.all([api.vocabulary(), api.usage()]);
      setVocabulary(v);
      setUsage(u);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api]);

  useLoadOnChange(reload, [api]);

  /** Runs a change, reloads and toasts; an error is toasted and leaves the screen as it was. */
  async function run(action: () => Promise<string>) {
    try {
      showToast(await action());
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const table = useTableSort(vocabulary?.tags ?? NO_TAGS, TAG_SORT_VALUES);
  if (failed && !vocabulary) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!vocabulary || !usage) return <Spinner />;

  async function addTag(name: string, colour: string | null) {
    await api.create(name, colour);
    showToast(text.created);
    await reload();
  }

  const modes: Array<{ value: string; label: string }> = [
    ...(scope === "project" && vocabulary.has_parent ? [{ value: "inherit", label: text.modeInherit }] : []),
    { value: "free", label: text.modeFree },
    { value: "restricted", label: text.modeRestricted },
  ];
  const modeValue = scope === "project" && vocabulary.has_parent ? (vocabulary.own_mode ?? "inherit") : vocabulary.mode;

  const columns: DirectoryColumn<Tag>[] = [
    { key: "name", label: text.nameHeading, sortable: true, render: (tag) => <TagChip tag={tag} /> },
    {
      key: "colour",
      label: text.colourHeading,
      sortable: true,
      render: (tag) => tag.colour ? (
        <span className="row" style={{ gap: "var(--space-2)" }}>
          <span className="colour-swatch" aria-hidden="true" style={{ background: tag.colour, cursor: "default" }} />
          <span className="text-muted">{tag.colour}</span>
        </span>
      ) : <span className="text-muted">{text.noColour}</span>,
    },
    {
      key: "used",
      label: text.usedHeading,
      sortable: true,
      render: (tag) => tag.usage_count > 0 ? (
        <Tooltip label={text.showUsage(tag.name)}>
          <button
            type="button"
            className="btn btn-sm"
            aria-label={text.showUsage(tag.name)}
            onClick={() => setDialog({ kind: "usage", tag })}
          >
            {text.recordsCount(tag.usage_count)}
          </button>
        </Tooltip>
      ) : text.recordsCount(tag.usage_count),
    },
    {
      key: "actions",
      label: <span className="sr-only">{strings.common.moreOptions}</span>,
      render: (tag) => tag.editable ? (
        <ActionMenu
          triggerLabel={`${tag.name}`}
          items={[
            { label: text.rename(tag.name), key: "rename", onSelect: () => setDialog({ kind: "rename", tag }) },
            { label: text.changeColour(tag.name), key: "colour", onSelect: () => setDialog({ kind: "colour", tag }) },
            ...(vocabulary.tags.length > 1
              ? [{ label: text.merge(tag.name), key: "merge", onSelect: () => setDialog({ kind: "merge", tag }) }]
              : []),
            ...(tag.usage_count > 0
              ? [{ label: text.reclassify(tag.name), key: "reclassify", onSelect: () => setDialog({ kind: "reclassify", tag }) }]
              : []),
            { label: text.delete(tag.name), key: "delete", danger: true, onSelect: () => setDialog({ kind: "delete", tag }) },
          ]}
        />
      ) : <Badge>{text.inheritedBadge}</Badge>,
    },
  ];

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{scope === "project" ? text.description : text.orgDescription}</p>

      <LabeledSelect
        helpNotNeeded
        label={text.modeLabel}
        value={modeValue}
        placeholder={null}
        options={modes}
        onChange={(value) =>
          void run(async () => {
            await api.setMode(value === "inherit" ? null : (value as TagMode));
            return text.modeSaved;
          })
        }
      />
      {scope === "project" && vocabulary.has_parent && vocabulary.own_mode === null && (
        <p className="text-muted" style={{ margin: 0 }}>
          {text.modeInheritedHint(vocabulary.mode === "restricted" ? text.modeRestricted : text.modeFree)}
        </p>
      )}
      {vocabulary.inherited && <p className="text-muted" style={{ margin: 0 }}>{text.inheritedNotice}</p>}

      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        <Plus /> {text.addLabel}
      </button>

      <DirectoryTable
        ariaLabel={text.title}
        columns={columns}
        rows={table.rows}
        sort={table.sort}
        onSort={table.onSort}
        rowKey={(tag) => tag.id}
        emptyState={<p className="text-muted">{strings.tags.filter.none}</p>}
      />

      {creating && <TagCreateModal onCreate={addTag} onClose={() => setCreating(false)} />}
      {dialog?.kind === "usage" && (
        <TagUsageModal
          tag={dialog.tag}
          usage={usage}
          editable={!vocabulary.inherited}
          onReclassify={(artefactType) => setDialog({ kind: "reclassify", tag: dialog.tag, artefactType })}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "rename" && (
        <RenameDialog
          tag={dialog.tag}
          onCancel={() => setDialog(null)}
          onSave={(name) => {
            setDialog(null);
            void run(async () => {
              await api.update(dialog.tag.id, { name });
              return text.renamed;
            });
          }}
        />
      )}
      {dialog?.kind === "colour" && (
        <ColourDialog
          tag={dialog.tag}
          onCancel={() => setDialog(null)}
          onSave={(colour) => {
            setDialog(null);
            void run(async () => {
              await api.update(dialog.tag.id, colour === "" ? { clear_colour: true } : { colour });
              return text.colourSaved;
            });
          }}
        />
      )}
      {dialog?.kind === "merge" && (
        <MergeDialog
          tag={dialog.tag}
          others={vocabulary.tags.filter((t) => t.id !== dialog.tag.id)}
          onCancel={() => setDialog(null)}
          onMerge={(intoId) => {
            setDialog(null);
            void run(async () => {
              const result = await api.merge(dialog.tag.id, intoId);
              return text.merged(result.records_moved);
            });
          }}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title={text.deleteTitle(dialog.tag.name)}
          message={text.deleteBody(dialog.tag.name, dialog.tag.usage_count)}
          confirmLabel={text.deleteConfirm}
          requireTypedText={dialog.tag.name}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const tag = dialog.tag;
            setDialog(null);
            void run(async () => {
              const result = await api.remove(tag.id);
              return text.deleted(result.records_untagged);
            });
          }}
        />
      )}
      {dialog?.kind === "reclassify" && (
        <ReclassifyDialog
          api={api}
          tag={dialog.tag}
          others={vocabulary.tags.filter((t) => t.id !== dialog.tag.id)}
          types={usage.tables.map((t) => ({ type: t.artefact_type, label: t.label }))}
          initialType={dialog.artefactType}
          onClose={() => setDialog(null)}
          onApplied={async (result) => {
            setDialog(null);
            showToast(text.reclassifyDone(result.matched));
            await reload();
          }}
        />
      )}
    </div>
  );
}

function RenameDialog({ tag, onCancel, onSave }: { tag: Tag; onCancel: () => void; onSave: (name: string) => void }) {
  const strings = useStrings();
  const [name, setName] = useState(tag.name);
  const problem = tagNameProblem(name);
  return (
    <Modal title={strings.tags.admin.rename(tag.name)} onClose={onCancel}>
      <div className="stack">
        <TextField helpNotNeeded required
          label={strings.tags.admin.nameHeading}
          value={name}
          onChange={setName}
          inputProps={{ maxLength: TAG_NAME_MAX_LENGTH * 2, autoFocus: true }}
        />
        {problem === "too_long" && <span role="alert" style={{ color: "var(--color-danger)" }}>{strings.tags.tooLong(TAG_NAME_MAX_LENGTH)}</span>}
        {problem === "invalid_characters" && <span role="alert" style={{ color: "var(--color-danger)" }}>{strings.tags.invalidCharacters}</span>}
        <FormActions
          onCancel={onCancel}
          onSave={() => { if (!problem) onSave(name.trim()); }}
          saveLabel={strings.tags.admin.renameSave}
          saveDisabled={!!problem}
        />
      </div>
    </Modal>
  );
}

/** Sets or clears one tag's colour: presets, the colour wheel or a hex code. */
function ColourDialog({ tag, onCancel, onSave }: { tag: Tag; onCancel: () => void; onSave: (colour: string) => void }) {
  const strings = useStrings();
  const [colour, setColour] = useState(tag.colour ?? "");
  return (
    <Modal title={strings.tags.admin.changeColour(tag.name)} onClose={onCancel}>
      <div className="stack">
        <ColorField helpNotNeeded
          label={strings.tags.admin.colourHeading}
          ariaLabel={strings.tags.admin.colourLabel(tag.name)}
          value={colour}
          onChange={setColour}
          presets={TAG_COLOURS}
          emptyLabel={strings.tags.admin.noColour}
        />
        <FormActions onCancel={onCancel} onSave={() => onSave(colour)} saveLabel={strings.tags.admin.colourSave} />
      </div>
    </Modal>
  );
}

function MergeDialog({
  tag, others, onCancel, onMerge,
}: { tag: Tag; others: Tag[]; onCancel: () => void; onMerge: (intoId: string) => void }) {
  const strings = useStrings();
  const [target, setTarget] = useState(others[0]?.id ?? "");
  return (
    <Modal title={strings.tags.admin.mergeTitle(tag.name)} onClose={onCancel}>
      <div className="stack">
        <p className="text-muted" style={{ margin: 0 }}>{strings.tags.admin.mergeBody(tag.name, tag.usage_count)}</p>
        <LabeledSelect help={strings.help.tagMergeInto}
          label={strings.tags.admin.mergeTarget}
          value={target}
          onChange={setTarget}
          placeholder={null}
          options={others.map((t) => ({ value: t.id, label: t.name }))}
        />
        <FormActions
          onCancel={onCancel}
          onSave={() => onMerge(target)}
          saveLabel={strings.tags.admin.mergeConfirm}
          saveDisabled={!target}
        />
      </div>
    </Modal>
  );
}

function ReclassifyDialog({
  api, tag, others, types, initialType, onClose, onApplied,
}: {
  api: TagAdminApi;
  tag: Tag;
  others: Tag[];
  types: Array<{ type: string; label: string }>;
  initialType?: string;
  onClose: () => void;
  onApplied: (result: ReclassifyResult) => void | Promise<void>;
}) {
  const strings = useStrings();
  const text = strings.tags.admin;
  const [add, setAdd] = useState<string[]>([]);
  const [remove, setRemove] = useState<string[]>([tag.id]);
  const [type, setType] = useState(initialType ?? "");
  const [forecast, setForecast] = useState<ReclassifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const candidates = useMemo(() => [tag, ...others], [tag, others]);
  const body = (dryRun: boolean) => ({
    from_tag_id: tag.id, artefact_types: type ? [type] : undefined, add, remove, dry_run: dryRun,
  });
  const choices = (selected: string[], set: (ids: string[]) => void, label: string) => (
    <MultiSelectDropdown
      triggerLabel={label}
      emptyLabel={strings.tags.filter.choose}
      options={candidates.map((t) => {
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

  async function preview() {
    setBusy(true);
    setError(null);
    try {
      setForecast(await api.reclassify(body(true)));
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      await onApplied(await api.reclassify(body(false)));
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
      setBusy(false);
    }
  }

  const nothingChosen = add.length === 0 && remove.length === 0;
  return (
    <Modal title={text.reclassifyTitle(tag.name)} onClose={onClose}>
      <div className="stack">
        <FilterField label={text.reclassifyAdd}>{choices(add, setAdd, text.reclassifyAdd)}</FilterField>
        <FilterField label={text.reclassifyRemove}>{choices(remove, setRemove, text.reclassifyRemove)}</FilterField>
        <LabeledSelect helpNotNeeded
          label={text.reclassifyTypes}
          value={type}
          onChange={(next) => { setType(next); setForecast(null); }}
          placeholder={text.reclassifyAllTypes}
          options={types.map((t) => ({ value: t.type, label: t.label }))}
        />
        {nothingChosen && <p className="text-muted" style={{ margin: 0 }}>{text.reclassifyNothing}</p>}
        {forecast && <p role="status" style={{ margin: 0 }}>{text.reclassifyForecast(forecast.matched, forecast.added, forecast.removed)}</p>}
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={() => void apply()}
          saveLabel={text.reclassifyApply}
          saveDisabled={busy || nothingChosen || !forecast}
        >
          <button type="button" className="btn" disabled={busy || nothingChosen} onClick={() => void preview()}>
            {text.reclassifyPreview}
          </button>
        </FormActions>
      </div>
    </Modal>
  );
}
