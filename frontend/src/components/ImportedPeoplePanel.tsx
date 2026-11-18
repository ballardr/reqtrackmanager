/**
 * Module: components/ImportedPeoplePanel
 *
 * The organisation administrator's list of imported people: the stand-ins a bundle import created for people who are
 * not members (`PrincipalBadge` marks them "Imported" wherever they appear).
 *
 * Responsibilities: list them with whether anything still refers to them and whether they are due for removal,
 * anonymise one, remove an unused one, and set the retention age that decides which are listed as due. It owns its
 * own fetch and mutations; the page only places it.
 *
 * Design: nothing is removed automatically. Removal is offered only for an unused person (the server refuses
 * otherwise), and each action confirms first (style guide confirmation tiers).
 */
import { useState } from "react";

import { api } from "../api/client";
import type { ImportedPeopleList, ImportedPersonRow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { useTableSort } from "../hooks/useTableSort";
import type { SortValue } from "../utils/sortRows";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { TextField } from "./FormFields";

const EMPTY_PEOPLE: ImportedPersonRow[] = [];

/** Sortable value of each sortable column; status orders due for removal, then in use, then unused. */
const PERSON_SORT_VALUES: Record<string, (person: ImportedPersonRow) => SortValue> = {
  name: (p) => p.display_name,
  added: (p) => p.created_at,
  status: (p) => (p.due_for_removal ? 0 : p.in_use ? 1 : 2),
};

/**
 * @param orgId The organisation whose imported people are listed.
 */
export function ImportedPeoplePanel({ orgId }: { orgId: string }) {
  const strings = useStrings();
  const text = strings.importPeople;
  const run = useMutation();
  const [list, setList] = useState<ImportedPeopleList | null>(null);
  const [retention, setRetention] = useState("");
  const [retentionDirty, setRetentionDirty] = useState(false);
  const [confirm, setConfirm] = useState<{ kind: "anonymise" | "remove"; person: ImportedPersonRow } | null>(null);

  async function load() {
    try {
      const found = await api.get<ImportedPeopleList>(`/api/v1/orgs/${orgId}/imported-people`);
      setList(found);
      if (!retentionDirty) setRetention(found.retention_days ? String(found.retention_days) : "");
    } catch {
      setList({ retention_days: null, people: [] });
    }
  }
  useLoadOnChange(load, [orgId]);

  async function saveRetention() {
    const days = retention.trim() ? Number(retention) : null;
    const saved = await run(
      () => api.put(`/api/v1/orgs/${orgId}/advanced-settings`, { imported_person_retention_days: days }),
      { success: text.retentionSaved, failure: text.retentionFailed },
    );
    if (saved) {
      setRetentionDirty(false);
      void load();
    }
  }

  async function apply() {
    if (!confirm) return;
    const { kind, person } = confirm;
    setConfirm(null);
    const done = await run(
      () => kind === "anonymise"
        ? api.post(`/api/v1/orgs/${orgId}/imported-people/${person.id}/anonymise`)
        : api.delete(`/api/v1/orgs/${orgId}/imported-people/${person.id}`),
      kind === "anonymise" ? { success: text.anonymised, failure: text.anonymiseFailed } : { success: text.removed, failure: text.removeFailed },
    );
    if (done) void load();
  }

  const table = useTableSort(list?.people ?? EMPTY_PEOPLE, PERSON_SORT_VALUES);
  const columns: DirectoryColumn<ImportedPersonRow>[] = [
    { key: "name", label: text.columnName, sortable: true, render: (p) => p.display_name },
    { key: "added", label: text.columnAdded, sortable: true, render: (p) => new Date(p.created_at).toLocaleDateString() },
    {
      key: "status", label: text.columnStatus, sortable: true,
      render: (p) => p.due_for_removal
        ? <Badge tone="warning">{text.statusDue}</Badge>
        : <Badge tone={p.in_use ? undefined : "muted"}>{p.in_use ? text.statusInUse : text.statusUnused}</Badge>,
    },
    {
      key: "actions", label: "",
      render: (p) => (
        <span className="row" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
          <button className="btn" onClick={() => setConfirm({ kind: "anonymise", person: p })} disabled={p.display_name === "Former person"}>
            {text.anonymise}
          </button>
          {!p.in_use && <button className="btn btn-danger" onClick={() => setConfirm({ kind: "remove", person: p })}>{text.remove}</button>}
        </span>
      ),
    },
  ];

  return (
    <div className="stack" data-testid="imported-people-panel">
      <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)" }}>
        <TextField
          label={text.retentionLabel} help={strings.help.importedRetention} value={retention}
          onChange={(next) => { setRetentionDirty(true); setRetention(next); }}
          inputProps={{ type: "number", min: 1, max: 3650, style: { maxWidth: 160 } }}
        />
        <button className="btn btn-primary" onClick={() => void saveRetention()}>{text.retentionSave}</button>
      </div>
      <DirectoryTable
        ariaLabel={text.tableLabel} columns={columns} rows={table.rows} rowKey={(p) => p.id}
        sort={table.sort} onSort={table.onSort}
        emptyState={list === null ? "" : text.panelEmpty}
      />
      {confirm && (
        <ConfirmDialog
          title={confirm.kind === "anonymise" ? text.anonymiseTitle(confirm.person.display_name) : text.removeTitle(confirm.person.display_name)}
          message={confirm.kind === "anonymise" ? text.anonymiseMessage : text.removeMessage}
          confirmLabel={confirm.kind === "anonymise" ? text.anonymise : text.remove}
          onConfirm={() => void apply()} onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
