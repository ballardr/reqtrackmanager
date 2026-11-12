/**
 * Module: modules/architecture/ConnectionDetailPage
 *
 * One connection as a routed page (`/projects/:projectId/modules/architecture/connections/:connectionId`, also the
 * target other records' links follow): its type, protocol, both ends with their ports (each end links to its element), and
 * description. The Links panel and the activity timeline sit in the aside and tags in the header. An end the viewer can no
 * longer read shows only its code. Edits send only the changed fields with the version they were based on (a stale
 * version, 409, is shown in the dialog); the server enforces the Architect role and a refusal appears as a message.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { DetailLayout } from "../../components/DetailLayout";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordField, RecordFieldGroup } from "../../components/RecordDetailParts";
import { RecordHeader } from "../../components/RecordHeader";
import { RecordTags } from "../../components/RecordTags";
import { Spinner } from "../../components/Spinner";
import { useArchiveAction, useConfirmedAction } from "../../components/useConfirmedAction";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectConnectionApi, projectElementApi } from "./api";
import { diffConnectionFields, valuesFromConnection } from "./architectureFields";
import { ArchitectureStatusControls } from "./ArchitectureStatusControls";
import { ConnectionFormModal } from "./ConnectionFormModal";
import { ConnectionEnd } from "./connectionEnds";
import { useArchitectureReference } from "./useArchitectureReference";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureConnection, type ArchitectureElement,
  type ArchitectureRecordStatus, type ConnectionFieldValues,
} from "./types";

export function ConnectionDetailPage() {
  const { projectId = "", connectionId = "" } = useParams<{ projectId: string; connectionId: string }>();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const reference = useArchitectureReference(projectId);
  const connectionApi = projectConnectionApi(projectId);

  const [connection, setConnection] = useState<ArchitectureConnection | null>(null);
  const [elements, setElements] = useState<ArchitectureElement[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    if (!projectId || !connectionId) return;
    let live = true;
    projectConnectionApi(projectId).get(connectionId)
      .then((found) => { if (live) { setConnection(found); setLoadError(null); } })
      .catch((err) => { if (live) setLoadError(toErrorMessage(err, "This connection could not be found, or you do not have access to it.")); });
    const api = projectElementApi(projectId);
    Promise.all([api.list({ open_only: true }), api.listShared({ open_only: true })])
      .then(([own, shared]) => { if (live) setElements([...own, ...shared]); })
      .catch(() => { if (live) setElements([]); });
    return () => { live = false; };
  }, [projectId, connectionId, refreshKey]);

  const archive = useArchiveAction({
    noun: "Connection",
    isArchived: connection?.is_archived ?? false,
    hidden: !connection,
    archiveBody: "This connection will no longer appear in lists or diagrams. Nothing is deleted, and it remains available for historical purposes.",
    onToggle: async () => {
      if (!connection) return;
      try {
        setConnection(await (connection.is_archived ? connectionApi.unarchive(connection.id) : connectionApi.archive(connection.id)));
        showToast(connection.is_archived ? "Connection unarchived." : "Connection archived.");
      } catch (err) {
        showToast(toErrorMessage(err, "Could not update this connection."), "error");
      }
    },
  });
  const remove = useConfirmedAction(connection ? {
    label: "Delete permanently", danger: true, title: "Delete this connection permanently?",
    message: "The connection is removed from the model and from diagrams. This cannot be undone. A connection that other records use cannot be deleted; retire it instead.",
    confirmLabel: "Delete", requireTypedText: connection.unique_code,
    onConfirm: async () => {
      try {
        await connectionApi.remove(connection.id);
        showToast("Connection deleted.");
        navigate(`/projects/${projectId}/modules/architecture/connections`);
      } catch (err) {
        showToast(toErrorMessage(err, "Could not delete this connection."), "error");
      }
    },
  } : null);

  if (!projectId || !connectionId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (connection === null || !reference.loaded) return <Spinner />;

  async function saveEdit(values: ConnectionFieldValues) {
    if (!connection) return;
    setFormError(null);
    const changed = diffConnectionFields(valuesFromConnection(connection), values);
    if (Object.keys(changed).length === 0) {
      showToast("Nothing changed.");
      setEditing(false);
      return;
    }
    try {
      setConnection(await connectionApi.update(connection.id, connection.version, changed));
      showToast("Connection updated.");
      setEditing(false);
      reload();
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this connection."));
    }
  }

  async function moveTo(status: ArchitectureRecordStatus) {
    if (!connection) return;
    try {
      setConnection(await connectionApi.setStatus(connection.id, connection.version, status));
      showToast(`Connection moved to ${ARCHITECTURE_STATUS_LABEL[status]}.`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not change the status."), "error");
    }
  }

  const endLink = (id: string, locked: boolean) => (locked ? null : `/projects/${projectId}/modules/architecture/elements/${id}`);
  const sourceHref = endLink(connection.source_element_id, connection.source_locked);
  const targetHref = endLink(connection.target_element_id, connection.target_locked);

  return (
    <DetailLayout
      activity={<RecordActivity projectId={projectId} artefactType="architecture_connection" artefactId={connection.id} refreshToken={recordActivityKey(connection)} />}
      aside={<ArtefactLinksPanel projectId={projectId} artefactType="architecture_connection" artefactId={connection.id} onChanged={reload} />}
    >
      <RecordHeader
        recordLabel="Connection"
        title={connection.name || `${connection.source_element_name} → ${connection.target_element_name}`}
        code={connection.unique_code}
        tags={<RecordTags projectId={projectId} artefactType="architecture_connection" artefactId={connection.id} />}
        back={{ to: `/projects/${projectId}/modules/architecture/connections`, label: "Connections" }}
        badges={
          <>
            {connection.is_archived && <Badge tone="muted">Archived</Badge>}
            <Badge tone={ARCHITECTURE_STATUS_TONE[connection.status]}>{ARCHITECTURE_STATUS_LABEL[connection.status]}</Badge>
          </>
        }
        version={connection.version}
        subtitle={<>{connection.connection_type_name}{connection.protocol ? ` · ${connection.protocol}` : ""}</>}
        onEdit={connection.is_archived ? undefined : () => setEditing(true)}
        actions={[archive.item, remove.item]}
        transitions={<ArchitectureStatusControls status={connection.status} onMove={moveTo} />}
      />
      {archive.dialog}
      {remove.dialog}
      <div className="stack">
        <DetailCard>
          <div className="row" style={{ gap: "2rem", flexWrap: "wrap" }}>
            <RecordFieldGroup helpNotNeeded label="Source">
              {sourceHref ? <Link to={sourceHref}><ConnectionEnd connection={connection} end="source" /></Link> : <ConnectionEnd connection={connection} end="source" />}
              {connection.source_shared && <Badge tone="info">Shared</Badge>}
            </RecordFieldGroup>
            <RecordFieldGroup helpNotNeeded label="Target">
              {targetHref ? <Link to={targetHref}><ConnectionEnd connection={connection} end="target" /></Link> : <ConnectionEnd connection={connection} end="target" />}
              {connection.target_shared && <Badge tone="info">Shared</Badge>}
            </RecordFieldGroup>
            <RecordFieldGroup helpNotNeeded label="Direction">
              <span>{connection.directional ? "One-way, source to target" : "Two-way"}</span>
            </RecordFieldGroup>
          </div>
          <RecordField label="Description" value={connection.description || "—"} />
        </DetailCard>
      </div>

      {editing && (
        <ConnectionFormModal
          initial={connection} connectionTypes={reference.connectionTypes} elementTypes={reference.elementTypes} elements={elements}
          projectId={projectId} error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }} onSave={saveEdit}
        />
      )}
    </DetailLayout>
  );
}
