/**
 * Module: modules/architecture/OrgElementsPanel
 *
 * The organisation's own elements and collections, on the organisation administration page: shared platform blocks (an
 * identity service, a standard board) that projects use once a collection holding them is granted to the project or to a
 * group. Two tabs: *Elements* (a table with create, edit, status and archive; an element's code is qualified by the
 * organisation code) and *Collections* (`CollectionsPanel`). An organisation element has no project, so it takes no tags,
 * links or placements, and its parent and children must also be organisation elements. Controls render for any
 * organisation administrator; the server enforces the Architecture Org Admin role.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { CheckboxField } from "../../components/FormFields";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Badge } from "../../components/Badge";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { connectionTypeApi, elementTypeApi, orgElementApi, orgSymbolUrl, symbolApi } from "./api";
import { diffElementFields, elementCodeRecord, valuesFromElement } from "./architectureFields";
import { ArchitectureStatusControls } from "./ArchitectureStatusControls";
import { CollectionsPanel } from "./CollectionsPanel";
import { ElementFormModal, type ElementCreateExtras } from "./ElementFormModal";
import { useFolderListControls } from "./useFolderListControls";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureElement, type ArchitectureRecordStatus,
  type ArchitectureSymbol, type ConnectionType, type ElementFieldValues, type ElementType,
} from "./types";

type Tab = "elements" | "collections";

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

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (elements === null) return <Spinner />;

  const shown = elements.filter((e) => folders.matches(e.folder_path));

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
    { key: "code", label: "Code", render: (e) => <ScopedRecordCode record={elementCodeRecord(e)} /> },
    { key: "name", label: "Name", render: (e) => e.name },
    { key: "type", label: "Type", render: (e) => e.element_type_name },
    { key: "folder", label: "Folder", render: (e) => e.folder_path ?? "—" },
    { key: "owner", label: "Owner", render: (e) => <PrincipalBadge principal={e.owner} placeholder="—" /> },
    {
      key: "status", label: "Status",
      render: (e) => (
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <Badge tone={ARCHITECTURE_STATUS_TONE[e.status]}>{ARCHITECTURE_STATUS_LABEL[e.status]}</Badge>
          {e.is_archived && <Badge tone="muted">Archived</Badge>}
        </span>
      ),
    },
    {
      key: "actions", label: "Actions",
      render: (e) => (
        <span className="row" style={{ gap: "var(--space-2)" }}>
          <ArchitectureStatusControls
            status={e.status}
            moves={e.allowed_status_moves}
            onMove={(next: ArchitectureRecordStatus) => act(() => calls.setStatus(e.id, e.version, next), `Element moved to ${ARCHITECTURE_STATUS_LABEL[next]}.`)}
          />
          <button className="btn" aria-label={`Edit ${e.name}`} onClick={() => { setFormError(null); setEditing(e); }}>Edit</button>
          <button
            className="btn" aria-label={`${e.is_archived ? "Unarchive" : "Archive"} ${e.name}`}
            onClick={() => void act(() => (e.is_archived ? calls.unarchive(e.id) : calls.archive(e.id)), e.is_archived ? "Element unarchived." : "Element archived.")}
          >
            {e.is_archived ? "Unarchive" : "Archive"}
          </button>
        </span>
      ),
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
            <div className="row" style={{ gap: "var(--space-4)", alignItems: "center" }}>
              <button className="btn btn-primary" onClick={() => { setFormError(null); setEditing("new"); }}>New element</button>
              <CheckboxField helpNotNeeded label="Show archived" checked={showArchived} onChange={setShowArchived} />
            </div>
            <div className="side-grid">
              <div className="stack">
                {folders.bar}
                <DirectoryTable
                  ariaLabel="Organisation elements" columns={columns} rows={shown} rowKey={(e) => e.id}
                  selection={{ selected: folders.selected, onChange: folders.setSelected, label: (e) => `Select ${e.unique_code}`, allLabel: "Select all elements" }}
                      emptyState={<p className="text-muted">{elements.length === 0 ? "The organisation has no elements of its own yet." : "No elements match the chosen folder."}</p>}
                />
              </div>
              <div className="stack">{folders.panel}</div>
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
          error={formError} onCancel={() => { setEditing(null); setFormError(null); }} onSave={save}
        />
      )}
    </div>
  );
}
