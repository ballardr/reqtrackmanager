import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Component, RequirementDueForReview } from "../api/types";
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";

/** Requirements due or overdue for review, project-basis (C-R-09), with a
 * filter panel (component/reviewer) for projects with enough due reviews
 * that a flat list stops being scannable. */
export function ProjectReviewsDuePage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [items, setItems] = useState<RequirementDueForReview[] | null>(null);
  const [components, setComponents] = useState<Component[]>([]);
  const [componentId, setComponentId] = useState("");
  const [reviewerId, setReviewerId] = useState("");

  useEffect(() => {
    if (!projectId) return;
    api.get<Component[]>(`/api/v1/projects/${projectId}/components`).then(setComponents);
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    const params = new URLSearchParams();
    if (componentId) params.set("component_id", componentId);
    if (reviewerId) params.set("reviewer_id", reviewerId);
    api
      .get<RequirementDueForReview[]>(`/api/v1/projects/${projectId}/requirements/reviews/due?${params.toString()}`)
      .then(setItems);
  }, [projectId, componentId, reviewerId]);

  const reviewers = Array.from(
    new Map((items ?? []).filter((i) => i.reviewer_id).map((i) => [i.reviewer_id as string, i.reviewer_name as string])).entries()
  );

  if (!items) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.reviews.projectTitle}</h1>

      <div className="side-grid">
        <div className="stack">
          {items.length === 0 ? (
            <p className="text-muted">{strings.reviews.empty}</p>
          ) : (
            <div className="card">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>{strings.requirements.name}</th>
                    <th>{strings.admin.components}</th>
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
                      <td>{item.component_name}</td>
                      <td>{item.review_date}</td>
                      <td>{item.reviewer_name ?? strings.reviews.unassigned}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <FilterPanel>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Filters</h2>
          <FilterField label={strings.requirements.component}>
            <select className="input" value={componentId} onChange={(e) => setComponentId(e.target.value)}>
              <option value="">{strings.reviews.allComponents}</option>
              {components.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Reviewer">
            <select className="input" value={reviewerId} onChange={(e) => setReviewerId(e.target.value)}>
              <option value="">{strings.reviews.allReviewers}</option>
              {reviewers.map(([id, name]) => (
                <option key={id} value={id}>{name}</option>
              ))}
            </select>
          </FilterField>
        </FilterPanel>
      </div>
    </div>
  );
}
