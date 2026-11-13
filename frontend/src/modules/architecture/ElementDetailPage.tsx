/**
 * Module: modules/architecture/ElementDetailPage
 *
 * One element as a routed page (`/projects/:projectId/modules/architecture/elements/:elementId`, also the target other
 * records' links follow): its type, parent, owner and symbol, its ports (edited here one change at a time), its child
 * elements, the connections it takes part in, and the collections it is shared through. The Links panel and the activity
 * timeline sit in the aside, and tags in the header.
 *
 * An element another owner shares with the project is read-only here (no Edit, status, ports or delete); the server also
 * refuses a change to it. Edits send only the changed fields with the version they were based on, and a stale version
 * (409) is shown in the dialog. Every mutating control renders for any member; the server enforces the Architect role and a
 * refusal appears as a message.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { DetailLayout } from "../../components/DetailLayout";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordField, RecordFieldGroup } from "../../components/RecordDetailParts";
import { RecordHeader } from "../../components/RecordHeader";
import { RecordTags } from "../../components/RecordTags";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Spinner } from "../../components/Spinner";
import { useArchiveAction, useConfirmedAction } from "../../components/useConfirmedAction";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useRecordOwnerCode } from "../../hooks/useOrganizationCode";
import { architectureTabPath } from "./architectureTabs";
import { projectConnectionApi, projectElementApi, projectSymbolUrl } from "./api";
import { diffElementFields, elementCodeRecord, valuesFromElement } from "./architectureFields";
import { ArchitectureStatusControls } from "./ArchitectureStatusControls";
import { useCreateConnection } from "./useCreateConnection";
import { useCreateElement } from "./useCreateElement";
import { ConnectionFormModal } from "./ConnectionFormModal";
import { ElementFormModal } from "./ElementFormModal";
import { ElementSharingCard } from "./ElementSharingCard";
import { ARCHITECTURE_HELP } from "./help";
import { PortList } from "./PortList";
import { SymbolImage } from "./SymbolImage";
import { useArchitectureReference } from "./useArchitectureReference";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE,
  type ArchitectureConnection, type ArchitectureElement, type ArchitectureRecordStatus, type ElementFieldValues,
} from "./types";

export function ElementDetailPage() {
  const { projectId = "", elementId = "" } = useParams<{ projectId: string; elementId: string }>();
  const { showToast } = useToast();
  const reference = useArchitectureReference(projectId);
  const elementApi = projectElementApi(projectId);
  const navigate = useNavigate();

  const [element, setElement] = useState<ArchitectureElement | null>(null);
  const [owned, setOwned] = useState<ArchitectureElement[]>([]);
  const [shared, setShared] = useState<ArchitectureElement[]>([]);
  const [connections, setConnections] = useState<ArchitectureConnection[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [addingChild, setAddingChild] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const connectionForm = useCreateConnection(projectId, () => { setConnecting(false); reload(); });
  const ownerCode = useRecordOwnerCode(element ? elementCodeRecord(element) : {});
  const childForm = useCreateElement(projectId, () => { setAddingChild(false); reload(); });

  useEffect(() => {
    if (!projectId || !elementId) return;
    let live = true;
    const api = projectElementApi(projectId);
    api.get(elementId)
      .then((found) => { if (live) { setElement(found); setLoadError(null); } })
      .catch((err) => { if (live) setLoadError(toErrorMessage(err, "This element could not be found, or you do not have access to it.")); });
    api.list({ include_archived: false }).then((list) => { if (live) setOwned(list); }).catch(() => { if (live) setOwned([]); });
    api.listShared().then((list) => { if (live) setShared(list); }).catch(() => { if (live) setShared([]); });
    projectConnectionApi(projectId).list({ element_id: elementId, include_archived: false })
      .then((list) => { if (live) setConnections(list); }).catch(() => { if (live) setConnections([]); });
    return () => { live = false; };
  }, [projectId, elementId, refreshKey]);

  const archive = useArchiveAction({
    noun: "Element",
    isArchived: element?.is_archived ?? false,
    hidden: !element || element.shared,
    archiveBody: "This element will no longer appear in lists or pickers. Nothing is deleted, and it remains available for historical purposes.",
    onToggle: async () => {
      if (!element) return;
      try {
        setElement(await (element.is_archived ? elementApi.unarchive(element.id) : elementApi.archive(element.id)));
        showToast(element.is_archived ? "Element unarchived." : "Element archived.");
      } catch (err) {
        showToast(toErrorMessage(err, "Could not update this element."), "error");
      }
    },
  });
  const remove = useConfirmedAction(element && !element.shared ? {
    label: "Delete permanently", danger: true, title: "Delete this element permanently?",
    message: "The element, its ports and its place in diagrams are removed. This cannot be undone. An element that other records use cannot be deleted; retire it instead.",
    confirmLabel: "Delete", requireTypedText: element.name,
    onConfirm: async () => {
      try {
        await elementApi.remove(element.id);
        showToast("Element deleted.");
        navigate(architectureTabPath(projectId, "elements"));
      } catch (err) {
        showToast(toErrorMessage(err, "Could not delete this element."), "error");
      }
    },
  } : null);

  if (!projectId || !elementId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (element === null || !reference.loaded || reference.project === null) return <Spinner />;
  const project = reference.project;
  const readOnly = element.shared || element.project_id !== projectId;
  const children = owned.filter((e) => e.parent_id === element.id);
  const parent = [...owned, ...shared].find((e) => e.id === element.parent_id);
  const typeIcon = element.effective_symbol_id;

  async function saveEdit(values: ElementFieldValues) {
    if (!element) return;
    setFormError(null);
    const changed = diffElementFields(valuesFromElement(element), values);
    if (Object.keys(changed).length === 0) {
      showToast("Nothing changed.");
      setEditing(false);
      return;
    }
    try {
      setElement(await elementApi.update(element.id, element.version, changed));
      showToast("Element updated.");
      setEditing(false);
      reload();
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this element."));
    }
  }

  async function moveTo(status: ArchitectureRecordStatus) {
    if (!element) return;
    try {
      setElement(await elementApi.setStatus(element.id, element.version, status));
      showToast(`Element moved to ${ARCHITECTURE_STATUS_LABEL[status]}.`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not change the status."), "error");
    }
  }

  const portsApi = {
    add: async (values: Parameters<typeof elementApi.addPort>[1]) => { await elementApi.addPort(element.id, values); reload(); },
    change: async (portId: string, change: Parameters<typeof elementApi.updatePort>[2]) => { await elementApi.updatePort(element.id, portId, change); reload(); },
    remove: async (portId: string) => { await elementApi.removePort(element.id, portId); reload(); },
  };

  return (
    <DetailLayout
      activity={<RecordActivity projectId={projectId} artefactType="architecture_element" artefactId={element.id} refreshToken={recordActivityKey(element)} />}
      aside={<ArtefactLinksPanel projectId={projectId} artefactType="architecture_element" artefactId={element.id} onChanged={reload} />}
    >
      <RecordHeader
        recordLabel="Element"
        title={element.name}
        code={element.unique_code}
        codeOwner={ownerCode}
        tagsInline tags={<RecordTags inline projectId={projectId} artefactType="architecture_element" artefactId={element.id} />}
        back={{ to: architectureTabPath(projectId, "elements"), label: "Elements" }}
        badges={
          <>
            {element.shared && <Badge tone="info">Shared</Badge>}
            {element.is_archived && <Badge tone="muted">Archived</Badge>}
            <Badge tone={ARCHITECTURE_STATUS_TONE[element.status]}>{ARCHITECTURE_STATUS_LABEL[element.status]}</Badge>
          </>
        }
        version={element.version}
        subtitle={
          <>{element.element_type_name} · Owner: <PrincipalBadge principal={element.owner} placeholder="None" /></>
        }
        onEdit={readOnly || element.is_archived ? undefined : () => setEditing(true)}
        actions={[archive.item, remove.item]}
        stateMenu={readOnly ? undefined : <ArchitectureStatusControls status={element.status} moves={element.allowed_status_moves} onMove={moveTo} />}
      />
      {archive.dialog}
      {remove.dialog}
      <div className="stack">
        <DetailCard>
          {element.description && <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{element.description}</p>}
          <div className="row" style={{ gap: "2rem", flexWrap: "wrap" }}>
            <RecordFieldGroup help={ARCHITECTURE_HELP.elementParent} label="Parent">
              {parent ? <Link to={`/projects/${projectId}/modules/architecture/elements/${parent.id}`}>{parent.name}</Link> : <span className="text-muted">{element.parent_id ? "Not visible" : "Top level"}</span>}
            </RecordFieldGroup>
            <RecordFieldGroup help={ARCHITECTURE_HELP.elementSymbol} label="Symbol">
              {typeIcon ? <SymbolImage src={projectSymbolUrl(projectId, typeIcon)} alt={`Symbol of ${element.name}`} size={36} /> : <span className="text-muted">Drawn as the type's shape</span>}
            </RecordFieldGroup>
          </div>
          {!element.description && <RecordField label="Description" value="—" />}
        </DetailCard>

        <DetailCard heading="Ports">
          <PortList
            ports={element.ports} connectionTypes={reference.connectionTypes} readOnly={readOnly || element.is_archived}
            onAdd={portsApi.add} onChange={portsApi.change} onRemove={portsApi.remove}
          />
        </DetailCard>

        <DetailCard heading="Child elements" action={readOnly ? undefined : <button className="btn" onClick={() => { childForm.clearError(); setAddingChild(true); }}>Add child</button>}>
          {children.length === 0 ? <p className="text-muted" style={{ margin: 0 }}>No child elements.</p> : (
            <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
              {children.map((c) => (
                <li key={c.id}>
                  <Link to={`/projects/${projectId}/modules/architecture/elements/${c.id}`}>
                    <ScopedRecordCode record={elementCodeRecord(c)} /> {c.name}
                  </Link>{" "}
                  <span className="text-muted">{c.element_type_name}</span>{" "}
                  <Badge tone={ARCHITECTURE_STATUS_TONE[c.status]}>{ARCHITECTURE_STATUS_LABEL[c.status]}</Badge>
                </li>
              ))}
            </ul>
          )}
        </DetailCard>

        <DetailCard heading="Connections" action={<button className="btn" onClick={() => { connectionForm.clearError(); setConnecting(true); }}>New connection</button>}>
          {connections.length === 0 ? <p className="text-muted" style={{ margin: 0 }}>No connections.</p> : (
            <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
              {connections.map((c) => (
                <li key={c.id}>
                  <Link to={`/projects/${projectId}/modules/architecture/connections/${c.id}`}>
                    <ScopedRecordCode record={{ unique_code: c.unique_code, from_project_code: c.from_project_code }} /> {c.name || `${c.source_element_name} → ${c.target_element_name}`}
                  </Link>{" "}
                  <span className="text-muted">{c.connection_type_name} · {c.source_element_name} → {c.target_element_name}</span>
                </li>
              ))}
            </ul>
          )}
        </DetailCard>

        <ElementSharingCard projectId={projectId} element={element} />
      </div>

      {editing && (
        <ElementFormModal
          initial={element} elementTypes={reference.elementTypes} connectionTypes={reference.connectionTypes} candidates={owned}
          symbols={reference.symbols} symbolUrl={(id) => projectSymbolUrl(projectId, id)} orgUsers={reference.orgUsers}
          organizationId={project.organization_id} projectId={projectId} error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }} onSave={saveEdit}
        />
      )}
      {addingChild && (
        <ElementFormModal
          elementTypes={reference.elementTypes} connectionTypes={reference.connectionTypes} candidates={owned}
          symbols={reference.symbols} symbolUrl={(id) => projectSymbolUrl(projectId, id)} orgUsers={reference.orgUsers}
          organizationId={project.organization_id} projectId={projectId} defaultParentId={element.id} error={childForm.error}
          onCancel={() => { setAddingChild(false); childForm.clearError(); }} onSave={childForm.create}
        />
      )}
      {connecting && (
        <ConnectionFormModal
          connectionTypes={reference.connectionTypes} elementTypes={reference.elementTypes} elements={[...owned, ...shared]}
          projectId={projectId} defaultSourceId={element.id} error={connectionForm.error}
          onCancel={() => { setConnecting(false); connectionForm.clearError(); }} onSave={connectionForm.create}
        />
      )}
    </DetailLayout>
  );
}
