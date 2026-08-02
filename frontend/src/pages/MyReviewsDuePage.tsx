import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { RequirementDueForReview } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/** Requirements assigned to the current user as reviewer, due/overdue,
 * across every project (C-R-09, filtered per C-R-10). */
export function MyReviewsDuePage() {
  const [items, setItems] = useState<RequirementDueForReview[] | null>(null);

  useEffect(() => {
    api.get<RequirementDueForReview[]>("/api/v1/me/reviews/due").then(setItems);
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
                  <td>{item.review_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
