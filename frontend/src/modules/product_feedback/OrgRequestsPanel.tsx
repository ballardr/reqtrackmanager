/**
 * Module: modules/product_feedback/OrgRequestsPanel
 *
 * The organisation's request inbox: requests that arrived before anyone knew which project they belong to. It is a
 * group on the Organisation Overview (`module.ts`'s `orgOverviewSections`), the same placement and reasoning as the
 * organisation-level Strategy list: it is day-to-day content, not configuration.
 *
 * Triage is moving a request into a project (on the request's page), which renumbers it there. An inbox request has
 * no links or tags (those belong to a project), so the list shows no demand or Pain Point warnings, and it scores only
 * on the organisation's own scoring scheme. An organisation administrator can switch the inbox off; the panel then
 * says so rather than showing an error.
 */
import { useEffect, useState } from "react";

import { orgScoringApi, type ScoringScheme } from "../../api/scoring";
import type { OrgUser } from "../../api/types";
import { ApiError, api } from "../../api/client";
import { DirectoryTable } from "../../components/DirectoryTable";
import { FilterPanel } from "../../components/FilterPanel";
import { ListActions } from "../../components/ListActions";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Spinner } from "../../components/Spinner";
import { cycleSort } from "../../components/sortState";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { orgRequestApi } from "./api";
import { RequestFormModal, type RequestFormValues } from "./RequestFormModal";
import { requestColumns } from "./requestColumns";
import { RequestFilterFields } from "./RequestFilterFields";
import { sortRequests, useRequestListFilters } from "./requestListState";
import type { EnhancementRequest, FeedbackAccess } from "./types";

const SCHEME_KEY = "enhancement_request";

export function OrgRequestsPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [requests, setRequests] = useState<EnhancementRequest[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [access, setAccess] = useState<FeedbackAccess | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const filters = useRequestListFilters(scheme);

  useEffect(() => {
    void orgScoringApi.get(orgId, SCHEME_KEY).then(setScheme).catch(() => setScheme(null));
    void orgRequestApi.getAccess(orgId).then(setAccess).catch(() => setAccess(null));
    void api.get<OrgUser[]>(`/api/v1/orgs/${orgId}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
  }, [orgId]);

  async function reload() {
    try {
      setRequests(await orgRequestApi.list(orgId, { include_archived: filters.includeArchived, scoring_model: filters.chosenModels }));
      setLoadError(null);
    } catch (err) {
      // A switched-off inbox answers 403/404; say what that means instead of the server's bare message.
      setLoadError(
        err instanceof ApiError && (err.status === 403 || err.status === 404)
          ? "The request inbox is switched off for this organisation, or you don't have access to it."
          : toErrorMessage(err, "Could not load the request inbox."),
      );
    }
  }

  useLoadOnChange(reload, [orgId, filters.includeArchived, filters.chosenModels]);

  async function create(values: RequestFormValues) {
    setCreateError(null);
    try {
      await orgRequestApi.create(orgId, values);
      showToast("Request submitted to the inbox.");
      setCreating(false);
      await reload();
    } catch (err) {
      setCreateError(toErrorMessage(err, "Could not submit the request."));
    }
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (requests === null) return <Spinner />;

  const filtered = requests.filter((r) => filters.matches(r));
  const columns = requestColumns({
    scheme, models: filters.models, showLinkWarnings: false,
    codeCell: (r) => <span className="text-muted"><ScopedRecordCode record={r} /></span>,
  });

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>
        {access?.can_submit !== false && <button className="btn btn-primary" onClick={() => setCreating(true)}>New request</button>}
        <ListActions
          organizationId={orgId} recordType="enhancement_request" filters={filters.filterParams().toString()} onImported={reload}
        />
      </div>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Request inbox"
          columns={columns}
          rows={sortRequests(filtered, filters)}
          sort={filters.sort}
          onSort={(key) => filters.setSort((current) => cycleSort(current, key))}
          rowKey={(r) => r.id}
          rowHref={(r) => `/orgs/${orgId}/modules/product_feedback/requests/${r.id}`}
          emptyState={<p className="text-muted">{requests.length > 0 ? "No requests match these filters." : "The inbox is empty."}</p>}
        />
        <FilterPanel
          sectionKey="product_feedback.inbox.list" total={filtered.length}
          search={filters.search} onSearchChange={filters.setSearch}
          searchPlaceholder="Search the inbox…" searchAriaLabel="Search the request inbox"
        >
          <RequestFilterFields filters={filters} scheme={scheme} requests={requests} />
        </FilterPanel>
      </div>

      {creating && (
        <RequestFormModal
          scopeLabel="organisation inbox" scheme={scheme} orgUsers={orgUsers} organizationId={orgId} error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }} onSave={create}
        />
      )}
    </div>
  );
}
