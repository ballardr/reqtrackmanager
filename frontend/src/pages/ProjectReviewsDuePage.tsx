import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Component, RequirementDueForReview } from "../api/types";
import { principalText } from "../api/types";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { PrincipalBadge } from "../components/PrincipalBadge";
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
  // "<type>:<id>" of the chosen reviewer (a user or a group), or "".
  const [reviewerKey, setReviewerKey] = useState("");
  const [mineOnly, setMineOnly] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    api.get<Component[]>(`/api/v1/projects/${projectId}/components`).then(setComponents);
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    const params = new URLSearchParams();
    if (componentId) params.set("component_id", componentId);
    if (reviewerKey) {
      const [type, id] = reviewerKey.split(":");
      params.set("reviewer_type", type);
      params.set("reviewer_id", id);
    }
    if (mineOnly) params.set("reviewer_mine", "true");
    api
      .get<RequirementDueForReview[]>(`/api/v1/projects/${projectId}/requirements/reviews/due?${params.toString()}`)
      .then(setItems);
  }, [projectId, componentId, reviewerKey, mineOnly]);

  const reviewers = Array.from(
    new Map(
      (items ?? []).flatMap((i) => (i.reviewer ? [[`${i.reviewer.type}:${i.reviewer.id}`, principalText(i.reviewer)] as const] : []))
    ).entries()
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
                      <td><PrincipalBadge principal={item.reviewer} placeholder={strings.reviews.unassigned} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <FilterPanel sectionKey="projectReviewsDueFilters">
          <FilterField label={strings.requirements.component}>
            <select className="input" value={componentId} onChange={(e) => setComponentId(e.target.value)}>
              <option value="">{strings.reviews.allComponents}</option>
              {components.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Reviewer">
            <select className="input" value={reviewerKey} onChange={(e) => setReviewerKey(e.target.value)}>
              <option value="">{strings.reviews.allReviewers}</option>
              {reviewers.map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </FilterField>
          <FilterCheckbox label={strings.reviews.assignedToMe} checked={mineOnly} onChange={setMineOnly} />
        </FilterPanel>
      </div>
    </div>
  );
}
