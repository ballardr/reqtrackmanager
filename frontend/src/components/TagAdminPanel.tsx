/**
 * Module: components/TagAdminPanel
 *
 * The tag administration surface, one component for a project (Project Admin) and for the
 * organisation (Org Admin, for organisation-owned records): who may add a new tag, the vocabulary
 * (add, rename, colour, merge, reclassify, delete) and the usage tables, one per kind of record.
 *
 * Responsibilities:
 * - Show and set the mode: free, restricted, and for a project "follow the parent project".
 * - Maintain the vocabulary through `TagAdminApi`; a vocabulary inherited from a parent project
 *   is read-only here (adding a tag gives the project a list of its own).
 * - Show tag x record-type usage with a filter box and tick boxes that hide tags while reviewing,
 *   and launch "reclassify" for a tag, optionally limited to one kind of record.
 * - Follow the style guide's confirmation tiers: delete is Tier 2 (type the tag's name) and names
 *   how many records lose it; merge and reclassify confirm with a count and, for reclassify, a
 *   preview before anything is written. Every change ends in a toast.
 *
 * `api` is injectable for stories; the factories in `api/tags` bind it to a project or the organisation.
 */
import { useCallback, useMemo, useState } from "react";

import type { ReclassifyResult, Tag, TagAdminApi, TagMode, TagUsage, TagVocabulary } from "../api/tags";
import { TAG_NAME_MAX_LENGTH, tagNameProblem } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { ActionMenu } from "./ActionMenu";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { FilterField } from "./FilterPanel";
import { TextField } from "./FormFields";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";
import { TagChip } from "./TagChip";
import { TAG_COLOURS } from "./tagColours";

type Dialog =
  | { kind: "rename"; tag: Tag }
  | { kind: "merge"; tag: Tag }
  | { kind: "delete"; tag: Tag }
  | { kind: "reclassify"; tag: Tag; artefactType?: string };

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
  const [newName, setNewName] = useState("");
  const [newColour, setNewColour] = useState("");

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

  if (failed && !vocabulary) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!vocabulary || !usage) return <Spinner />;

  const nameProblem = newName.trim() === "" ? null : tagNameProblem(newName);

  async function addTag() {
    const colour = newColour || null;
    await run(async () => {
      await api.create(newName.trim(), colour);
      setNewName("");
      setNewColour("");
      return text.created;
    });
  }

  const modes: Array<{ value: string; label: string }> = [
    ...(scope === "project" && vocabulary.has_parent ? [{ value: "inherit", label: text.modeInherit }] : []),
    { value: "free", label: text.modeFree },
    { value: "restricted", label: text.modeRestricted },
  ];
  const modeValue = scope === "project" && vocabulary.has_parent ? (vocabulary.own_mode ?? "inherit") : vocabulary.mode;

  const columns: DirectoryColumn<Tag>[] = [
    { key: "name", label: text.nameHeading, render: (tag) => <TagChip tag={tag} /> },
    {
      key: "colour",
      label: text.colourHeading,
      render: (tag) => (
        <select
          className="input"
          style={{ width: "auto" }}
          aria-label={text.colourLabel(tag.name)}
          value={TAG_COLOURS.some((c) => c.hex === tag.colour) ? (tag.colour ?? "") : tag.colour ? "custom" : ""}
          disabled={!tag.editable}
          onChange={(e) => {
            const value = e.target.value;
            if (value === "custom") return;
            void run(async () => {
              await api.update(tag.id, value === "" ? { clear_colour: true } : { colour: value });
              return text.renamed;
            });
          }}
        >
          <option value="">{text.noColour}</option>
          {tag.colour && !TAG_COLOURS.some((c) => c.hex === tag.colour) && <option value="custom">{tag.colour}</option>}
          {TAG_COLOURS.map((c) => <option key={c.hex} value={c.hex}>{c.name}</option>)}
        </select>
      ),
    },
    { key: "used", label: text.usedHeading, render: (tag) => text.recordsCount(tag.usage_count) },
    {
      key: "actions",
      label: <span className="sr-only">{strings.common.moreOptions}</span>,
      render: (tag) => tag.editable ? (
        <ActionMenu
          triggerLabel={`${tag.name}`}
          items={[
            { label: text.rename(tag.name), key: "rename", onSelect: () => setDialog({ kind: "rename", tag }) },
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

      <FilterField label={text.modeLabel}>
        <select
          className="input"
          style={{ maxWidth: 320 }}
          aria-label={text.modeLabel}
          value={modeValue}
          onChange={(e) => {
            const value = e.target.value;
            void run(async () => {
              await api.setMode(value === "inherit" ? null : (value as TagMode));
              return text.modeSaved;
            });
          }}
        >
          {modes.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
      </FilterField>
      {scope === "project" && vocabulary.has_parent && vocabulary.own_mode === null && (
        <p className="text-muted" style={{ margin: 0 }}>
          {text.modeInheritedHint(vocabulary.mode === "restricted" ? text.modeRestricted : text.modeFree)}
        </p>
      )}
      {vocabulary.inherited && <p className="text-muted" style={{ margin: 0 }}>{text.inheritedNotice}</p>}

      <form
        className="row"
        style={{ alignItems: "flex-end" }}
        onSubmit={(e) => {
          e.preventDefault();
          if (newName.trim() !== "" && !nameProblem) void addTag();
        }}
      >
        <TextField helpNotNeeded
          label={text.addLabel}
          value={newName}
          onChange={setNewName}
          placeholder={text.addPlaceholder}
          inputProps={{ maxLength: TAG_NAME_MAX_LENGTH * 2 }}
        />
        <LabeledSelect helpNotNeeded
          label={text.colourHeading}
          ariaLabel={text.colourLabel(newName.trim() || text.addLabel)}
          value={newColour}
          onChange={setNewColour}
          placeholder={text.noColour}
          options={TAG_COLOURS.map((c) => ({ value: c.hex, label: c.name }))}
        />
        <button type="submit" className="btn btn-primary" disabled={newName.trim() === "" || !!nameProblem}>
          {text.addButton}
        </button>
      </form>
      {nameProblem && (
        <span role="alert" style={{ fontSize: "0.8rem", color: "var(--color-danger)" }}>
          {nameProblem === "too_long" ? strings.tags.tooLong(TAG_NAME_MAX_LENGTH) : strings.tags.invalidCharacters}
        </span>
      )}

      <DirectoryTable
        ariaLabel={text.title}
        columns={columns}
        rows={vocabulary.tags}
        rowKey={(tag) => tag.id}
        emptyState={<p className="text-muted">{strings.tags.filter.none}</p>}
      />

      <UsageTables usage={usage} editable={!vocabulary.inherited} onReclassify={(tagId, artefactType) => {
        const tag = vocabulary.tags.find((t) => t.id === tagId);
        if (tag) setDialog({ kind: "reclassify", tag, artefactType });
      }} />

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

/** One table per kind of record: tags as rows with counts, a filter box and tick boxes that hide tags while reviewing. */
function UsageTables({
  usage, editable, onReclassify,
}: { usage: TagUsage; editable: boolean; onReclassify: (tagId: string, artefactType: string) => void }) {
  const strings = useStrings();
  const text = strings.tags.admin;
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<Record<string, string>>({});

  return (
    <div className="stack">
      <h3 style={{ margin: 0 }}>{text.usageHeading}</h3>
      <p className="text-muted" style={{ margin: 0 }}>{text.usageDescription}</p>
      {hidden.size > 0 && (
        <div className="row">
          <span className="text-muted">{text.usageHiddenCount(hidden.size)}</span>
          <button type="button" className="btn btn-sm" onClick={() => setHidden(new Set())}>{text.usageShowAll}</button>
        </div>
      )}
      {usage.tables.length === 0 && <p className="text-muted">{text.usageEmpty}</p>}
      {usage.tables.map((table) => {
        const needle = (filters[table.artefact_type] ?? "").trim().toLowerCase();
        const rows = table.rows.filter((r) => !hidden.has(r.tag_id) && r.name.toLowerCase().includes(needle));
        const columns: DirectoryColumn<(typeof table.rows)[number]>[] = [
          {
            key: "hide",
            label: <span className="sr-only">{text.usageHide("")}</span>,
            render: (row) => (
              <input
                type="checkbox"
                aria-label={text.usageHide(row.name)}
                checked={hidden.has(row.tag_id)}
                onChange={(e) => setHidden((current) => {
                  const next = new Set(current);
                  if (e.target.checked) next.add(row.tag_id);
                  else next.delete(row.tag_id);
                  return next;
                })}
              />
            ),
          },
          { key: "tag", label: text.nameHeading, render: (row) => <TagChip tag={{ name: row.name, colour: row.colour }} /> },
          { key: "count", label: text.usedHeading, render: (row) => text.recordsCount(row.count) },
          {
            key: "last",
            label: text.lastUsedHeading,
            render: (row) => (row.last_used ? new Date(row.last_used).toLocaleDateString() : ""),
          },
          {
            key: "actions",
            label: <span className="sr-only">{strings.common.moreOptions}</span>,
            render: (row) => editable ? (
              <button
                type="button"
                className="btn btn-sm"
                aria-label={`${text.reclassify(row.name)} (${table.label})`}
                onClick={() => onReclassify(row.tag_id, table.artefact_type)}
              >
                {text.reclassifyButton}
              </button>
            ) : null,
          },
        ];
        return (
          <section key={table.artefact_type} className="stack" aria-label={table.label}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h4 style={{ margin: 0 }}>{table.label}</h4>
              <input
                className="input"
                style={{ maxWidth: 220 }}
                placeholder={text.usageFilter}
                aria-label={`${text.usageFilter} (${table.label})`}
                value={filters[table.artefact_type] ?? ""}
                onChange={(e) => setFilters({ ...filters, [table.artefact_type]: e.target.value })}
              />
            </div>
            <DirectoryTable
              ariaLabel={`${text.usageHeading}: ${table.label}`}
              columns={columns}
              rows={rows}
              rowKey={(row) => row.tag_id}
              emptyState={<p className="text-muted">{text.usageEmpty}</p>}
            />
          </section>
        );
      })}
      {usage.unused.length > 0 && (
        <div className="stack" style={{ gap: "0.25rem" }}>
          <h4 style={{ margin: 0 }}>{text.unusedHeading}</h4>
          <div className="row" style={{ gap: "0.35rem" }}>
            {usage.unused.map((tag) => <TagChip key={tag.id} tag={tag} />)}
          </div>
        </div>
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
        <TextField helpNotNeeded
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
