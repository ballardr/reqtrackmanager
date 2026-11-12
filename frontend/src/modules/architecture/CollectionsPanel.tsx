/**
 * Module: modules/architecture/CollectionsPanel
 *
 * Manages the collections of a project or an organisation: named sets of its elements that are shared with other
 * projects and groups. Each collection shows its members (the tops of the subtrees shared; their children go with them)
 * and its grants (a project, optionally with every project nested under it, or a group). Recipients can read, place,
 * connect to, allocate to and link the shared elements but never change them, which the grant control's help states.
 * Granting reaches outside the owning project, so the server checks the target is in the same organisation and audits
 * every change; its refusal is shown here. Nothing about a collection is shown by name outside this panel.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type { PrincipalRef, ProjectListItem } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FormActions } from "../../components/FormActions";
import { CheckboxField, TextAreaField, TextField } from "../../components/FormFields";
import { FieldCaption } from "../../components/FieldHelp";
import { InlineSelect, LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { PrincipalPicker } from "../../components/PrincipalPicker";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useRecordCode } from "../../hooks/useRecordCode";
import { orgCollectionApi, projectCollectionApi } from "./api";
import { ARCHITECTURE_HELP } from "./help";
import type { TypesScope } from "./ArchitectureTypesPanel";
import type { ArchitectureCollection, ArchitectureElement, CollectionMember } from "./types";
import type { OrgUser } from "../../api/types";

type GrantTarget = "project" | "group";

/** The collection's name and description in a dialog (create and edit). */
function CollectionFormModal({
  initial, error, onCancel, onSave,
}: {
  initial?: ArchitectureCollection;
  error: string | null;
  onCancel: () => void;
  onSave: (values: { name: string; description: string }) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  return (
    <Modal title={initial ? `Edit ${initial.name}` : "New collection"} onClose={onCancel}>
      <div className="stack">
        <TextField helpNotNeeded required label="Name" value={name} onChange={setName} />
        <TextAreaField helpNotNeeded label="Description" value={description} onChange={setDescription} />
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave({ name: name.trim(), description })} saveDisabled={name.trim() === ""} />
      </div>
    </Modal>
  );
}

/** One collection: members, grants and the controls to change them. */
function CollectionCard({
  collection, scope, elements, orgUsers, organizationId, projects, onChanged, onEdit, onDelete,
}: {
  collection: ArchitectureCollection;
  scope: TypesScope;
  elements: ArchitectureElement[];
  orgUsers: OrgUser[];
  organizationId: string;
  projects: ProjectListItem[];
  onChanged: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { showToast } = useToast();
  const formatCode = useRecordCode();
  const scopeId = scope.kind === "project" ? scope.projectId : scope.organizationId;
  const calls = useMemo(
    () => (scope.kind === "project" ? projectCollectionApi(scopeId) : orgCollectionApi(scopeId)),
    [scope.kind, scopeId],
  );
  const [members, setMembers] = useState<CollectionMember[] | null>(null);
  const [target, setTarget] = useState<GrantTarget>("project");
  const [grantProject, setGrantProject] = useState("");
  const [grantGroup, setGrantGroup] = useState<PrincipalRef | null>(null);
  const [descendants, setDescendants] = useState(false);

  useEffect(() => {
    let live = true;
    calls.members(collection.id).then((list) => { if (live) setMembers(list); }).catch(() => { if (live) setMembers([]); });
    return () => { live = false; };
  }, [calls, collection.id, collection.member_count]);

  async function run(action: () => Promise<unknown>, done: string) {
    try {
      await action();
      showToast(done);
      onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not change the collection."), "error");
    }
  }

  const memberIds = new Set((members ?? []).map((m) => m.element_id));
  const addable = elements.filter((e) => !memberIds.has(e.id) && !e.shared);
  const grantReady = target === "project" ? grantProject !== "" : grantGroup !== null;

  return (
    <section className="card stack" aria-label={collection.name}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="detail-card__title">{collection.name}</h2>
        <span className="row">
          <button className="btn" onClick={onEdit}>Edit</button>
          <button className="btn btn-danger" onClick={onDelete}>Delete</button>
        </span>
      </div>
      {collection.description && <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{collection.description}</p>}

      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <FieldCaption label="Elements shared" help={ARCHITECTURE_HELP.collectionMembers} />
        {members === null ? <Spinner /> : members.length === 0 ? <p className="text-muted">No elements in this collection.</p> : (
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
            {members.map((m) => (
              <li key={m.element_id} className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
                <span>{formatCode.code(m.unique_code)} {m.name}</span>
                <button className="btn btn-sm" aria-label={`Remove ${m.name} from ${collection.name}`}
                  onClick={() => void run(() => calls.removeMember(collection.id, m.element_id), "Element removed from the collection.")}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <InlineSelect
          ariaLabel={`Add an element to ${collection.name}`} value="" placeholder="Add an element…" autoWidth
          options={addable.map((e) => ({ value: e.id, label: `${formatCode.code(e.unique_code)} ${e.name}` }))}
          onChange={(next) => next && void run(() => calls.addMembers(collection.id, [next]), "Element added to the collection.")}
        />
      </div>

      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <FieldCaption label="Shared with" help={ARCHITECTURE_HELP.collectionGrant} />
        {collection.grants.length === 0 ? <p className="text-muted">Not shared with anyone yet.</p> : (
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
            {collection.grants.map((g) => {
              const name = g.group ? `${g.group.label} (group)` : `${g.project_name ?? "Project"}${g.project_code ? ` (${g.project_code})` : ""}`;
              return (
                <li key={g.id} className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
                  <span>{name}{g.include_descendants ? " and nested projects" : ""}</span>
                  <button className="btn btn-sm" aria-label={`Stop sharing ${collection.name} with ${name}`}
                    onClick={() => void run(() => calls.removeGrant(collection.id, g.id), "Sharing removed.")}>
                    Remove
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <div className="row" style={{ gap: "var(--space-3)", alignItems: "flex-end", flexWrap: "wrap" }}>
          <LabeledSelect
            helpNotNeeded label="Share with" value={target} placeholder={null} autoWidth
            options={[{ value: "project", label: "A project" }, { value: "group", label: "A group" }]}
            onChange={(next) => setTarget(next as GrantTarget)}
          />
          {target === "project" ? (
            <>
              <LabeledSelect
                helpNotNeeded label="Project" value={grantProject} placeholder="Choose a project" autoWidth
                options={projects.map((p) => ({ value: p.id, label: `${p.name} (${p.code})` }))} onChange={setGrantProject}
              />
              <CheckboxField
                help={ARCHITECTURE_HELP.collectionIncludeDescendants} label="Include nested projects"
                checked={descendants} onChange={setDescendants}
              />
            </>
          ) : (
            <PrincipalPicker
              orgUsers={orgUsers} organizationId={organizationId} projectId={scope.kind === "project" ? scope.projectId : undefined}
              value={grantGroup} onChange={setGrantGroup} kinds={["org_group", "project_group"]}
              ariaLabel={`Group to share ${collection.name} with`} placeholder="Search groups…" clearLabel="Clear"
            />
          )}
          <button
            className="btn btn-primary" disabled={!grantReady}
            onClick={() => void run(async () => {
              await calls.addGrant(collection.id, {
                project_id: target === "project" ? grantProject : null, group: target === "group" ? grantGroup : null,
                include_descendants: target === "project" && descendants,
              });
              setGrantProject("");
              setGrantGroup(null);
              setDescendants(false);
            }, "Collection shared.")}
          >
            Share
          </button>
        </div>
      </div>
    </section>
  );
}

/**
 * @param scope The project or organisation whose collections are managed.
 * @param elements The owner's elements, from which members are chosen.
 * @param orgUsers Organisation members, for the group search.
 * @param organizationId The owning organisation.
 */
export function CollectionsPanel({
  scope, elements, orgUsers, organizationId,
}: { scope: TypesScope; elements: ArchitectureElement[]; orgUsers: OrgUser[]; organizationId: string }) {
  const { showToast } = useToast();
  const [collections, setCollections] = useState<ArchitectureCollection[] | null>(null);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ArchitectureCollection | "new" | null>(null);
  const [deleting, setDeleting] = useState<ArchitectureCollection | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  const scopeId = scope.kind === "project" ? scope.projectId : scope.organizationId;
  const calls = useMemo(
    () => (scope.kind === "project" ? projectCollectionApi(scopeId) : orgCollectionApi(scopeId)),
    [scope.kind, scopeId],
  );

  useEffect(() => {
    let live = true;
    calls.list()
      .then((list) => { if (live) { setCollections(list); setLoadError(null); } })
      .catch((err) => { if (live) setLoadError(toErrorMessage(err, "Could not load the collections.")); });
    return () => { live = false; };
  }, [calls, refresh]);

  useEffect(() => {
    api.get<ProjectListItem[]>(`/api/v1/projects?organization_id=${organizationId}`).then(setProjects).catch(() => setProjects([]));
  }, [organizationId]);

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (collections === null) return <Spinner />;

  async function save(values: { name: string; description: string }) {
    setFormError(null);
    try {
      if (editing === "new") await calls.create(values);
      else if (editing) await calls.update(editing.id, values);
      showToast(editing === "new" ? "Collection created." : "Collection updated.");
      setEditing(null);
      reload();
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not save the collection."));
    }
  }

  return (
    <div className="stack">
      <div className="row">
        <button className="btn btn-primary" onClick={() => { setFormError(null); setEditing("new"); }}>New collection</button>
      </div>
      {collections.length === 0 && <p className="text-muted">No collections yet. Create one to share elements.</p>}
      {collections.map((c) => (
        <CollectionCard
          key={c.id} collection={c} scope={scope} elements={elements} orgUsers={orgUsers} organizationId={organizationId}
          projects={projects} onChanged={reload} onEdit={() => { setFormError(null); setEditing(c); }} onDelete={() => setDeleting(c)}
        />
      ))}
      {editing && (
        <CollectionFormModal
          initial={editing === "new" ? undefined : editing} error={formError}
          onCancel={() => { setEditing(null); setFormError(null); }} onSave={save}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete ${deleting.name}?`}
          message="The elements stay; they stop being shared through this collection, and projects and groups it was shared with lose that access."
          confirmLabel="Delete"
          onCancel={() => setDeleting(null)}
          onConfirm={async () => {
            const target = deleting;
            setDeleting(null);
            try {
              await calls.remove(target.id);
              showToast("Collection deleted.");
              reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not delete the collection."), "error");
            }
          }}
        />
      )}
    </div>
  );
}
