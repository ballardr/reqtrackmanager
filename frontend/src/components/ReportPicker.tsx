/**
 * Module: components/ReportPicker
 *
 * The Reports page's report chooser: a button showing the current report that opens a dialog to find another by
 * search, by type (reports, sheets, packs), by folder or from the person's favourites.
 *
 * Responsibilities:
 * - List every offered report in a tree of folders (`utils/reportFolders`), nested up to three levels, with a
 *   Favourites folder first; search and the type filter open every folder that still holds a match.
 * - Star and unstar a report (the star is on the right of its row): favourites are kept per person in their
 *   `ui_preferences` bag (`report_favourites`, by the report's stable placement key), so they follow the person across
 *   browsers.
 * - Remember which folders were open, per person and per picker (`report_picker_folders`, keyed by the `pickerId` each
 *   host passes), so reopening shows the same folders open; a picker opens fully collapsed the first time.
 * - Report the choice through `onSelect`; the host (`ReportCatalogue`) keeps the selection in the URL.
 *
 * `ReportPickerPanel` is the same search, filter and folder list (`FolderTreeList`, a file manager's list view) without the dialog, for another dialog to embed.
 *
 * Design decisions: a dialog rather than a native `<select>` because a tree, search and stars do not fit one; the
 * saved expansion state is overridden (everything open) only while a filter is active and is never written then, so
 * clearing the search returns to the person's own layout. Folder ids are derived from folder paths, so an id saved for
 * a folder that no longer exists is harmless; the list is capped. Pure presentation over already-loaded items.
 *
 * Dependencies: `Modal`, `FolderTreeList`, `useUiPreference`.
 */
import { ChevronDown, Star } from "lucide-react";
import { useMemo, useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { useOpenFolders } from "../hooks/useOpenFolders";
import { useUiPreference } from "../hooks/useUiPreference";
import { allFolderIds, buildFolderTree, type FolderNode } from "../utils/reportFolders";
import { FolderTreeList } from "./FolderTreeList";
import { ReportKindIcon, type ReportKind } from "./ReportKindIcon";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

export type ReportPickerKind = ReportKind;

/** One report the picker offers. */
export interface ReportPickerItem {
  /** The value `onSelect` receives (the URL's `report` parameter). */
  id: string;
  title: string;
  description: string;
  /** The folder path it files under (`""` for the top level). */
  folder: string;
  kind: ReportPickerKind;
  /** The stable key favourites are stored under; falls back to `id`. */
  favouriteKey?: string;
}

const FAVOURITES_KEY = "report_favourites";
const MAX_FAVOURITES = 100;
const FAVOURITES_PREFIX = "fav";
const TREE_PREFIX = "f";
const FAVOURITES_FOLDER_ID = `${FAVOURITES_PREFIX}:favourites`;

type KindFilter = "all" | ReportPickerKind;

/** The type filter's options: reports, sheets and packs, each matching one `kind`. */
function useKindOptions(): { value: KindFilter; label: string }[] {
  const text = useStrings().reportPicker;
  return [
    { value: "all", label: text.all },
    { value: "report", label: text.reports },
    { value: "sheet", label: text.sheets },
    { value: "pack", label: text.packs },
  ];
}

/**
 * @param pickerId Names this picker for the folders it remembers (one per place it is used).
 * @param items Everything on offer.
 * @param selectedId The chosen item's id.
 * @param onSelect Called with the id of the report the person picked (the dialog then closes).
 */
export function ReportPicker({
  pickerId, items, selectedId, onSelect,
}: { pickerId: string; items: ReportPickerItem[]; selectedId: string; onSelect: (id: string) => void }) {
  const text = useStrings().reportPicker;
  const [open, setOpen] = useState(false);
  const selected = items.find((item) => item.id === selectedId) ?? items[0];
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <span style={{ fontWeight: 600 }}>{text.label}</span>
      <button
        type="button" className="btn" aria-haspopup="dialog" aria-label={text.triggerName(selected.title)}
        style={{ justifyContent: "space-between", textAlign: "left", width: "100%" }}
        onClick={() => setOpen(true)}
      >
        <span>
          <span>{selected.title}</span>
          {selected.folder && <span className="text-muted"> · {selected.folder}</span>}
        </span>
        <ChevronDown aria-hidden="true" />
      </button>
      <span className="text-muted" style={{ fontSize: "0.9rem" }}>{selected.description}</span>
      {open && (
        <ReportPickerDialog
          pickerId={pickerId} items={items} selectedId={selected.id}
          onSelect={(id) => {
            setOpen(false);
            onSelect(id);
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

function favouriteKeyOf(item: ReportPickerItem): string {
  return item.favouriteKey ?? item.id;
}

function ReportPickerDialog({
  pickerId, items, selectedId, onSelect, onClose,
}: { pickerId: string; items: ReportPickerItem[]; selectedId: string; onSelect: (id: string) => void; onClose: () => void }) {
  const text = useStrings().reportPicker;
  return (
    <Modal title={text.title} onClose={onClose} size="lg">
      <ReportPickerPanel pickerId={pickerId} items={items} selectedId={selectedId} onSelect={onSelect} />
    </Modal>
  );
}

/**
 * The picker's search, type filter and folder tree without a dialog around it, so another dialog can embed it
 * (the record lists' "Download report" does).
 *
 * @param pickerId Names this picker for the folders it remembers (one per place it is used).
 * @param items Everything on offer.
 * @param selectedId The highlighted item's id (`""` for none).
 * @param onSelect Called with the id of the report the person picked.
 */
export function ReportPickerPanel({
  pickerId, items, selectedId, onSelect,
}: { pickerId: string; items: ReportPickerItem[]; selectedId: string; onSelect: (id: string) => void }) {
  const text = useStrings().reportPicker;
  const kindOptions = useKindOptions();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [favourites, setFavourites] = useUiPreference<string[]>(FAVOURITES_KEY, []);
  const favouriteSet = useMemo(() => new Set(favourites), [favourites]);

  const needle = search.trim().toLowerCase();
  const filtering = needle !== "" || kind !== "all";
  const shown = useMemo(
    () => items.filter((item) => (
      (kind === "all" || item.kind === kind)
      && (needle === "" || `${item.title} ${item.description} ${item.folder}`.toLowerCase().includes(needle))
    )),
    [items, kind, needle],
  );
  const tree = useMemo(() => {
    const folders = buildFolderTree(shown, (i) => i.folder, (i) => i.title, (i) => i.id, TREE_PREFIX);
    const starred = shown.filter((i) => favouriteSet.has(favouriteKeyOf(i)));
    if (starred.length === 0) return folders;
    const favouritesFolder: FolderNode<ReportPickerItem> = {
      id: FAVOURITES_FOLDER_ID, kind: "folder", name: text.favourites, path: "", count: starred.length,
      children: buildFolderTree(starred, () => "", (i) => i.title, (i) => i.id, FAVOURITES_PREFIX), pinned: true,
    };
    return [favouritesFolder, ...folders];
  }, [shown, favouriteSet, text.favourites]);

  const [openIds, setFolderOpen] = useOpenFolders(pickerId);
  const expanded = useMemo(() => (filtering ? new Set(allFolderIds(tree)) : openIds), [filtering, tree, openIds]);

  function toggleFavourite(item: ReportPickerItem) {
    const key = favouriteKeyOf(item);
    const next = favouriteSet.has(key) ? favourites.filter((k) => k !== key) : [...favourites, key].slice(-MAX_FAVOURITES);
    setFavourites(next);
  }

  return (
    <div className="stack">
      <div className="row" style={{ alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <TextField helpNotNeeded label={text.search} value={search} onChange={setSearch} inputProps={{ autoFocus: true }} />
        </div>
        <LabeledSelect helpNotNeeded label={text.show} value={kind} onChange={(v) => setKind(v as KindFilter)} options={kindOptions} placeholder={null} />
      </div>
      {shown.length === 0 ? (
        <p className="text-muted">{text.noMatch}</p>
      ) : (
        <FolderTreeList
          nodes={tree}
          label={text.listLabel}
          expanded={expanded}
          onToggle={(id, isOpen) => {
            if (!filtering) setFolderOpen(id, isOpen);
          }}
          itemView={(item) => ({ icon: <ReportKindIcon kind={item.kind} />, iconLabel: text.kind[item.kind], description: item.description })}
          isSelected={(item) => item.id === selectedId}
          onOpenItem={(item) => onSelect(item.id)}
          folderBadge={(node) => text.folderCount(node.count)}
          renderItemActions={(item) => (
            <FavouriteStar item={item} favourite={favouriteSet.has(favouriteKeyOf(item))} onToggle={toggleFavourite} />
          )}
        />
      )}
    </div>
  );
}

function FavouriteStar({
  item, favourite, onToggle,
}: { item: ReportPickerItem; favourite: boolean; onToggle: (item: ReportPickerItem) => void }) {
  const text = useStrings().reportPicker;
  const label = favourite ? text.removeFavourite(item.title) : text.addFavourite(item.title);
  return (
    <button
      type="button" className="btn" style={{ padding: "0.15rem" }} aria-pressed={favourite} aria-label={label} title={label}
      onClick={() => onToggle(item)}
    >
      <Star aria-hidden="true" fill={favourite ? "currentColor" : "none"} />
    </button>
  );
}
