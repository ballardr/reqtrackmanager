/**
 * Module: components/ServiceUsersPanel
 *
 * The organisation's service users for its administrators (Organisation Settings, Service users): a sortable list with
 * the review flags and token counts, a create form, and a detail dialog per service user (`ServiceUserDetailModal`)
 * for its tokens and lifecycle.
 *
 * Design decisions:
 * - The list is the whole set (an organisation has few service users), so it sorts in the browser; the sort is in the
 *   URL like every other list.
 * - Create and edit share one field group (`ServiceUserFields`); a save error stays in the dialog header and a success
 *   Toast follows every change.
 * - Archived service users are hidden unless asked for.
 *
 * Dependencies: `/api/v1/orgs/{id}/service-users`, `/api/v1/projects` (for the token restriction).
 */
import { useCallback, useMemo, useState } from "react";

import { api } from "../api/client";
import { serviceUsersPath, type ServiceUser, type ServiceUserDraft } from "../api/serviceUsers";
import type { ProjectListItem } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useUrlSort } from "../hooks/useUrlFilter";
import { Badge } from "./Badge";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { FilterCheckbox, FilterPanel } from "./FilterPanel";
import { InlineMessage } from "./InlineMessage";
import { PrincipalBadge } from "./PrincipalBadge";
import { ServiceBadge } from "./ServiceBadge";
import { ServiceUserDetailModal } from "./ServiceUserDetailModal";
import { ServiceUserFlags } from "./ServiceUserFlags";
import { ServiceUserFormModal } from "./ServiceUserFormModal";
import { Spinner } from "./Spinner";
import { cycleSort } from "./sortState";

const SORT_KEYS = ["name", "responsible", "last_used_at"] as const;
type SortKey = (typeof SORT_KEYS)[number];

function sortValue(user: ServiceUser, key: SortKey): string {
  if (key === "name") return user.name.toLowerCase();
  if (key === "responsible") return user.responsible?.label.toLowerCase() ?? "";
  return user.last_used_at ?? "";
}

/** What the create and edit forms send: a blank address means "none", and an unset responsible party clears it. */
function payload(draft: ServiceUserDraft, forEdit: boolean) {
  const email = draft.email.trim() || null;
  return forEdit
    ? { name: draft.name.trim(), description: draft.description, email, responsible: draft.responsible }
    : { name: draft.name.trim(), description: draft.description, ...(email ? { email } : {}), responsible: draft.responsible };
}

/**
 * @param organizationId The organisation whose service users are administered.
 */
export function ServiceUsersPanel({ organizationId }: { organizationId: string }) {
  const strings = useStrings();
  const text = strings.serviceUsers;
  const { showToast } = useToast();
  const [rows, setRows] = useState<ServiceUser[] | null>(null);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [sort, setSort] = useUrlSort<SortKey>(SORT_KEYS);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ServiceUser | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const query = includeArchived ? "?include_archived=true" : "";
      setRows(await api.get<ServiceUser[]>(`${serviceUsersPath(organizationId)}${query}`));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, text.loadFailed));
    }
  }, [organizationId, includeArchived, text.loadFailed]);

  useLoadOnChange(reload, [organizationId, includeArchived]);
  useLoadOnChange(async () => {
    try {
      setProjects(await api.get<ProjectListItem[]>(`/api/v1/projects?archived=false&include_templates=false&organization_id=${organizationId}`));
    } catch {
      setProjects([]);
    }
  }, [organizationId]);

  const sorted = useMemo(() => {
    if (!rows || !sort) return rows ?? [];
    const copy = [...rows];
    copy.sort((a, b) => {
      const left = sortValue(a, sort.key);
      const right = sortValue(b, sort.key);
      // A service user never used (or with no responsible party) sorts last in either direction.
      if (!left !== !right) return left ? -1 : 1;
      return (left < right ? -1 : left > right ? 1 : 0) * (sort.direction === "asc" ? 1 : -1);
    });
    return copy;
  }, [rows, sort]);

  const open = rows?.find((r) => r.user_id === openId) ?? null;

  async function save(draft: ServiceUserDraft, existing: ServiceUser | null) {
    setSaveError(null);
    try {
      if (existing) await api.patch(`${serviceUsersPath(organizationId)}/${existing.user_id}`, payload(draft, true));
      else await api.post(serviceUsersPath(organizationId), payload(draft, false));
      showToast(existing ? text.savedToast : text.createdToast);
      setCreating(false);
      setEditing(null);
      await reload();
    } catch (err) {
      setSaveError(toErrorMessage(err, strings.common.error));
    }
  }

  const columns: DirectoryColumn<ServiceUser>[] = [
    {
      key: "name", label: text.name, sortable: true,
      render: (u) => (
        <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <span>{u.name}</span>
          <ServiceBadge />
        </span>
      ),
    },
    { key: "responsible", label: text.responsible, sortable: true, render: (u) => <PrincipalBadge principal={u.responsible} placeholder={text.none} /> },
    { key: "flags", label: text.flags, render: (u) => <ServiceUserFlags flags={u.flags} /> },
    { key: "tokens", label: text.tokens, render: (u) => u.active_token_count },
    {
      key: "last_used_at", label: text.lastUsed, sortable: true,
      render: (u) => (u.last_used_at ? new Date(u.last_used_at).toLocaleString() : text.never),
    },
    {
      key: "status", label: text.status,
      render: (u) => (
        <Badge tone={u.is_active ? "accent" : "muted"}>
          {u.is_archived ? text.statusArchived : u.is_active ? text.statusActive : text.statusDeactivated}
        </Badge>
      ),
    },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-3)" }}>
        <button className="btn btn-primary" onClick={() => { setSaveError(null); setCreating(true); }}>{text.create}</button>
      </div>
      <FilterPanel layout="top" sectionKey="orgAdminServiceUsersFilters">
        <FilterCheckbox label={text.includeArchived} checked={includeArchived} onChange={setIncludeArchived} />
      </FilterPanel>
      {loadError ? (
        <InlineMessage>{loadError}</InlineMessage>
      ) : !rows ? (
        <Spinner />
      ) : (
        <DirectoryTable
          ariaLabel={text.heading} columns={columns} rows={sorted} rowKey={(u) => u.user_id}
          sort={sort} onSort={(key) => setSort(cycleSort(sort, key as SortKey))}
          onRowClick={(u) => setOpenId(u.user_id)}
          emptyState={<p className="text-muted">{text.empty}</p>}
        />
      )}

      {creating && (
        <ServiceUserFormModal
          organizationId={organizationId} error={saveError} onCancel={() => setCreating(false)}
          onSave={(draft) => void save(draft, null)}
        />
      )}
      {editing && (
        <ServiceUserFormModal
          organizationId={organizationId} initial={editing} error={saveError} onCancel={() => setEditing(null)}
          onSave={(draft) => void save(draft, editing)}
        />
      )}
      {open && !editing && (
        <ServiceUserDetailModal
          organizationId={organizationId} serviceUser={open} projects={projects}
          onEdit={() => { setSaveError(null); setEditing(open); }} onChanged={() => void reload()} onClose={() => setOpenId(null)}
        />
      )}
    </div>
  );
}
