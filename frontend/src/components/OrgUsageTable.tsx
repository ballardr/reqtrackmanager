/**
 * Module: components/OrgUsageTable
 *
 * A plain table at the top of the organisation settings overview: how many users, projects and how much file
 * storage the organisation uses.
 *
 * Reads `GET /orgs/{id}/overview-stats`, the service function the organisation dashboards' core metrics also use, so
 * the table and the widgets agree. It shows the storage limit (read-only here; set by the server administrator or a
 * Platform subscription manager), whether new files are accepted and, at 90% of the limit, a warning. It renders
 * only the organisation's real totals (`is_full_org_total`), because a scoped figure would describe the caller's
 * own projects. A failed or pending read draws nothing, because the page below is usable without it.
 *
 * External dependencies: `api`, `DirectoryTable`, `formatFileSize`.
 */
import type { JSX } from "react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { OrgOverviewStats } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { formatFileSize } from "../utils/formatFileSize";

import { DirectoryTable } from "./DirectoryTable";
import { InlineMessage } from "./InlineMessage";

interface UsageRow {
  key: string;
  measure: string;
  value: string;
}

/**
 * The organisation's usage figures as a two-column table.
 *
 * @param orgId The organisation whose figures are shown.
 * @returns The table, or nothing while the figures load, when the read fails or when they are not the full totals.
 */
export function OrgUsageTable({ orgId }: { orgId: string }): JSX.Element | null {
  const strings = useStrings();
  const [stats, setStats] = useState<OrgOverviewStats | null>(null);

  useEffect(() => {
    let current = true;
    api.get<OrgOverviewStats>(`/api/v1/orgs/${orgId}/overview-stats`)
      .then((loaded) => { if (current) setStats(loaded); })
      .catch(() => { if (current) setStats(null); });
    return () => { current = false; };
  }, [orgId]);

  if (!stats || !stats.is_full_org_total) return null;

  const rows: UsageRow[] = [
    { key: "users", measure: strings.orgAdmin.usage.users, value: stats.member_count.toLocaleString() },
    { key: "active", measure: strings.orgAdmin.usage.activeProjects, value: stats.project_count.toLocaleString() },
    { key: "archived", measure: strings.orgAdmin.usage.archivedProjects, value: stats.archived_project_count.toLocaleString() },
    { key: "storage", measure: strings.orgAdmin.usage.storage, value: formatFileSize(stats.total_file_size_bytes) },
    {
      key: "limit", measure: strings.orgAdmin.usage.storageLimit,
      value: stats.storage_quota_bytes === null ? strings.orgAdmin.usage.noLimit : formatFileSize(stats.storage_quota_bytes),
    },
    {
      key: "uploads", measure: strings.orgAdmin.usage.fileUploads,
      value: stats.uploads_enabled ? strings.orgAdmin.usage.uploadsEnabled : strings.orgAdmin.usage.uploadsDisabled,
    },
  ];

  return (
    <div className="stack">
    <DirectoryTable
      ariaLabel={strings.orgAdmin.usage.title}
      columns={[
        { key: "measure", label: strings.orgAdmin.usage.measure, render: (row) => row.measure },
        { key: "value", label: strings.orgAdmin.usage.value, render: (row) => row.value },
      ]}
      rows={rows}
      rowKey={(row) => row.key}
      emptyState={null}
    />
    {stats.storage_warning && <InlineMessage tone="warning">{strings.orgAdmin.usage.nearlyFull}</InlineMessage>}
    </div>
  );
}
