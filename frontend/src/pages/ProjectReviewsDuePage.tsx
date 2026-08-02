import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { RequirementDueForReview } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/** Requirements due or overdue for review, project-basis (C-R-09). */
export function ProjectReviewsDuePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [items, setItems] = useState<RequirementDueForReview[] | null>(null);

  useEffect(() => {
    if (!projectId) return;
    api.get<RequirementDueForReview[]>(`/api/v1/projects/${projectId}/requirements/reviews/due`).then(setItems);
  }, [projectId]);

  if (!items) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.reviews.projectTitle}</h1>
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
                <th>{strings.reviews.reviewer}</th>
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
                  <td>{item.reviewer_id ?? strings.reviews.unassigned}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
