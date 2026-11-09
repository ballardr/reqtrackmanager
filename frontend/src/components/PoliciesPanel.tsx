/**
 * Module: components/PoliciesPanel
 *
 * Administration of policies for one scope: the server's, or one organisation's (the same panel with the owner
 * passed in). Lists the built-in policies first (the server's, unset until written) and any others, with their
 * status, version and effective date. An administrator can write or edit the working copy, publish it as a new
 * version with a change note, unpublish it, read the version history, and delete a policy that is not built in.
 *
 * An organisation's list adds each policy's audience, the setting that allows links in its policies, and, on
 * publication, the choice to notify the people who may read it.
 *
 * Saving writes the working copy only; readers see the published version until it is published again. The server
 * enforces scope and the text rules; its message is shown in the dialog.
 */
import { History, Pencil, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import { api } from "../api/client";
import type {
  OrgPolicySettings, OrgPolicySummary, OrgPolicyWrite, Policy, PolicySlot, PolicySummary, PolicyVersion,
} from "../api/types";
import { POLICY_STATE_LABEL, POLICY_STATE_TONE } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { formatPlainDate } from "../utils/localDate";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { FormActions } from "./FormActions";
import { CheckboxField, TextAreaField, ToggleField } from "./FormFields";
import { Modal } from "./Modal";
import { PolicyEditor } from "./PolicyEditor";
import { PrincipalBadge } from "./PrincipalBadge";
import { Spinner } from "./Spinner";

/** Where the panel reads and writes: the server's policies, or one organisation's. */
export type PolicyScope = { kind: "server" } | { kind: "organisation"; organizationId: string };

function basePath(scope: PolicyScope): string {
  return scope.kind === "server" ? "/api/v1/system/policies" : `/api/v1/orgs/${scope.organizationId}/policies`;
}

/** What the editor dialog is open for: a new policy, a built-in policy not yet written, or an existing one. */
type Editing = { kind: "new" } | { kind: "slot"; slot: PolicySlot; title: string } | { kind: "edit"; policy: Policy };

function PublishDialog({ title, error, organisation, onCancel, onPublish }: {
  title: string; error: string | null; organisation: boolean; onCancel: () => void; onPublish: (note: string, notifyMembers: boolean) => void;
}) {
  const strings = useStrings();
  const text = strings.policies;
  const [note, setNote] = useState("");
  const [notifyMembers, setNotifyMembers] = useState(false);
  return (
    <Modal title={text.publishTitle(title)} onClose={onCancel}>
      <div className="stack">
        <p>{organisation ? text.publishBodyOrganisation : text.publishBody}</p>
        <TextAreaField label={text.changeNote} help={strings.help.policyChangeNote} value={note} onChange={setNote} rows={3} inputProps={{ maxLength: 1000 }} />
        {organisation && <CheckboxField label={text.notifyMembers} help={strings.help.policyNotifyMembers} checked={notifyMembers} onChange={setNotifyMembers} />}
        <FormActions error={error} onCancel={onCancel} saveLabel={text.publish} onSave={() => onPublish(note.trim(), notifyMembers)} />
      </div>
    </Modal>
  );
}

function HistoryDialog({ title, versions, onClose }: { title: string; versions: PolicyVersion[]; onClose: () => void }) {
  const text = useStrings().policies;
  return (
    <Modal title={`${text.history}: ${title}`} onClose={onClose}>
      {versions.length === 0 ? (
        <div className="text-muted">{text.historyEmpty}</div>
      ) : (
        <table className="table" aria-label={text.history}>
          <thead>
            <tr><th>{text.version}</th><th>{text.updated}</th><th>{text.effectiveFromLabel}</th><th>{text.changeNote}</th></tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version}>
                <td>{v.version}</td>
                <td>{new Date(v.published_at).toLocaleString()}</td>
                <td>{v.effective_from ? formatPlainDate(v.effective_from) : ""}</td>
                <td>{v.change_note || <span className="text-muted">{text.noteNone}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}

/**
 * @param scope The scope to administer.
 */
export function PoliciesPanel({ scope }: { scope: PolicyScope }) {
  const strings = useStrings();
  const text = strings.policies;
  const run = useMutation();
  const { showToast } = useToast();
  const [items, setItems] = useState<(PolicySummary | OrgPolicySummary)[] | null>(null);
  const [settings, setSettings] = useState<OrgPolicySettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [publishing, setPublishing] = useState<PolicySummary | null>(null);
  const [unpublishing, setUnpublishing] = useState<PolicySummary | null>(null);
  const [removing, setRemoving] = useState<PolicySummary | null>(null);
  const [history, setHistory] = useState<Policy | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const path = basePath(scope);
  const organisation = scope.kind === "organisation";

  const reload = useCallback(async () => {
    try {
      const [list, loadedSettings] = await Promise.all([
        api.get<(PolicySummary | OrgPolicySummary)[]>(path),
        organisation ? api.get<OrgPolicySettings>(`${path}/settings`) : Promise.resolve(null),
      ]);
      setItems(list);
      setSettings(loadedSettings);
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, text.loadFailed));
    }
  }, [path, organisation, text.loadFailed]);

  useLoadOnChange(reload, [path]);

  async function openEditor(item: PolicySummary) {
    setSaveError(null);
    if (item.id === null) {
      setEditing({ kind: "slot", slot: item.key as PolicySlot, title: item.title });
      return;
    }
    try {
      setEditing({ kind: "edit", policy: await api.get<Policy>(`${path}/${item.id}`) });
    } catch (err) {
      showToast(toErrorMessage(err, text.loadFailed), "error");
    }
  }

  async function openHistory(item: PolicySummary) {
    try {
      setHistory(await api.get<Policy>(`${path}/${item.id}`));
    } catch (err) {
      showToast(toErrorMessage(err, text.loadFailed), "error");
    }
  }

  async function setAllowLinks(allowLinks: boolean) {
    if (await run(() => api.put(`${path}/settings`, { allow_links: allowLinks }), { success: text.settingSaved, failure: strings.mutation.failure("save", text.noun) })) {
      setSettings((current) => (current ? { ...current, allow_links: allowLinks } : current));
    }
  }

  async function save(values: OrgPolicyWrite) {
    if (editing === null) return;
    setSaveError(null);
    const existing = editing.kind === "edit" ? editing.policy : null;
    const verb = existing ? "save" : "create";
    try {
      if (existing) await api.put(`${path}/${existing.id}`, values);
      else await api.post(path, values);
    } catch (err) {
      setSaveError(toErrorMessage(err, strings.mutation.failure(verb, text.noun)));
      return;
    }
    showToast(strings.mutation.success(text.noun, strings.mutation.past[verb]));
    setEditing(null);
    await reload();
  }

  async function publish(item: PolicySummary, note: string, notifyMembers: boolean) {
    setSaveError(null);
    try {
      await api.post(`${path}/${item.id}/publish`, organisation ? { change_note: note, notify_members: notifyMembers } : { change_note: note });
    } catch (err) {
      setSaveError(toErrorMessage(err, strings.mutation.failure("publish", text.noun)));
      return;
    }
    showToast(text.publishedToast);
    setPublishing(null);
    await reload();
  }

  async function unpublish(item: PolicySummary) {
    setUnpublishing(null);
    if (await run(() => api.post(`${path}/${item.id}/unpublish`, {}), { success: text.unpublishedToast, failure: strings.mutation.failure("unpublish", text.noun) })) await reload();
  }

  async function remove(item: PolicySummary) {
    setRemoving(null);
    if (await run(() => api.delete(`${path}/${item.id}`), "delete", text.noun)) await reload();
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!items) return <Spinner />;
  return (
    <div className="stack">
      {settings && (
        <ToggleField label={text.allowLinks} help={strings.help.policyLinks} checked={settings.allow_links} onChange={(next) => void setAllowLinks(next)} />
      )}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-primary" onClick={() => { setSaveError(null); setEditing({ kind: "new" }); }}>{text.newPolicy}</button>
      </div>
      <table className="table" aria-label={text.heading}>
        <thead>
          <tr>
            <th>{text.title}</th>
            <th>{text.state}</th>
            <th>{text.version}</th>
            {organisation && <th>{text.audience}</th>}
            <th>{text.effectiveFromLabel}</th>
            <th>{text.updated}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id ?? item.key} data-policy-key={item.key ?? undefined}>
              <td><strong>{item.title}</strong></td>
              <td>
                {item.id === null ? (
                  <span className="text-muted">{text.notWritten}</span>
                ) : (
                  <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
                    <Badge tone={POLICY_STATE_TONE[item.state]}>{POLICY_STATE_LABEL[item.state]}</Badge>
                    {item.current_version > 0 && item.has_unpublished_changes && <Badge tone="warning">{text.unpublishedChanges}</Badge>}
                  </div>
                )}
              </td>
              <td>{item.current_version > 0 ? item.current_version : ""}</td>
              {organisation && (
                <td>
                  {"audience" in item && item.audience.length > 0 ? (
                    <div className="row" style={{ gap: "var(--space-1)", flexWrap: "wrap" }}>
                      {item.audience.map((p) => <PrincipalBadge key={`${p.type}:${p.id}`} principal={p} />)}
                    </div>
                  ) : (
                    <span className="text-muted">{text.audienceEveryone}</span>
                  )}
                </td>
              )}
              <td>{item.effective_from ? formatPlainDate(item.effective_from) : ""}</td>
              <td>{item.updated_at ? new Date(item.updated_at).toLocaleString() : ""}</td>
              <td>
                <div className="row" style={{ justifyContent: "flex-end" }}>
                  {item.id === null ? (
                    <button className="btn" onClick={() => void openEditor(item)}>{text.writeSlot(item.title)}</button>
                  ) : (
                    <>
                      {(item.state === "draft" || item.has_unpublished_changes) && (
                        <button className="btn btn-primary" aria-label={text.publishAria(item.title)} onClick={() => { setSaveError(null); setPublishing(item); }}>
                          {text.publish}
                        </button>
                      )}
                      {item.state === "published" && (
                        <button className="btn" aria-label={text.unpublishAria(item.title)} onClick={() => setUnpublishing(item)}>{text.unpublish}</button>
                      )}
                      <button className="btn" aria-label={`${text.history}: ${item.title}`} title={text.history} onClick={() => void openHistory(item)}><History /></button>
                      <button className="btn" aria-label={text.editAria(item.title)} title={text.editAria(item.title)} onClick={() => void openEditor(item)}><Pencil /></button>
                      {item.key === null && (
                        <button className="btn btn-danger" aria-label={text.deleteAria(item.title)} title={text.deleteAria(item.title)} onClick={() => setRemoving(item)}><Trash2 /></button>
                      )}
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing !== null && (
        <PolicyEditor
          policy={editing.kind === "edit" ? editing.policy : null} slot={editing.kind === "slot" ? editing.slot : null}
          slotTitle={editing.kind === "slot" ? editing.title : undefined} error={saveError}
          organization={scope.kind === "organisation" ? { id: scope.organizationId, starterTitles: settings?.starter_titles ?? [] } : undefined}
          onCancel={() => setEditing(null)} onSave={save}
        />
      )}
      {publishing && (
        <PublishDialog
          title={publishing.title} error={saveError} organisation={organisation} onCancel={() => setPublishing(null)}
          onPublish={(note, notifyMembers) => void publish(publishing, note, notifyMembers)}
        />
      )}
      {history && <HistoryDialog title={history.title} versions={history.versions} onClose={() => setHistory(null)} />}
      {unpublishing && (
        <ConfirmDialog
          title={text.unpublishTitle(unpublishing.title)} message={text.unpublishBody} confirmLabel={text.unpublish}
          onConfirm={() => void unpublish(unpublishing)} onCancel={() => setUnpublishing(null)}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={text.deleteTitle(removing.title)} message={text.deleteBody} confirmLabel={strings.common.delete}
          onConfirm={() => void remove(removing)} onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  );
}
