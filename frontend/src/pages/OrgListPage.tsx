import { useCallback, useState } from "react";

import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useUrlSort, useUrlText } from "../hooks/useUrlFilter";
import { sortRows } from "../utils/sortRows";
import { cycleSort } from "../components/sortState";
import { Navigate } from "react-router-dom";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { DirectoryTable } from "../components/DirectoryTable";
import { FilterPanel } from "../components/FilterPanel";
import { ListPageLayout } from "../components/ListPageLayout";
import { LoadFailed } from "../components/LoadFailed";
import { Spinner } from "../components/Spinner";
import { useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Lists the organisations the user belongs to (C-U-15). A user in exactly one skips the list and lands on
 * that organisation's `target` page. `target` selects the destination ("admin" by default; `/org-overview`,
 * `/org-files` and `/org-resources` reuse this component with `overview`, `files` and `resources`), so the
 * navigation rail never needs an organisation id.
 *
 * The list is a shared `DirectoryTable` with a `FilterPanel` search. Search is client-side: `GET /orgs`
 * takes no `search`/`limit`/`offset`, and the `mine=true` personal membership list is small.
 */
export function OrgListPage({ target = "admin" }: { target?: "admin" | "overview" | "resources" | "files" }) {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [failed, setFailed] = useState(false);
  // The search lives in the URL so the list comes back as it was left after a visit to a record.
  const [search, setSearch] = useUrlText("q");
  const [sort, setSort] = useUrlSort<string>(["name"]);
  const orgLabelPlural = useOrgLabelPlural();
  const orgLabelCap = useOrgLabelCapitalized();

  const load = useCallback(() => {
    // `mine=true`: the personal membership list, not the platform directory; a server administrator
    // with no membership sees it empty (`orgs.py::list_organizations`).
    setFailed(false);
    api.get<Organization[]>("/api/v1/orgs?mine=true").then(setOrgs, () => setFailed(true));
  }, []);
  useLoadOnChange(load, []);

  if (failed) return <LoadFailed message={strings.requestFailure.loadFailed(strings.requestFailure.organisations)} onRetry={load} />;
  if (!orgs) return <Spinner />;

  if (orgs.length === 1) {
    return <Navigate to={`/orgs/${orgs[0].id}/${target}`} replace />;
  }

  const heading =
    target === "overview"
      ? `${orgLabelCap} overview`
      : target === "resources"
        ? strings.nav.orgResources(orgLabelCap)
        : target === "files"
          ? strings.files.orgTitle(orgLabelCap)
          : "Org Management";

  const needle = search.trim().toLowerCase();
  const filteredOrgs = needle ? orgs.filter((o) => o.name.toLowerCase().includes(needle)) : orgs;

  const columns: DirectoryColumn<Organization>[] = [{ key: "name", label: "Name", sortable: true, render: (o) => o.name }];

  return (
    <div className="stack">
      <ListPageLayout
        title={heading}
        filter={
          <FilterPanel
            sectionKey="orgListFilters"
            matching={filteredOrgs.length}
            total={orgs.length}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.serverOrgs.search(orgLabelPlural)}
          >
            {null}
          </FilterPanel>
        }
      >
        <div className="stack">
          <DirectoryTable
            ariaLabel={heading}
            columns={columns}
            rows={sortRows(filteredOrgs, sort, { name: (o) => o.name })}
            sort={sort}
            onSort={(key) => setSort((current) => cycleSort(current, key))}
            rowKey={(o) => o.id}
            rowHref={(o) => `/orgs/${o.id}/${target}`}
            emptyState={
              <p className="text-muted">
                {orgs.length === 0
                  ? strings.orgAdmin.noOrganizations(orgLabelPlural)
                  : strings.serverOrgs.empty(orgLabelPlural)}
              </p>
            }
          />
        </div>
      </ListPageLayout>
    </div>
  );
}
