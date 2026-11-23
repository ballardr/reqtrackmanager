/**
 * Module: modules/architecture/OrgElementsPanel
 *
 * The organisation's own elements and collections, on Org Resources: shared platform blocks (an
 * identity service, a standard board) that projects use once a collection holding them is granted to the project or to a
 * group. Two tabs: *Elements* (a table with create, edit, status and archive; an element's code is qualified by the
 * organisation code) and *Collections* (`CollectionsPanel`). The Elements tab has one primary button (New element) and one
 * actions menu (folders, then Export and Import), and each row one actions menu; folders and Show archived are in the filter panel. An organisation element has no project, so it takes no tags,
 * links or placements, and its parent and children must also be organisation elements. Controls render for any
 * organisation administrator; the server enforces the Architecture Org Admin role.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { ActionMenu, type ActionMenuItem } from "../../components/ActionMenu";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { ListActions, ListActionsMenu, ListMenuItems } from "../../components/ListActions";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Badge } from "../../components/Badge";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { addSortParams, useListSort } from "../../hooks/useListSort";
import { SortField } from "../../components/SortField";
import { sortRows } from "../../utils/sortRows";
import { connectionTypeApi, elementTypeApi, orgElementApi, orgSymbolUrl, symbolApi } from "./api";
import { ELEMENT_SORT_KEYS, elementSortValues } from "./architectureSort";
import { diffElementFields, elementCodeRecord, valuesFromElement } from "./architectureFields";
import { CollectionsPanel } from "./CollectionsPanel";
import { ElementFormModal, type ElementCreateExtras } from "./ElementFormModal";
import { useFolderListControls } from "./useFolderListControls";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureElement,
  type ArchitectureSymbol, type ConnectionType, type ElementFieldValues, type ElementType,
} from "./types";

type Tab = "elements" | "collections";

const NO_ELEMENTS: ArchitectureElement[] = [];
/** The organisation list has no Parent column, so only the columns it draws sort. */
const ORG_ELEMENT_SORT_VALUES = elementSortValues(() => "");

/** @param orgId The organisation whose own elements and collections are managed. */
export function OrgElementsPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const calls = useMemo(() => orgElementApi(orgId), [orgId]);
  const scope = useMemo(() => ({ kind: "org" as const, organizationId: orgId }), [orgId]);
  const [tab, setTab] = useState<Tab>("elements");
  const [elements, setElements] = useState<ArchitectureElement[] | null>(null);
  const [elementTypes, setElementTypes] = useState<ElementType[]>([]);
  const [connectionTypes, setConnectionTypes] = useState<ConnectionType[]>([]);
  const [symbols, setSymbols] = useState<ArchitectureSymbol[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ArchitectureElement | "new" | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  const folders = useFolderListControls({ organizationId: orgId }, "element", "elements", reload, false);

  useEffect(() => {
    let live = true;
    Promise.all([
      calls.list({ include_archived: showArchived }),
      elementTypeApi.orgList(orgId), connectionTypeApi.orgList(orgId), symbolApi.orgList(orgId),
      api.get<OrgUser[]>(`/api/v1/orgs/${orgId}/users`).catch(() => [] as OrgUser[]),
    ])
      .then(([list, types, connections, found, users]) => {
        if (!live) return;
        setElements(list);
        setElementTypes(types);
        setConnectionTypes(connections);
        setSymbols(found);
        setOrgUsers(users);
        setLoadError(null);
      })
      .catch((err) => { if (live) setLoadError(toErrorMessage(err, "Could not load the organisation's elements.")); });
    return () => { live = false; };
  }, [calls, orgId, showArchived, refresh]);

  const listSort = useListSort("org_architecture_elements", ELEMENT_SORT_KEYS, "code", true);
  const sortedRows = sortRows(elements ?? NO_ELEMENTS, listSort.sort, ORG_ELEMENT_SORT_VALUES);
  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (elements === null) return <Spinner />;

  const shown = sortedRows.filter((e) => folders.matches(e.folder_path));
  const exportFilters = new URLSearchParams();
  folders.addParams(exportFilters);
  if (showArchived) exportFilters.set("include_archived", "true");
  addSortParams(exportFilters, listSort.sort);

  async function save(values: ElementFieldValues, extras: ElementCreateExtras) {
    setFormError(null);
    try {
      if (editing === "new") {
        await calls.create({ ...values, activate: extras.activate, ports: extras.ports });
        showToast("Element created.");
      } else if (editing) {
        const changed = diffElementFields(valuesFromElement(editing), values);
        if (Object.keys(changed).length > 0) await calls.update(editing.id, editing.version, changed);
        showToast(Object.keys(changed).length > 0 ? "Element updated." : "Nothing changed.");
      }
      setEditing(null);
      reload();
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not save the element."));
    }
  }

  async function act(action: () => Promise<unknown>, done: string) {
    try {
      await action();
      showToast(done);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not change the element."), "error");
    }
  }

  const columns: DirectoryColumn<ArchitectureElement>[] = [
    { key: "code", label: "Code", sortable: true, render: (e) => <ScopedRecordCode record={elementCodeRecord(e)} /> },
    { key: "name", label: "Name", sortable: true, render: (e) => e.name },
    { key: "type", label: "Type", sortable: true, render: (e) => e.element_type_name },
    { key: "folder", label: "Folder", sortable: true, render: (e) => e.folder_path ?? "—" },
    { key: "owner", label: "Owner", sortable: true, render: (e) => <PrincipalBadge principal={e.owner} placeholder="—" /> },
    {
      key: "status", label: "Status", sortable: true,
      render: (e) => (
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <Badge tone={ARCHITECTURE_STATUS_TONE[e.status]}>{ARCHITECTURE_STATUS_LABEL[e.status]}</Badge>
          {e.is_archived && <Badge tone="muted">Archived</Badge>}
        </span>
      ),
    },
    {
      key: "actions", label: "Actions",
      render: (e) => {
        const items: ActionMenuItem[] = [
          { key: "edit", label: "Edit", onSelect: () => { setFormError(null); setEditing(e); } },
        ];
        if (e.allowed_status_moves.length > 0) {
          items.push({
            key: "status", label: "Change status", onSelect: () => undefined,
            children: e.allowed_status_moves.map((next): ActionMenuItem => ({
              key: `status:${next}`,
              label: `Move from ${ARCHITECTURE_STATUS_LABEL[e.status]} to ${ARCHITECTURE_STATUS_LABEL[next]}`,
              onSelect: () => void act(() => calls.setStatus(e.id, e.version, next), `Element moved to ${ARCHITECTURE_STATUS_LABEL[next]}.`),
            })),
          });
        }
        items.push({
          key: "archive", label: e.is_archived ? "Unarchive" : "Archive",
          onSelect: () => void act(() => (e.is_archived ? calls.unarchive(e.id) : calls.archive(e.id)), e.is_archived ? "Element unarchived." : "Element archived."),
        });
        return <ActionMenu triggerLabel={`Actions for ${e.name}`} items={items} />;
      },
    },
  ];

  return (
    <div className="stack">
      <Tabs
        idPrefix="org-architecture"
        tabs={[{ key: "elements", label: "Elements" }, { key: "collections", label: "Collections" }]}
        active={tab}
        onChange={setTab}
      />
      <div className="stack" {...tabPanelProps("org-architecture", tab)}>
        {tab === "elements" ? (
          <>
            <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start", alignItems: "center" }}>
              <button className="btn btn-primary" onClick={() => { setFormError(null); setEditing("new"); }}>New element</button>
              <ListActionsMenu>
                <ListMenuItems items={folders.menuItems} />
                <ListActions organizationId={orgId} recordType="architecture_element" filters={exportFilters.toString()} onImported={reload} />
              </ListActionsMenu>
            </div>
            <div className="side-grid">
              <div className="stack">
                {folders.bar}
                <DirectoryTable
                  ariaLabel="Organisation elements" columns={columns} rows={shown} rowKey={(e) => e.id}
                  sort={listSort.sort} onSort={listSort.onHeaderSort}
                  selection={{ selected: folders.selected, onChange: folders.setSelected, label: (e) => `Select ${e.unique_code}`, allLabel: "Select all elements" }}
                      emptyState={<p className="text-muted">{elements.length === 0 ? "The organisation has no elements of its own yet." : "No elements match the chosen folder."}</p>}
                />
              </div>
              <FilterPanel sectionKey="architecture.org-elements" total={shown.length}>
                <SortField list={listSort} columns={columns} />
                <FilterCheckbox label="Show archived" checked={showArchived} onChange={setShowArchived} />
                {folders.panel}
              </FilterPanel>
            </div>
          </>
        ) : (
          <CollectionsPanel scope={scope} elements={elements.filter((e) => !e.is_archived)} orgUsers={orgUsers} organizationId={orgId} />
        )}
      </div>
      {folders.dialog}
      {editing && (
        <ElementFormModal
          initial={editing === "new" ? undefined : editing}
          elementTypes={elementTypes} connectionTypes={connectionTypes} candidates={elements}
          symbols={symbols} symbolUrl={(id) => orgSymbolUrl(orgId, id)} orgUsers={orgUsers} organizationId={orgId}
          error={formError} onCancel={() => { setEditing(null); setFormError(null); }} onSave={save} onSymbolsChanged={reload}
        />
      )}
    </div>
  );
}
