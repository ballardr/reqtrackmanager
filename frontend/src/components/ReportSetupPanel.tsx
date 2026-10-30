/**
 * Module: components/ReportSetupPanel
 *
 * Report setup for an organisation or a project (Org Admin → Templates & reports, Project Admin → Report setup): one
 * folder list of every report the scope can arrange, in the shape of the Reports chooser. Custom layouts, report packs
 * and the reports modules and the platform provide are rows of one tree (`FolderTreeList`), each with the actions that
 * apply to it.
 *
 * Responsibilities:
 * - Merge the placement, layout, pack and folder lists (`utils/reportSetupRows`) into one typed row model and show it
 *   as folders and rows, with search and type, status and (in a project) source filters.
 * - Row actions by type: open the designer or pack editor, edit details, duplicate (`ReportDuplicateDialog`), move to a folder, delete an own
 *   layout or pack; hide a shared layout or pack in a project (and show it again), hide or show a module report, reset
 *   a folder or visibility override back to what the tiers above set.
 * - Folder rows: New folder inside, Rename and Delete (a folder the scope owns); a New menu creates a layout, a pack, a layout from a built-in starter or
 *   a folder; an organisation adds the starter layouts; a project restores hidden layouts and packs in one go.
 * - In a project, copy reports to another project: "Copy to another project…" turns on tick boxes (a folder's box covers
 *   what is in it) and a row's menu copies that one report; both open `ReportCopyDialog`.
 * - Follow the confirmation tiers: delete is Tier 2 (type the name); hiding and deleting a folder are Tier 1. Every
 *   change ends in a toast.
 *
 * Design decisions: a client-side merge of lists the server already authorises row by row (a 403 shows the load
 * failure; the panel does not guess permissions). Moving an owned layout or pack edits its own folder, moving any
 * other report sets a placement, so the same "Move to folder" works on every row. The open folders are remembered per
 * person and per scope; a search or filter opens every folder that still holds a match and hides empty folders, and
 * does not overwrite the remembered layout.
 */
import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { reportFolderApi, type ReportFolder, type ReportFolderApi } from "../api/reportFolders";
import { LAYOUT_ORIGIN_LABEL, reportLayoutPath, type ReportLayoutApi, type ReportLayoutSummary } from "../api/reportLayouts";
import { reportPackPath, type ReportPackApi, type ReportPackSummary } from "../api/reportPacks";
import { reportDuplicateApi, type DuplicateResult, type ReportDuplicateApi } from "../api/reportDuplicate";
import { reportCopyApi, type CopyItems, type ReportCopyApi } from "../api/reportCopy";
import type { ReportPlacement, ReportPlacementApi } from "../api/reportPlacements";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useColumnChoice } from "../hooks/useColumnChoice";
import { useOpenFolders } from "../hooks/useOpenFolders";
import {
  allFolderIds, buildFolderTree, folderLevels, folderProblem, FOLDER_SEPARATOR, MAX_FOLDER_DEPTH, parentFolder, tidyFolder,
  type FolderNode,
} from "../utils/reportFolders";
import { copyCount, copyItems, isCopyable } from "../utils/reportCopySelection";
import {
  applySetupFilter, buildSetupRows, EMPTY_SETUP_FILTER, isFiltering, rowCan,
  type ReportSetupFilter, type ReportSetupRow, type SetupSourceFilter, type SetupStatusFilter, type SetupTypeFilter,
} from "../utils/reportSetupRows";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { Badge } from "./Badge";
import { ColumnChooser } from "./ColumnChooser";
import { ConfirmDialog } from "./ConfirmDialog";
import { FilterField, FilterPanel } from "./FilterPanel";
import { FolderTreeList, type FolderTreeChecks, type FolderTreeColumn } from "./FolderTreeList";
import { MenuButton } from "./MenuButton";
import { ReportCopyDialog } from "./ReportCopyDialog";
import { ReportDuplicateDialog } from "./ReportDuplicateDialog";
import { ReportFolderNameDialog } from "./ReportFolderNameDialog";
import { ReportLayoutFormModal } from "./ReportLayoutFormModal";
import { ReportMoveDialog } from "./ReportMoveDialog";
import { ReportPackFormModal } from "./ReportPackFormModal";
import { ReportKindIcon } from "./ReportKindIcon";
import { RestoreOrgDefaultsButton } from "./RestoreOrgDefaultsButton";
import { Spinner } from "./Spinner";

type Dialog =
  | { kind: "create-layout" }
  | { kind: "create-pack" }
  | { kind: "edit"; row: ReportSetupRow }
  | { kind: "delete"; row: ReportSetupRow }
  | { kind: "hide"; row: ReportSetupRow }
  | { kind: "move"; row: ReportSetupRow }
  | { kind: "copy-to-project"; items: CopyItems }
  | { kind: "duplicate"; row: ReportSetupRow }
  | { kind: "from-starter" }
  | { kind: "folder-add"; parent: string }
  | { kind: "folder-rename"; path: string }
  | { kind: "folder-delete"; path: string };

interface Loaded {
  placements: ReportPlacement[];
  layouts: ReportLayoutSummary[];
  packs: ReportPackSummary[];
  folders: ReportFolder[];
}

const FOLDER_TREE_PREFIX = "f";
/** Marks a ticked folder among the ticked rows' keys. */
const FOLDER_PICK = "folder:";

/** The columns shown until a person chooses: the type and folder are read from the icon and the nesting, the version from the designer. */
const DEFAULT_COLUMNS = ["status", "shared", "updated"];

/**
 * @param layoutApi The layout calls, bound to an organisation or a project.
 * @param packApi The pack calls, bound to the same scope.
 * @param placementApi The placement calls, bound to the same scope.
 * @param folderApi The folder calls for the same scope; the live ones when omitted.
 * @param copyApi The calls that copy reports to another project (a project's panel only); the live ones when omitted.
 * @param duplicateApi The calls that duplicate one report or start from a built-in starter; the live ones for the scope when omitted.
 */
export function ReportSetupPanel({
  layoutApi, packApi, placementApi, folderApi: folderApiProp, copyApi = reportCopyApi, duplicateApi: duplicateApiProp,
}: {
  layoutApi: ReportLayoutApi; packApi: ReportPackApi; placementApi: ReportPlacementApi; folderApi?: ReportFolderApi; copyApi?: ReportCopyApi;
  duplicateApi?: ReportDuplicateApi;
}) {
  const strings = useStrings();
  const text = strings.reportSetup;
  const copyText = strings.reportCopy;
  const { showToast } = useToast();
  const navigate = useNavigate();
  const scope = placementApi.scope;
  const inProject = scope.kind === "project";
  const folderApi = useMemo(() => folderApiProp ?? reportFolderApi(scope), [folderApiProp, scope]);
  const duplicateApi = useMemo(() => duplicateApiProp ?? reportDuplicateApi(scope), [duplicateApiProp, scope]);
  const [data, setData] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [filter, setFilter] = useState<ReportSetupFilter>(EMPTY_SETUP_FILTER);
  const [openIds, setFolderOpen] = useOpenFolders(`setup-${scope.kind}`);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());

  const reload = useCallback(async () => {
    try {
      const [placements, layouts, packs, folders] = await Promise.all([
        placementApi.list(), layoutApi.list(), packApi.list(),
        // The folder list only adds empty folders and says which folders can be renamed: the list works without it.
        folderApi.list().catch(() => [] as ReportFolder[]),
      ]);
      setData({ placements, layouts, packs, folders });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [placementApi, layoutApi, packApi, folderApi]);
  useLoadOnChange(reload, [scope.kind, scope.id]);

  const rows = useMemo(() => (data ? buildSetupRows(data.placements, data.layouts, data.packs) : []), [data]);
  const filtering = isFiltering(filter);
  const shown = useMemo(() => applySetupFilter(rows, filter), [rows, filter]);
  const folderPaths = useMemo(() => data?.folders.map((f) => f.path) ?? [], [data]);
  const ownedFolders = useMemo(() => new Set((data?.folders ?? []).filter((f) => f.own).map((f) => f.path.toLowerCase())), [data]);
  const tree = useMemo(
    () => buildFolderTree(shown, (r) => r.folder, (r) => r.title, (r) => r.key, FOLDER_TREE_PREFIX, filtering ? [] : folderPaths),
    [shown, filtering, folderPaths],
  );
  const expanded = useMemo(() => (filtering ? new Set(allFolderIds(tree)) : openIds), [filtering, tree, openIds]);
  const hiddenObjects = useMemo(() => rows.filter((r) => r.hidden && (r.layout || r.pack)), [rows]);

  /** The ticked folders, by path (a folder's tick is stored as `folder:<path>`). */
  const pickedFolders = useMemo(
    () => [...picked].filter((k) => k.startsWith(FOLDER_PICK)).map((k) => k.slice(FOLDER_PICK.length)).filter((path) => ownedFolders.has(path.toLowerCase())),
    [picked, ownedFolders],
  );
  const pickedItems = useMemo(() => copyItems(rows, picked, pickedFolders), [rows, picked, pickedFolders]);
  const checks = useMemo<FolderTreeChecks<ReportSetupRow> | undefined>(() => {
    if (!picking) return undefined;
    const below = (node: FolderNode<ReportSetupRow>): ReportSetupRow[] =>
      node.kind === "item" && node.item ? (isCopyable(node.item) ? [node.item] : []) : node.children.flatMap(below);
    return {
      state: (node) => {
        if (node.kind === "item") return picked.has(node.item?.key ?? "");
        const inside = below(node);
        if (inside.length === 0) return picked.has(`${FOLDER_PICK}${node.path}`);
        const ticked = inside.filter((r) => picked.has(r.key)).length;
        return ticked === inside.length ? true : ticked === 0 ? false : "mixed";
      },
      onChange: (node, checked) => setPicked((current) => {
        const next = new Set(current);
        const keys = node.kind === "item" ? [node.item?.key ?? ""] : [...below(node).map((r) => r.key), `${FOLDER_PICK}${node.path}`];
        for (const key of keys) {
          if (checked) next.add(key);
          else next.delete(key);
        }
        return next;
      }),
      label: (node) => copyText.tickLabel(node.name),
      disabled: (node) => node.kind === "item" && node.item !== undefined && !isCopyable(node.item),
    };
  }, [picking, picked, copyText]);

  const allColumns = useMemo<FolderTreeColumn<ReportSetupRow>[]>(() => [
    {
      id: "status", header: text.statusHeading, width: "minmax(5rem, 9rem)",
      render: (row) => {
        if (row.hidden) {
          const by = row.hiddenFrom && row.hiddenFrom !== scope.kind ? strings.reportPlacements.source[row.hiddenFrom] : null;
          return <Badge>{by ? strings.reportPlacements.hiddenBy(by) : strings.reportPlacements.hidden}</Badge>;
        }
        if (row.folder === row.defaultFolder) return null;
        const tier = row.folderFrom && row.folderFrom !== scope.kind && row.folderFrom !== "project" ? ` · ${strings.reportPlacements.source[row.folderFrom]}` : "";
        return <span className="text-muted">{text.movedFrom(row.defaultFolder)}{tier}</span>;
      },
    },
    ...(inProject
      ? [{
        id: "shared", header: text.sharedHeading, hideBelow: true,
        render: (row: ReportSetupRow) => (row.origin === "platform" || row.origin === "project" ? null : <Badge>{LAYOUT_ORIGIN_LABEL[row.origin]}</Badge>),
      }]
      : []),
    {
      id: "version", header: text.versionHeading, width: "5rem", hideBelow: true,
      sortValue: (row) => row.version ?? 0, render: (row) => row.version ?? "",
    },
    {
      id: "kind", header: text.kindHeading, width: "6rem", hideBelow: true,
      sortValue: (row) => strings.reportPicker.kind[row.shape], render: (row) => strings.reportPicker.kind[row.shape],
    },
    {
      id: "folder", header: text.folderHeading, hideBelow: true,
      sortValue: (row) => row.folder, render: (row) => row.folder,
    },
    {
      id: "updated", header: text.updatedHeading, width: "7rem", hideBelow: true,
      sortValue: (row) => row.updatedAt ?? "", render: (row) => (row.updatedAt ? new Date(row.updatedAt).toLocaleDateString() : ""),
    },
  ], [text, strings.reportPlacements, strings.reportPicker.kind, inProject, scope.kind]);
  const columnIds = useMemo(() => allColumns.map((c) => c.id), [allColumns]);
  const choice = useColumnChoice(`report_setup_${scope.kind}`, columnIds, DEFAULT_COLUMNS);
  const columns = useMemo(() => allColumns.filter((c) => choice.visible.includes(c.id)), [allColumns, choice.visible]);

  /** Runs a change, toasts its outcome and reloads; an error is toasted and leaves the list as it was. */
  async function run(action: () => Promise<string>) {
    try {
      showToast(await action());
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (failed && !data) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!data) return <Spinner />;

  const nounOf = (row: ReportSetupRow) => (row.type === "layout" ? strings.reportLayouts : row.type === "pack" ? strings.reportPacks : null);

  /** Opens the copy the server made: a layout in its designer, a pack in its editor, at the tier it landed in. */
  function openDuplicate(done: DuplicateResult) {
    setDialog(null);
    if (!done.new_id) return;
    const landed = done.target === "organization" && scope.kind === "project" ? { kind: "organization" as const, id: done.organization_id } : scope;
    navigate(done.kind === "pack" ? reportPackPath(landed, done.new_id) : reportLayoutPath(landed, done.new_id));
  }

  function open(row: ReportSetupRow) {
    if (row.layout) navigate(reportLayoutPath(scope, row.layout.id));
    else if (row.pack) navigate(reportPackPath(scope, row.pack.id));
    else setDialog({ kind: "move", row });
  }

  async function show(row: ReportSetupRow) {
    await run(async () => {
      if (row.layout) {
        await layoutApi.setHidden?.(row.layout.id, false);
        return strings.reportLayouts.restored;
      }
      if (row.pack) {
        await packApi.setHidden?.(row.pack.id, false);
        return strings.reportPacks.restored;
      }
      await placementApi.set({ report_key: row.key, hidden: row.hiddenFrom === "project" || !inProject ? null : false });
      return strings.reportPlacements.shown;
    });
  }

  async function hide(row: ReportSetupRow) {
    await run(async () => {
      if (row.layout) {
        await layoutApi.setHidden?.(row.layout.id, true);
        return strings.reportLayouts.hidden;
      }
      if (row.pack) {
        await packApi.setHidden?.(row.pack.id, true);
        return strings.reportPacks.hidden;
      }
      await placementApi.set({ report_key: row.key, hidden: true });
      return strings.reportPlacements.hiddenToast;
    });
  }

  async function remove(row: ReportSetupRow) {
    await run(async () => {
      if (row.layout) {
        await layoutApi.remove(row.layout.id);
        return strings.reportLayouts.deleted;
      }
      await packApi.remove((row.pack as ReportPackSummary).id);
      return strings.reportPacks.deleted;
    });
  }

  /** Moves an owned layout or pack by editing it, any other report by setting this scope's placement. */
  async function move(row: ReportSetupRow, folder: string) {
    await run(async () => {
      if (row.owned && row.layout) await layoutApi.update(row.layout.id, { folder });
      else if (row.owned && row.pack) await packApi.update(row.pack.id, { folder });
      else await placementApi.set({ report_key: row.key, folder });
      setDialog(null);
      return strings.reportPlacements.moved;
    });
  }

  function menuFor(row: ReportSetupRow): ActionMenuItem[] {
    const can = rowCan(row, inProject);
    const noun = nounOf(row);
    const items: ActionMenuItem[] = [];
    if (can.open) {
      const label = row.layout
        ? (row.owned ? strings.reportLayouts.open : strings.reportLayouts.view)
        : (row.owned ? strings.reportPacks.open : strings.reportPacks.view);
      items.push({ key: "open", label, onSelect: () => open(row) });
    }
    if (can.editDetails) items.push({ key: "edit", label: (noun ?? strings.reportLayouts).editDetails, onSelect: () => setDialog({ kind: "edit", row }) });
    items.push({ key: "move", label: strings.reportPlacements.move, onSelect: () => setDialog({ kind: "move", row }) });
    if (can.copy && noun) items.push({ key: "copy", label: noun.makeCopy, onSelect: () => setDialog({ kind: "duplicate", row }) });
    if (inProject && isCopyable(row) && (row.layout || row.pack)) {
      items.push({
        key: "copy-to-project", label: copyText.startRow,
        onSelect: () => setDialog({ kind: "copy-to-project", items: copyItems(rows, new Set([row.key]), []) }),
      });
    }
    if (can.resetFolder) {
      items.push({
        key: "reset-folder", label: strings.reportPlacements.resetFolder,
        onSelect: () => void run(async () => {
          await placementApi.set({ report_key: row.key, folder: null });
          return strings.reportPlacements.folderReset;
        }),
      });
    }
    if (can.resetVisibility) {
      items.push({
        key: "reset-visibility", label: strings.reportPlacements.resetVisibility,
        onSelect: () => void run(async () => {
          await placementApi.set({ report_key: row.key, hidden: null });
          return strings.reportPlacements.visibilityReset;
        }),
      });
    }
    if (can.show) items.push({ key: "show", label: strings.reportPlacements.show, onSelect: () => void show(row) });
    if (can.hide) items.push({ key: "hide", label: noun ? noun.hide : strings.reportPlacements.hide, danger: true, onSelect: () => setDialog({ kind: "hide", row }) });
    if (can.delete && noun) items.push({ key: "delete", label: noun.delete, danger: true, onSelect: () => setDialog({ kind: "delete", row }) });
    return items;
  }

  function folderMenu(node: FolderNode<ReportSetupRow>): ActionMenuItem[] {
    const items: ActionMenuItem[] = [];
    if (folderLevels(node.path).length < MAX_FOLDER_DEPTH) {
      items.push({ key: "add", label: strings.reportFolders.newInside, onSelect: () => setDialog({ kind: "folder-add", parent: node.path }) });
    }
    if (ownedFolders.has(node.path.toLowerCase())) {
      items.push({ key: "rename", label: strings.reportFolders.rename, onSelect: () => setDialog({ kind: "folder-rename", path: node.path }) });
      items.push({ key: "delete", label: strings.reportFolders.delete, danger: true, onSelect: () => setDialog({ kind: "folder-delete", path: node.path }) });
    }
    return items;
  }

  const newItems: ActionMenuItem[] = [
    { key: "layout", label: text.newLayout, onSelect: () => setDialog({ kind: "create-layout" }) },
    { key: "pack", label: text.newPack, onSelect: () => setDialog({ kind: "create-pack" }) },
    { key: "starter", label: strings.reportDuplicate.fromStarter, onSelect: () => setDialog({ kind: "from-starter" }) },
    { key: "folder", label: text.newFolder, onSelect: () => setDialog({ kind: "folder-add", parent: "" }) },
  ];

  const set = (patch: Partial<ReportSetupFilter>) => setFilter({ ...filter, ...patch });
  const folderLabel = (path: string) => folderLevels(path).slice(-1)[0] ?? path;

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{inProject ? text.projectDescription : text.orgDescription}</p>
      <div className="row">
        <MenuButton primary label={text.new} menuLabel={text.newMenu} items={newItems} />
        {layoutApi.addStarters && (
          <button
            type="button" className="btn"
            onClick={() => void run(async () => {
              const added = (await layoutApi.addStarters?.()) ?? [];
              return added.length > 0 ? strings.reportLayouts.startersAdded(added) : strings.reportLayouts.startersNone;
            })}
          >
            {text.addStarters}
          </button>
        )}
        {inProject && (layoutApi.restore || packApi.restore) && (
          <RestoreOrgDefaultsButton
            hidden={hiddenObjects.map((r) => ({ id: r.key, name: r.title }))}
            noun={text.restoreNoun}
            onRestore={async (keys) => {
              const ids = (prefix: string) => keys.filter((k) => k.startsWith(prefix)).map((k) => k.slice(prefix.length));
              if (ids("layout:").length > 0) await layoutApi.restore?.(ids("layout:"));
              if (ids("pack:").length > 0) await packApi.restore?.(ids("pack:"));
              showToast(text.restored);
              await reload();
            }}
          />
        )}
        {inProject && !picking && (
          <button type="button" className="btn" onClick={() => setPicking(true)}>{copyText.start}</button>
        )}
        <span style={{ marginInlineStart: "auto" }}>
          <ColumnChooser
            columns={allColumns.map((c) => ({ id: c.id, label: c.header }))} visible={choice.visible}
            onToggle={choice.toggle} onReset={choice.reset} isDefault={choice.isDefault} alwaysOn={strings.folderTreeList.nameHeader}
          />
        </span>
      </div>
      {picking && (
        <div className="row" role="group" aria-label={copyText.start} style={{ alignItems: "center" }}>
          <span className="text-muted">{copyText.pickIntro}</span>
          <strong aria-live="polite">{copyText.selected(copyCount(pickedItems))}</strong>
          <button
            type="button" className="btn btn-primary" disabled={copyCount(pickedItems) === 0}
            onClick={() => setDialog({ kind: "copy-to-project", items: pickedItems })}
          >
            {copyText.copy}
          </button>
          <button type="button" className="btn" onClick={() => { setPicking(false); setPicked(new Set()); }}>{copyText.cancelPick}</button>
        </div>
      )}
      <FilterPanel
        sectionKey={`reportSetup.${scope.kind}`} layout="top" matching={shown.length} total={rows.length}
        search={filter.search} onSearchChange={(search) => set({ search })} searchPlaceholder={text.searchPlaceholder} searchAriaLabel={text.searchLabel}
      >
        <FilterField label={text.typeFilter}>
          <select className="input" value={filter.type} onChange={(e) => set({ type: e.target.value as SetupTypeFilter })}>
            <option value="">{text.any}</option>
            <option value="report">{text.typeReport}</option>
            <option value="sheet">{text.typeSheet}</option>
            <option value="pack">{text.typePack}</option>
          </select>
        </FilterField>
        <FilterField label={text.statusFilter}>
          <select className="input" value={filter.status} onChange={(e) => set({ status: e.target.value as SetupStatusFilter })}>
            <option value="">{text.any}</option>
            <option value="moved">{text.statusMoved}</option>
            <option value="hidden">{text.statusHidden}</option>
          </select>
        </FilterField>
        {inProject && (
          <FilterField label={text.sourceFilter}>
            <select className="input" value={filter.source} onChange={(e) => set({ source: e.target.value as SetupSourceFilter })}>
              <option value="">{text.any}</option>
              <option value="own">{text.sourceOwn}</option>
              <option value="shared">{text.sourceShared}</option>
            </select>
          </FilterField>
        )}
      </FilterPanel>
      <FolderTreeList
        nodes={tree}
        label={text.listLabel}
        expanded={expanded}
        onToggle={(id, isOpen) => {
          if (!filtering) setFolderOpen(id, isOpen);
        }}
        itemView={(row) => ({ icon: <ReportKindIcon kind={row.shape} />, iconLabel: strings.reportPicker.kind[row.shape], description: row.description })}
        onOpenItem={open}
        columns={columns}
        folderBadge={(node) => text.folderCount(node.count)}
        checks={checks}
        renderItemActions={(row) => <ActionMenu triggerLabel={strings.reportPlacements.actionsFor(row.title)} items={menuFor(row)} />}
        renderFolderActions={(node) => {
          const items = folderMenu(node);
          return items.length > 0 ? <ActionMenu triggerLabel={text.folderActionsFor(node.name)} items={items} /> : null;
        }}
        emptyText={rows.length > 0 ? text.noMatch : text.empty}
      />

      {dialog?.kind === "copy-to-project" && (
        <ReportCopyDialog
          api={copyApi} sourceProjectId={scope.id} items={dialog.items} onClose={() => setDialog(null)}
          onCopied={() => { setPicking(false); setPicked(new Set()); }}
        />
      )}
      {dialog?.kind === "duplicate" && (dialog.row.layout || dialog.row.pack) && (
        <ReportDuplicateDialog
          api={duplicateApi} onClose={() => setDialog(null)} onDuplicated={openDuplicate}
          source={dialog.row.layout
            ? { kind: "layout", id: dialog.row.layout.id, name: dialog.row.layout.name }
            : { kind: "pack", id: (dialog.row.pack as ReportPackSummary).id, name: (dialog.row.pack as ReportPackSummary).name }}
        />
      )}
      {dialog?.kind === "from-starter" && (
        <ReportDuplicateDialog api={duplicateApi} source={{ kind: "starter" }} onClose={() => setDialog(null)} onDuplicated={openDuplicate} />
      )}
      {dialog?.kind === "create-layout" && (
        <ReportLayoutFormModal
          api={layoutApi} folderApi={folderApi} onFoldersChanged={() => void reload()} onClose={() => setDialog(null)}
          onSaved={(saved) => {
            showToast(strings.reportLayouts.created);
            navigate(reportLayoutPath(scope, saved.id));
          }}
        />
      )}
      {dialog?.kind === "create-pack" && (
        <ReportPackFormModal
          api={packApi} folderApi={folderApi} onFoldersChanged={() => void reload()} onClose={() => setDialog(null)}
          onSaved={(saved) => {
            showToast(strings.reportPacks.created);
            navigate(reportPackPath(scope, saved.id));
          }}
        />
      )}
      {dialog?.kind === "edit" && dialog.row.layout && (
        <ReportLayoutFormModal
          api={layoutApi} folderApi={folderApi} onFoldersChanged={() => void reload()} layout={dialog.row.layout} onClose={() => setDialog(null)}
          onSaved={() => {
            showToast(strings.reportLayouts.detailsSaved);
            void reload();
          }}
        />
      )}
      {dialog?.kind === "edit" && dialog.row.pack && (
        <ReportPackFormModal
          api={packApi} folderApi={folderApi} onFoldersChanged={() => void reload()} pack={dialog.row.pack} onClose={() => setDialog(null)}
          onSaved={() => {
            showToast(strings.reportPacks.detailsSaved);
            void reload();
          }}
        />
      )}
      {dialog?.kind === "move" && (
        <ReportMoveDialog
          title={dialog.row.title}
          folder={dialog.row.owned ? (dialog.row.layout?.folder ?? dialog.row.pack?.folder ?? "") : dialog.row.folder}
          noneLabel={dialog.row.owned ? strings.reportFolders.none : undefined}
          folders={folderPaths} folderApi={folderApi} onChanged={() => void reload()} onClose={() => setDialog(null)}
          onSave={(folder) => move(dialog.row, folder)}
        />
      )}
      {dialog?.kind === "delete" && nounOf(dialog.row) && (
        <ConfirmDialog
          title={nounOf(dialog.row)?.deleteTitle(dialog.row.title) ?? ""}
          message={(dialog.row.layout ? strings.reportLayouts : strings.reportPacks).deleteMessage(dialog.row.version ?? 1)}
          confirmLabel={nounOf(dialog.row)?.delete ?? ""}
          requireTypedText={dialog.row.title}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const row = dialog.row;
            setDialog(null);
            void remove(row);
          }}
        />
      )}
      {dialog?.kind === "hide" && (
        <ConfirmDialog
          title={(nounOf(dialog.row) ?? strings.reportPlacements).hideTitle(dialog.row.title)}
          message={(nounOf(dialog.row) ?? strings.reportPlacements).hideMessage}
          confirmLabel={nounOf(dialog.row)?.hideConfirm ?? strings.reportPlacements.hide}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const row = dialog.row;
            setDialog(null);
            void hide(row);
          }}
        />
      )}
      {dialog?.kind === "folder-add" && (
        <ReportFolderNameDialog
          mode="add" parent={dialog.parent} onClose={() => setDialog(null)}
          onSubmit={async (name) => {
            const path = tidyFolder(dialog.parent === "" ? name : `${dialog.parent}${FOLDER_SEPARATOR}${name}`);
            const problem = folderProblem(path);
            if (problem) throw new Error(problem);
            await folderApi.add(path);
            showToast(strings.reportFolders.added(path));
            await reload();
          }}
        />
      )}
      {dialog?.kind === "folder-rename" && (
        <ReportFolderNameDialog
          mode="rename" parent={dialog.path} initialName={folderLabel(dialog.path)} onClose={() => setDialog(null)}
          onSubmit={async (name) => {
            const change = await folderApi.rename(dialog.path, name);
            showToast(strings.reportFolders.renamed(change.path ?? name, change.layouts + change.packs + change.placements));
            await reload();
          }}
        />
      )}
      {dialog?.kind === "folder-delete" && (
        <ConfirmDialog
          title={strings.reportFolders.deleteTitle(dialog.path)}
          message={strings.reportFolders.deleteMessage(parentFolder(dialog.path))}
          confirmLabel={strings.reportFolders.delete}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const path = dialog.path;
            setDialog(null);
            void run(async () => {
              const change = await folderApi.remove(path);
              return strings.reportFolders.deleted(path, change.layouts + change.packs + change.placements);
            });
          }}
        />
      )}
    </div>
  );
}
