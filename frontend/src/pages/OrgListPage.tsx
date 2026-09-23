import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { DirectoryTable } from "../components/DirectoryTable";
import { FilterPanel } from "../components/FilterPanel";
import { Spinner } from "../components/Spinner";
import { useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Lists organisations the user belongs to (C-U-15: users may belong to
 * more than one). A user who belongs to exactly one skips the list
 * entirely and lands straight on that organisation's own `target` page —
 * the list only earns its keep when there's an actual choice to make.
 *
 * `target` (compliance-module-plan.md Phase 19) generalises this single-
 * org/multi-org auto-redirect convention beyond its original "admin" use:
 * `/org-overview` reuses the exact same component (`target="overview"`)
 * for the new "Organisation Overview" page's entry point, rather than
 * duplicating this fetch-then-redirect-or-list logic a second time.
 *
 * Rebuilt onto the shared `DirectoryTable` + `FilterPanel` (search) shell
 * every other directory in the app uses — this used to be a bare
 * `orgs.map` list of links with no table semantics and no way to narrow a
 * long list by name. Search is client-side, a deliberate judgment call:
 * `GET /orgs` (`backend/app/routers/orgs.py::list_organizations`) has no
 * `search`/`limit`/`offset` query params today, unlike the sibling list
 * pages (`ServerOrganisationsPage.tsx`, `ProjectListPage.tsx`) whose own
 * endpoints already support server-side filtering — and this page's own
 * `mine=true` fetch is, by that endpoint's own doc comment, a *personal*
 * membership list (not the server-wide directory), realistically small
 * enough to filter in the browser rather than justify adding new backend
 * query params purely for this page. Revisit server-side if a deployment's
 * "orgs one person belongs to" count ever grows large enough to matter.
 */
export function OrgListPage({ target = "admin" }: { target?: "admin" | "overview" }) {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [search, setSearch] = useState("");
  const orgLabelPlural = useOrgLabelPlural();
  const orgLabelCap = useOrgLabelCapitalized();

  useEffect(() => {
    // `mine=true`: this is the personal "orgs I belong to" list (nav rail's
    // "My organisations"), not the server-admin platform directory — a
    // server admin with no real membership anywhere must see it empty like
    // anyone else, per `orgs.py::list_organizations`'s doc comment.
    api.get<Organization[]>("/api/v1/orgs?mine=true").then(setOrgs);
  }, []);

  if (!orgs) return <Spinner />;

  if (orgs.length === 1) {
    return <Navigate to={`/orgs/${orgs[0].id}/${target}`} replace />;
  }

  const heading = target === "overview" ? `${orgLabelCap} overview` : "Org Management";

  const needle = search.trim().toLowerCase();
  const filteredOrgs = needle ? orgs.filter((o) => o.name.toLowerCase().includes(needle)) : orgs;

  const columns: DirectoryColumn<Organization>[] = [{ key: "name", label: "Name", render: (o) => o.name }];

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{heading}</h1>
      <div className="side-grid">
        <div className="stack">
          <DirectoryTable
            ariaLabel={heading}
            columns={columns}
            rows={filteredOrgs}
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
      </div>
    </div>
  );
}
