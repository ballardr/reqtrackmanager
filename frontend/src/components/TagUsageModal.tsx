/**
 * Module: components/TagUsageModal
 *
 * The dialog that shows where one tag is used, opened from the record count in the Used on column of
 * the Tags page (`TagAdminPanel`), so the secondary answer is not a permanent section of the page.
 *
 * Responsibilities:
 * - List, per kind of record, how many records carry the tag and when it was last used, from the usage
 *   tables the panel already loaded (no request of its own).
 * - Offer "Reclassify" for one kind of record when the vocabulary is editable; the panel closes this
 *   dialog and opens its reclassify dialog.
 *
 * Shared by the organisation and project Tags pages through `TagAdminPanel`.
 */
import type { Tag, TagUsage, TagUsageRow } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { useTableSort } from "../hooks/useTableSort";
import type { SortValue } from "../utils/sortRows";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { Modal } from "./Modal";
import { TagChip } from "./TagChip";

/** One kind of record in which the tag is used. */
interface TagUsageLine {
  artefactType: string;
  label: string;
  row: TagUsageRow;
}

/** Sortable value of each sortable column. */
const LINE_SORT_VALUES: Record<string, (line: TagUsageLine) => SortValue> = {
  type: (line) => line.label,
  count: (line) => line.row.count,
  last: (line) => line.row.last_used,
};

/**
 * @param tag The tag whose usage is shown.
 * @param usage The usage tables of the vocabulary; only the rows of `tag` are shown.
 * @param editable Whether the vocabulary may be changed here (a list inherited from a parent project may not).
 * @param onReclassify Called with the kind of record to reclassify the tag's records in.
 * @param onClose Closes the dialog.
 */
export function TagUsageModal({
  tag, usage, editable, onReclassify, onClose,
}: {
  tag: Tag;
  usage: TagUsage;
  editable: boolean;
  onReclassify: (artefactType: string) => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.tags.admin;
  const lines: TagUsageLine[] = usage.tables.flatMap((table) =>
    table.rows.filter((row) => row.tag_id === tag.id).map((row) => ({ artefactType: table.artefact_type, label: table.label, row })),
  );
  const table = useTableSort(lines, LINE_SORT_VALUES);
  const columns: DirectoryColumn<TagUsageLine>[] = [
    { key: "type", label: text.recordTypeHeading, sortable: true, render: (line) => line.label },
    { key: "count", label: text.usedHeading, sortable: true, render: (line) => text.recordsCount(line.row.count) },
    {
      key: "last",
      label: text.lastUsedHeading,
      sortable: true,
      render: (line) => (line.row.last_used ? new Date(line.row.last_used).toLocaleDateString() : ""),
    },
    {
      key: "actions",
      label: <span className="sr-only">{strings.common.moreOptions}</span>,
      render: (line) => editable ? (
        <button
          type="button"
          className="btn btn-sm"
          aria-label={`${text.reclassify(tag.name)} (${line.label})`}
          onClick={() => onReclassify(line.artefactType)}
        >
          {text.reclassifyButton}
        </button>
      ) : null,
    },
  ];
  return (
    <Modal title={text.usageTitle(tag.name)} onClose={onClose}>
      <div className="stack">
        <TagChip tag={tag} />
        <DirectoryTable
          ariaLabel={text.usageTitle(tag.name)}
          columns={columns}
          rows={table.rows}
          sort={table.sort}
          onSort={table.onSort}
          rowKey={(line) => line.artefactType}
          emptyState={<p className="text-muted">{text.usageEmpty}</p>}
        />
      </div>
    </Modal>
  );
}
