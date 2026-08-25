import { Star } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { ProjectListItem, StageStatus } from "../api/types";
import { collapseProjectRoles, PROJECT_ROLE_LABEL, STAGE_STATUS_LABEL } from "../api/types";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useFavourites } from "../context/FavouritesContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";

const PAGE_SIZE = 30;

function stageBadgeText(stageName: string, status: StageStatus | null): string {
  if (!status || stageName.toLowerCase() === status) return stageName;
  return `${stageName} · ${STAGE_STATUS_LABEL[status]}`;
}

/** Only shown in the nav when the user has favourited at least one active
 * project (Layout.tsx) — a quick jump list, not a filtered view of
 * ProjectListPage, though it shares that page's server-side
 * pagination/search shape (`favorite_only` on the same `/projects`
 * endpoint) rather than fetching and filtering every project client-side. */
export function FavouritesPage() {
  const strings = useStrings();
  const { showToast } = useToast();
  const { refreshFavourites } = useFavourites();
  const orgLabelCap = useOrgLabelCapitalized();
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useViewMode("favourites");

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({
      archived: "false", favorite_only: "true", limit: String(PAGE_SIZE), offset: String(offset),
    });
    if (search) params.set("search", search);
    return params;
  }

  async function load(offset: number, append: boolean) {
    const page = await api.getPage<ProjectListItem>(`/api/v1/projects?${listParams(offset).toString()}`);
    setProjects((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  useEffect(() => {
    setProjects(null);
    load(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  async function unfavorite(project: ProjectListItem) {
    try {
      await api.delete(`/api/v1/projects/${project.id}/favorite`);
      load(0, false);
      refreshFavourites();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.nav.favourites}</h1>

      <div className="row" style={{ justifyContent: "space-between" }}>
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder={strings.projects.search}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <ViewToggle mode={viewMode} onChange={setViewMode} />
      </div>

      {!projects && <Spinner />}
      {projects && projects.length === 0 && <p className="text-muted">{strings.projects.empty}</p>}
      {projects && projects.length > 0 && viewMode === "tiles" && (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
          {projects.map((p) => (
            <div key={p.id} className="card stack" style={{ gap: "0.5rem" }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "nowrap" }}>
                <Link
                  to={`/projects/${p.id}`}
                  style={{
                    fontWeight: 600, fontSize: "1.05rem", minWidth: 0, overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}
                  title={p.name}
                >
                  {p.name}
                </Link>
                <button
                  className="btn"
                  onClick={() => unfavorite(p)}
                  title={strings.projects.unfavorite}
                  aria-label={strings.projects.unfavorite}
                  style={{ flexShrink: 0 }}
                >
                  <Star size={16} fill="currentColor" />
                </button>
              </div>
              <div className="text-muted" style={{ fontSize: "0.8rem" }}>{p.organization_name}</div>
              {p.current_stage_name && (
                <span className="badge" style={{ alignSelf: "flex-start" }}>
                  {stageBadgeText(p.current_stage_name, p.current_stage_status)}
                </span>
              )}
              <p className="text-muted" style={{ margin: 0, flex: 1 }}>
                {p.summary || "—"}
              </p>
              <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                {strings.projects.roles}: {collapseProjectRoles(p.my_roles).map((r) => PROJECT_ROLE_LABEL[r]).join(", ") || "—"}
              </div>
              <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                {strings.projects.requirementCount}: {p.requirement_count}
              </div>
            </div>
          ))}
        </div>
      )}
      {projects && projects.length > 0 && viewMode === "list" && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th />
                <th>Name</th>
                <th>{strings.projects.organisation(orgLabelCap)}</th>
                <th>{strings.projects.stage}</th>
                <th>{strings.projects.roles}</th>
                <th>{strings.projects.requirementCount}</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td>
                    <button
                      className="btn"
                      onClick={() => unfavorite(p)}
                      title={strings.projects.unfavorite}
                      aria-label={strings.projects.unfavorite}
                    >
                      <Star size={14} fill="currentColor" />
                    </button>
                  </td>
                  <td>
                    <Link to={`/projects/${p.id}`}>{p.name}</Link>
                    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                      {p.summary || "—"}
                    </div>
                  </td>
                  <td className="text-muted">{p.organization_name}</td>
                  <td>
                    {p.current_stage_name && (
                      <span className="badge">{stageBadgeText(p.current_stage_name, p.current_stage_status)}</span>
                    )}
                  </td>
                  <td className="text-muted">{collapseProjectRoles(p.my_roles).map((r) => PROJECT_ROLE_LABEL[r]).join(", ") || "—"}</td>
                  <td className="text-muted">{p.requirement_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {projects && <LoadMoreButton loaded={projects.length} total={total} onClick={() => load(projects.length, true)} />}
    </div>
  );
}
