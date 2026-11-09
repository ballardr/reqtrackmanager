/**
 * Module: components/OrgUsageTable
 *
 * A plain table at the top of the organisation settings overview: how many users, projects and how much file storage
 * the organisation uses.
 *
 * Responsibilities:
 * - Read `GET /orgs/{id}/overview-stats`, the same service function the organisation dashboards' core metrics use, so
 *   the table and the widgets cannot disagree.
 * - Render only the organisation's real totals (`is_full_org_total`): a scoped figure would describe the caller's own
 *   projects, not the organisation's size, so nothing is drawn for it.
 *
 * Design decisions: a table, not a widget (the figures are fixed and need no layout or editing); a failed or pending
 * read draws nothing rather than an error, because the settings page below it is fully usable without it.
 * External dependencies: `api`, `DirectoryTable`, `formatFileSize`.
 */
import type { JSX } from "react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { OrgOverviewStats } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { formatFileSize } from "../utils/formatFileSize";

import { DirectoryTable } from "./DirectoryTable";

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
  ];

  return (
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
  );
}
