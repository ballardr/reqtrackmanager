import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { api } from "../api/client";
import type { Organization } from "../api/types";
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
 */
export function OrgListPage({ target = "admin" }: { target?: "admin" | "overview" }) {
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
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

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{heading}</h1>
      <div className="card stack">
        {orgs.map((o) => (
          <Link key={o.id} to={`/orgs/${o.id}/${target}`}>
            {o.name}
          </Link>
        ))}
        {orgs.length === 0 && <p className="text-muted">{strings.orgAdmin.noOrganizations(orgLabelPlural)}</p>}
      </div>
    </div>
  );
}
