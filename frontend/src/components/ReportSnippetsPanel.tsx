/**
 * Module: components/ReportSnippetsPanel
 *
 * The Report snippets section of Report setup (Org Admin → Templates & reports, Project Admin → Report setup): the snippets
 * authors saved from the designer, as a list the scope can manage.
 *
 * Responsibilities:
 * - List the saved snippets the scope can reach (name and description, category, where each comes from, how many blocks,
 *   and the page styles and variables it carries) with search; a project's list shows the ones it hides, flagged.
 * - New snippet, and Edit (details and blocks) for an own snippet, in `ReportSnippetEditorDialog`; make a copy (into the scope, or up to the organisation from a project), delete an own snippet,
 *   hide or show an inherited one in a project; "Add organisation defaults" restores the hidden ones.
 * - Follow the confirmation tiers: delete is Tier 2 (type the name); hiding is Tier 1. Every change ends in a toast.
 *
 * Design decisions: the server authorises each row (a 403 shows the load failure; the panel does not guess permissions). A
 * snippet is written in the layout editors (the dialog reuses them), whether it is made here or saved from the designer. A snippet is
 * configuration, not an artefact type, so it has no code and no link; the list is a plain table (it has no folders).
 */
import { useCallback, useMemo, useState } from "react";

import { LAYOUT_ORIGIN_LABEL, reportLayoutApi, type ReportLayoutApi } from "../api/reportLayouts";
import { reportSnippetStoreApi, type ReportSnippetStoreApi, type SavedSnippet } from "../api/reportSnippets";
import { ApiError } from "../api/client";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { FilterPanel } from "./FilterPanel";
import { ReportSnippetEditorDialog } from "./ReportSnippetEditorDialog";
import { RestoreOrgDefaultsButton } from "./RestoreOrgDefaultsButton";
import { Spinner } from "./Spinner";

type Dialog =
  | { kind: "new" }
  | { kind: "edit"; row: SavedSnippet }
  | { kind: "delete"; row: SavedSnippet }
  | { kind: "hide"; row: SavedSnippet };

/** What a snippet carries beyond its blocks, in words ("Page style Wide; variable audience"). */
function carriedText(row: SavedSnippet, empty: string): string {
  const parts = [...row.page_styles.map((n) => `style ${n}`), ...row.variables.map((n) => `variable ${n}`)];
  return parts.length > 0 ? parts.join(", ") : empty;
}

/**
 * @param api The saved-snippet calls, bound to an organisation or a project; the live ones for `scope` when omitted.
 * @param scope The scope to bind the live calls to (ignored when `api` is given).
 * @param layoutApi The layout calls of the same scope, for the snippet editor.
 */
export function ReportSnippetsPanel({
  api: apiProp, scope, layoutApi: layoutApiProp,
}: {
  api?: ReportSnippetStoreApi;
  scope?: { kind: "organization" | "project"; id: string };
  /** The layout calls the snippet editor draws its block types, fields and pictures from; the live ones for the scope when omitted. */
  layoutApi?: ReportLayoutApi;
}) {
  const strings = useStrings();
  const text = strings.reportSnippetsPanel;
  const { showToast } = useToast();
  const api = useMemo(() => {
    if (apiProp) return apiProp;
    if (!scope) throw new Error("ReportSnippetsPanel needs an api or a scope.");
    return reportSnippetStoreApi(scope);
  }, [apiProp, scope]);
  const layoutApi = useMemo(() => layoutApiProp ?? reportLayoutApi(api.scope), [layoutApiProp, api.scope]);
  const inProject = api.scope.kind === "project";
  const [rows, setRows] = useState<SavedSnippet[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [search, setSearch] = useState("");
  const [copyBlocked, setCopyBlocked] = useState<string[]>([]);

  const reload = useCallback(async () => {
    try {
      setRows(await api.list());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api]);
  useLoadOnChange(reload, [api.scope.kind, api.scope.id]);

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (rows ?? []).filter((r) => needle === "" || `${r.name} ${r.description} ${r.category}`.toLowerCase().includes(needle));
  }, [rows, search]);
  const categories = useMemo(() => [...new Set((rows ?? []).map((r) => r.category))], [rows]);
  const hidden = useMemo(() => (rows ?? []).filter((r) => r.hidden), [rows]);

  /** Runs a change, then reloads and says what happened; a refusal is shown in a toast. */
  async function run(change: () => Promise<string>) {
    try {
      showToast(await change());
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, text.failed), "error");
    }
  }

  async function copy(row: SavedSnippet, target: "project" | "organization") {
    setCopyBlocked([]);
    try {
      const made = await api.copy(row.id, { target });
      showToast(text.copied(made.name));
      await reload();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && typeof err.detail === "object" && err.detail !== null) {
        const errors = (err.detail as { errors?: { message: string }[] }).errors ?? [];
        setCopyBlocked(errors.map((e) => e.message));
      } else {
        showToast(toErrorMessage(err, text.copyFailed), "error");
      }
    }
  }

  function menuFor(row: SavedSnippet): ActionMenuItem[] {
    const items: ActionMenuItem[] = [];
    if (row.editable) items.push({ key: "edit", label: text.edit, onSelect: () => setDialog({ kind: "edit", row }) });
    items.push({ key: "copy", label: text.makeCopy, onSelect: () => void copy(row, inProject ? "project" : "organization") });
    if (inProject) items.push({ key: "copy-up", label: text.copyToOrganization, onSelect: () => void copy(row, "organization") });
    if (!row.editable && api.setHidden && !row.hidden) items.push({ key: "hide", label: text.hide, danger: true, onSelect: () => setDialog({ kind: "hide", row }) });
    if (!row.editable && api.setHidden && row.hidden) {
      items.push({ key: "show", label: text.show, onSelect: () => void run(async () => { await api.setHidden?.(row.id, false); return text.shown; }) });
    }
    if (row.editable) items.push({ key: "delete", label: text.delete, danger: true, onSelect: () => setDialog({ kind: "delete", row }) });
    return items;
  }

  const columns: DirectoryColumn<SavedSnippet>[] = [
    {
      key: "name", label: text.nameHeader,
      render: (row) => (
        <span className="stack" style={{ gap: 0 }}>
          <strong>{row.name}</strong>
          {row.description && <span className="text-muted">{row.description}</span>}
        </span>
      ),
    },
    { key: "category", label: text.categoryHeader, render: (row) => row.category },
    {
      key: "source", label: text.sourceHeader,
      render: (row) => (
        <>
          {LAYOUT_ORIGIN_LABEL[row.origin]} {row.hidden && <Badge>{text.hiddenBadge}</Badge>}
        </>
      ),
    },
    { key: "blocks", label: text.blocksHeader, render: (row) => row.blocks },
    { key: "carries", label: text.carriesHeader, render: (row) => carriedText(row, text.carriesNothing) },
    {
      key: "actions", label: <span className="sr-only">{text.actionsHeader}</span>,
      render: (row) => <ActionMenu triggerLabel={text.actionsFor(row.name)} items={menuFor(row)} />,
    },
  ];

  if (failed) return <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{text.loadFailed}</p>;
  if (rows === null) return <Spinner />;
  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.hint}</p>
      <div className="row">
        <button type="button" className="btn btn-primary" aria-haspopup="dialog" onClick={() => setDialog({ kind: "new" })}>{text.newButton}</button>
      </div>
      {inProject && api.restore && (
        <div className="row">
          <RestoreOrgDefaultsButton
            hidden={hidden.map((r) => ({ id: r.id, name: r.name }))}
            noun={text.restoreNoun}
            onRestore={async (ids) => {
              await api.restore?.(ids);
              showToast(text.restored);
              await reload();
            }}
          />
        </div>
      )}
      <FilterPanel
        sectionKey={`reportSnippets.${api.scope.kind}`} layout="top" matching={shown.length} total={rows.length}
        search={search} onSearchChange={setSearch} searchPlaceholder={text.searchLabel} searchAriaLabel={text.searchLabel}
      >
        {null}
      </FilterPanel>
      {copyBlocked.length > 0 && (
        <div role="alert" className="stack" style={{ gap: "var(--space-1)", color: "var(--color-danger)" }}>
          <span>{text.copyBlocked}</span>
          <ul style={{ margin: 0 }}>{copyBlocked.map((message, index) => <li key={index}>{message}</li>)}</ul>
        </div>
      )}
      <DirectoryTable
        ariaLabel={text.listLabel} columns={columns} rows={shown} rowKey={(row) => row.id}
        emptyState={<p className="text-muted" style={{ margin: 0 }}>{rows.length > 0 ? text.noMatch : text.empty}</p>}
      />
      {dialog?.kind === "new" && (
        <ReportSnippetEditorDialog
          api={api} layoutApi={layoutApi} categories={categories} onClose={() => setDialog(null)}
          onSaved={(saved) => { setDialog(null); showToast(strings.reportSnippetSave.saved(saved.name)); void reload(); }}
        />
      )}
      {dialog?.kind === "edit" && (
        <ReportSnippetEditorDialog
          api={api} layoutApi={layoutApi} snippet={dialog.row} categories={categories} onClose={() => setDialog(null)}
          onSaved={() => { setDialog(null); showToast(text.editSaved); void reload(); }}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title={text.deleteTitle(dialog.row.name)} message={text.deleteMessage} confirmLabel={text.delete}
          requireTypedText={dialog.row.name} onCancel={() => setDialog(null)}
          onConfirm={() => {
            const row = dialog.row;
            setDialog(null);
            void run(async () => { await api.remove(row.id); return text.deleted; });
          }}
        />
      )}
      {dialog?.kind === "hide" && (
        <ConfirmDialog
          title={text.hideTitle(dialog.row.name)} message={text.hideMessage} confirmLabel={text.hideConfirm}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const row = dialog.row;
            setDialog(null);
            void run(async () => { await api.setHidden?.(row.id, true); return text.hidden; });
          }}
        />
      )}
    </div>
  );
}
