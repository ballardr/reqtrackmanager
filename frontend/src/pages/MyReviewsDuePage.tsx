import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { RequirementDueForReview } from "../api/types";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

const PAGE_SIZE = 30;

/** Requirements assigned to the current user as reviewer, due/overdue,
 * across every project (C-R-09, filtered per C-R-10) — unlike its
 * project-scoped sibling `ProjectReviewsDuePage`, this spans every project
 * the reviewer has a role on, so each row shows which project it belongs
 * to. */
export function MyReviewsDuePage() {
  const [items, setItems] = useState<RequirementDueForReview[] | null>(null);
  const [total, setTotal] = useState(0);

  async function load(offset: number, append: boolean) {
    const page = await api.getPage<RequirementDueForReview>(
      `/api/v1/me/reviews/due?limit=${PAGE_SIZE}&offset=${offset}`
    );
    setItems((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  useEffect(() => {
    load(0, false);
  }, []);

  if (!items) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.reviews.myTitle}</h1>
      {items.length === 0 ? (
        <p className="text-muted">{strings.reviews.empty}</p>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>{strings.requirements.name}</th>
                <th>{strings.projects.title}</th>
                <th>{strings.reviews.reviewDate}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.requirement_id}>
                  <td>{item.unique_code}</td>
                  <td>
                    <Link to={`/projects/${item.project_id}/requirements/${item.requirement_id}`}>{item.name}</Link>
                  </td>
                  <td className="text-muted">{item.project_name}</td>
                  <td>{item.review_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {items.length > 0 && <LoadMoreButton loaded={items.length} total={total} onClick={() => load(items.length, true)} />}
    </div>
  );
}
