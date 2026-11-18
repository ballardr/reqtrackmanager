/**
 * Module: modules/architecture/BaselineRecordsCard
 *
 * The records of one type in a baseline, as a card with a sortable table (code, name, status). A row opens the record's content
 * as it stood (`onOpen`). The sort is local to the card, since the baseline page shows one card per type.
 */
import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { RecordCode } from "../../components/RecordCode";
import { useTableSort } from "../../hooks/useTableSort";
import type { SortValue } from "../../utils/sortRows";
import { ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, BASELINE_TYPE_LABEL, type BaselineRecord } from "./types";

const SORT_VALUES: Record<string, (row: BaselineRecord) => SortValue> = {
  code: (r) => r.code,
  name: (r) => r.name,
  status: (r) => (r.status ? ARCHITECTURE_STATUS_LABEL[r.status] : null),
};

/**
 * @param itemType The record type (`architecture_element` and so on); it names the card.
 * @param records The baseline's records of that type.
 * @param onOpen Called with the record whose row was chosen.
 */
export function BaselineRecordsCard({
  itemType, records, onOpen,
}: { itemType: string; records: BaselineRecord[]; onOpen: (record: BaselineRecord) => void }) {
  const label = BASELINE_TYPE_LABEL[itemType] ?? itemType;
  const { rows, sort, onSort } = useTableSort(records, SORT_VALUES);
  const columns: DirectoryColumn<BaselineRecord>[] = [
    { key: "code", label: "Code", sortable: true, render: (r) => <RecordCode code={r.code} /> },
    { key: "name", label: "Name", sortable: true, render: (r) => r.name },
    {
      key: "status", label: "Status", sortable: true,
      render: (r) => (r.status ? <Badge tone={ARCHITECTURE_STATUS_TONE[r.status]}>{ARCHITECTURE_STATUS_LABEL[r.status]}</Badge> : "—"),
    },
  ];
  return (
    <DetailCard heading={`${label} (${records.length})`}>
      <DirectoryTable
        ariaLabel={label} columns={columns} rows={rows} rowKey={(r) => r.id} sort={sort} onSort={onSort} onRowClick={onOpen}
        emptyState={<p className="text-muted">None in this baseline.</p>}
      />
    </DetailCard>
  );
}
