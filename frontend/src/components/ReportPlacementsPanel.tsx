/**
 * Module: components/ReportPlacementsPanel
 *
 * Arranges the Reports picker for an organisation or a project (Org Admin → Templates & reports, Project Admin →
 * Report setup): where each report is filed and which module reports are shown. One component for both tiers over
 * `ReportPlacementApi`.
 *
 * Responsibilities:
 * - List every report the scope can place, upstream ones included (module reports, layouts and packs shared from the
 *   organisation or a parent project), with the folder it files under now, the default it would otherwise have and
 *   which tier set the override (the style guide's "platform default override visibility").
 * - Move a report to a folder (`ReportFolderField`), reset it to the default, hide a module report from the picker,
 *   show it again and return to following what the tiers above set. A shared layout or pack is hidden from its own list, so only moved here.
 * - Follow the confirmation tiers: hiding is Tier 1 (a confirm); every change ends in a toast.
 *
 * Design decisions: a placement tidies what people are offered, it does not remove access, and the confirm says so;
 * access is enforced by the server (403 shows the load failure) and the panel does not guess permissions.
 */
import { useCallback, useMemo, useState } from "react";

import type { PlacementSource, ReportPlacement, ReportPlacementApi } from "../api/reportPlacements";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useShowMore } from "../hooks/useShowMore";
import { distinctFolders, folderProblem, tidyFolder } from "../utils/reportFolders";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { FilterField, FilterPanel } from "./FilterPanel";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { ReportFolderField } from "./ReportFolderField";
import { Spinner } from "./Spinner";

type Dialog = { kind: "move"; row: ReportPlacement } | { kind: "hide"; row: ReportPlacement };
type StatusFilter = "" | "moved" | "hidden";

/** @param api The calls, bound to an organisation or a project. */
export function ReportPlacementsPanel({ api }: { api: ReportPlacementApi }) {
  const strings = useStrings();
  const text = strings.reportPlacements;
  const { showToast } = useToast();
  const [rows, setRows] = useState<ReportPlacement[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState("");
  const [status, setStatus] = useState<StatusFilter>("");

  const reload = useCallback(async () => {
    try {
      setRows(await api.list());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api]);
  useLoadOnChange(reload, [api.scope.kind, api.scope.id]);

  const needle = search.trim().toLowerCase();
  const matching = useMemo(
    () => (rows ?? []).filter((row) => (
      (needle === "" || `${row.title} ${row.description} ${row.folder} ${row.group}`.toLowerCase().includes(needle))
      && (group === "" || row.group === group)
      && (status === "" || (status === "hidden" ? row.hidden : row.folder !== row.default_folder))
    )),
    [rows, needle, group, status],
  );
  const { limit, more } = useShowMore(matching.length, `${needle}|${group}|${status}`);

  /** Sets one placement, toasts the outcome and takes the refreshed list; an error is toasted and leaves the list. */
  async function change(change: Parameters<ReportPlacementApi["set"]>[0], message: string) {
    try {
      setRows(await api.set(change));
      showToast(message);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (failed && !rows) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!rows) return <Spinner />;

  const groups = [...new Set(rows.map((row) => row.group))].sort((a, b) => a.localeCompare(b));
  const folders = distinctFolders(rows.map((row) => row.folder));
  const inProject = api.scope.kind === "project";

  const sourceLabel = (source: PlacementSource | null) => (source ? text.source[source] : "");

  function menuFor(row: ReportPlacement): ActionMenuItem[] {
    const items: ActionMenuItem[] = [{ key: "move", label: text.move, onSelect: () => setDialog({ kind: "move", row }) }];
    if (row.own_folder !== null) {
      items.push({ key: "reset-folder", label: text.resetFolder, onSelect: () => void change({ report_key: row.report_key, folder: null }, text.folderReset) });
    }
    if (row.own_hidden !== null) {
      items.push({ key: "reset-visibility", label: text.resetVisibility, onSelect: () => void change({ report_key: row.report_key, hidden: null }, text.visibilityReset) });
    }
    if (row.can_hide) {
      items.push(row.hidden
        ? { key: "show", label: text.show, onSelect: () => void change({ report_key: row.report_key, hidden: row.hidden_from === "project" || !inProject ? null : false }, text.shown) }
        : { key: "hide", label: text.hide, danger: true, onSelect: () => setDialog({ kind: "hide", row }) });
    }
    return items;
  }

  const columns: DirectoryColumn<ReportPlacement>[] = [
    {
      key: "report",
      label: text.reportHeading,
      render: (row) => (
        <span className="stack" style={{ gap: 0 }}>
          <span>{row.title}</span>
          <span className="text-muted" style={{ fontSize: "0.85rem" }}>{row.group}</span>
        </span>
      ),
    },
    { key: "kind", label: text.kindHeading, render: (row) => <Badge>{text.kind[row.kind]}</Badge> },
    {
      key: "folder",
      label: text.folderHeading,
      render: (row) => (
        <span className="stack" style={{ gap: 0 }}>
          <span>{row.folder || text.topLevel}</span>
          {row.folder !== row.default_folder && (
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>
              {text.defaultFolder(row.default_folder)}{row.folder_from && row.folder_from !== api.scope.kind && row.folder_from !== "project" ? ` · ${sourceLabel(row.folder_from)}` : ""}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "visibility",
      label: text.visibilityHeading,
      render: (row) => (row.hidden
        ? <Badge>{row.hidden_from && row.hidden_from !== (inProject ? "project" : "organization") ? text.hiddenBy(sourceLabel(row.hidden_from)) : text.hidden}</Badge>
        : null),
    },
    {
      key: "actions",
      label: <span className="sr-only">{strings.common.moreOptions}</span>,
      render: (row) => <ActionMenu triggerLabel={text.actionsFor(row.title)} items={menuFor(row)} />,
    },
  ];

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{inProject ? text.projectDescription : text.orgDescription}</p>
      <FilterPanel
        sectionKey={`reportPlacements.${api.scope.kind}`} layout="top" matching={matching.length} total={rows.length}
        search={search} onSearchChange={setSearch} searchPlaceholder={text.searchPlaceholder} searchAriaLabel={text.searchLabel}
      >
        <FilterField label={text.groupFilter}>
          <select className="input" value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">{text.any}</option>
            {groups.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </FilterField>
        <FilterField label={text.statusFilter}>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
            <option value="">{text.any}</option>
            <option value="moved">{text.statusMoved}</option>
            <option value="hidden">{text.statusHidden}</option>
          </select>
        </FilterField>
      </FilterPanel>
      <DirectoryTable
        ariaLabel={text.listLabel}
        columns={columns}
        rows={matching.slice(0, limit)}
        total={matching.length}
        onLoadMore={more}
        rowKey={(row) => row.report_key}
        emptyState={<p className="text-muted">{rows.length > 0 ? strings.reportListControls.noMatch : text.empty}</p>}
      />

      {dialog?.kind === "move" && (
        <MoveDialog
          row={dialog.row} folders={folders} onClose={() => setDialog(null)}
          onSave={async (folder) => {
            await change({ report_key: dialog.row.report_key, folder }, text.moved);
            setDialog(null);
          }}
        />
      )}
      {dialog?.kind === "hide" && (
        <ConfirmDialog
          title={text.hideTitle(dialog.row.title)}
          message={text.hideMessage}
          confirmLabel={text.hide}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const row = dialog.row;
            setDialog(null);
            void change({ report_key: row.report_key, hidden: true }, text.hiddenToast);
          }}
        />
      )}
    </div>
  );
}

/** The dialog that moves one report to a folder (the same field group as a layout's or pack's own folder). */
function MoveDialog({
  row, folders, onClose, onSave,
}: { row: ReportPlacement; folders: string[]; onClose: () => void; onSave: (folder: string) => Promise<void> }) {
  const strings = useStrings();
  const text = strings.reportPlacements;
  const [folder, setFolder] = useState(row.folder);
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={text.moveTitle(row.title)} onClose={onClose}>
      <div className="stack">
        <ReportFolderField value={folder} onChange={setFolder} suggestions={folders} label={text.moveField} helpKey="reportPlacementFolder" />
        <FormActions
          onCancel={onClose}
          onSave={() => {
            setBusy(true);
            void onSave(tidyFolder(folder)).finally(() => setBusy(false));
          }}
          saveLabel={text.moveSave}
          saveDisabled={busy || folderProblem(folder) !== null}
          cancelDisabled={busy}
        />
      </div>
    </Modal>
  );
}
