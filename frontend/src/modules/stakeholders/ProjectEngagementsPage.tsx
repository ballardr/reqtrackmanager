/**
 * Module: modules/stakeholders/ProjectEngagementsPage
 *
 * The project's Engagement log, mounted at `/projects/:projectId/modules/
 * stakeholders/engagements` (`module.ts`, reached via the "Engagements" nav-rail
 * entry). An engagement is project-scoped only, so there is no scope column; the
 * list/filter/create UI is the shared `RecordListView`, with the channel as its
 * "type" column and filter. An engagement has no status or archive, so those
 * controls are left out. Filters the list cannot do client-side (a participant,
 * a covered Persona, a date range, retention due) go to the API and refetch.
 *
 * Also the landing route for a research finding (`?finding=<id>`, the path the
 * module registers for the `research_finding` artefact type): the finding's
 * engagement is looked up and the page redirects there, so a link to a finding
 * from the Links panel never dead-ends.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { FilterCheckbox, FilterField } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectEngagementApi, projectPersonaApi, projectResearchApi, projectStakeholderApi, type EngagementListFilters } from "./api";
import { EngagementFormModal } from "./EngagementFormModal";
import { RecordListView } from "./RecordListView";
import type { Engagement, EngagementFieldValues } from "./types";
import { ENGAGEMENT_CHANNEL_LABEL } from "./types";

type Option = { value: string; label: string };

/** An engagement as the shared list reads it: `name` is its title. */
type EngagementRow = Engagement & { name: string };

export function ProjectEngagementsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams] = useSearchParams();
  const findingId = searchParams.get("finding");
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [engagements, setEngagements] = useState<EngagementRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filters, setFilters] = useState<EngagementListFilters>({});
  const [stakeholderOptions, setStakeholderOptions] = useState<Option[]>([]);
  const [personaOptions, setPersonaOptions] = useState<Option[]>([]);

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);
  const setFilter = (patch: Partial<EngagementListFilters>) => setFilters((current) => ({ ...current, ...patch }));

  // A finding link lands here: send the viewer to the engagement the finding belongs to.
  useEffect(() => {
    if (!projectId || !findingId) return;
    projectResearchApi
      .getFinding(projectId, findingId)
      .then((finding) => navigate(`/projects/${projectId}/modules/stakeholders/engagements/${finding.engagement_id}#finding-${finding.id}`, { replace: true }))
      .catch((err) => setLoadError(toErrorMessage(err, "This finding could not be found, or research extras are not enabled for this project.")));
  }, [projectId, findingId, navigate]);

  useEffect(() => {
    if (!projectId || findingId) return;
    let active = true;
    projectEngagementApi
      .list(projectId, filters)
      .then((list) => {
        if (!active) return;
        setEngagements(list.map((e) => ({ ...e, name: e.title })));
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, "The Stakeholders & Personas module isn't enabled for this project, or you don't have access to its engagements."));
      });
    return () => {
      active = false;
    };
  }, [projectId, findingId, filters, refreshKey]);

  useEffect(() => {
    if (!projectId) return;
    projectStakeholderApi.list(projectId).then((list) => setStakeholderOptions(list.map((s) => ({ value: s.id, label: s.name })))).catch(() => setStakeholderOptions([]));
    projectPersonaApi.list(projectId).then((list) => setPersonaOptions(list.map((p) => ({ value: p.id, label: p.name })))).catch(() => setPersonaOptions([]));
  }, [projectId]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (engagements === null) return <Spinner />;

  const filterSelect = (label: string, value: string | undefined, options: Option[], onChange: (next: string | undefined) => void, allLabel: string) => (
    <FilterField label={label}>
      <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value || undefined)}>
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </FilterField>
  );

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Engagements</h1>
      <RecordListView<EngagementRow, EngagementFieldValues>
        records={engagements}
        ariaLabel="Engagements"
        sectionKey="stakeholders.engagements.list"
        noun="Engagement"
        newLabel="Log engagement"
        scopeLabel="project"
        emptyText="No engagements logged for this project yet."
        showScope={false}
        typeName={(e) => ENGAGEMENT_CHANNEL_LABEL[e.channel]}
        typeLabel="Channel"
        searchText={(e) => `${e.unique_code} ${e.title} ${e.summary}`}
        columnsBeforeType={[
          { key: "code", label: "Code", render: (e) => <span className="text-muted">{e.unique_code}</span> },
          { key: "date", label: "Date", render: (e) => e.engagement_date },
        ]}
        columnsAfterScope={[
          { key: "participants", label: "Participants", render: (e) => e.participant_count + e.anonymous_participant_count },
          {
            key: "retention", label: "Retention",
            render: (e) => (e.retention_due ? <span className="badge badge--warning">Review due</span> : e.retain_until ? `Until ${e.retain_until}` : "—"),
          },
        ]}
        extraFilters={
          <>
            {filterSelect("Participant", filters.stakeholder_id, stakeholderOptions, (next) => setFilter({ stakeholder_id: next }), "Anyone")}
            {filterSelect("Persona covered", filters.persona_id, personaOptions, (next) => setFilter({ persona_id: next }), "Any persona")}
            <FilterField label="From">
              <input className="input" type="date" aria-label="From date" value={filters.date_from ?? ""} onChange={(e) => setFilter({ date_from: e.target.value || undefined })} />
            </FilterField>
            <FilterField label="To">
              <input className="input" type="date" aria-label="To date" value={filters.date_to ?? ""} onChange={(e) => setFilter({ date_to: e.target.value || undefined })} />
            </FilterField>
            <FilterCheckbox label="Retention review due" checked={filters.retention_due === true} onChange={(next) => setFilter({ retention_due: next ? true : undefined })} />
          </>
        }
        onOpen={(e) => navigate(`/projects/${projectId}/modules/stakeholders/engagements/${e.id}`)}
        onCreate={async (values) => {
          await projectEngagementApi.create(projectId, values);
          showToast("Engagement logged.");
          reload();
        }}
        renderCreateModal={(props) => <EngagementFormModal error={props.error} onCancel={props.onCancel} onSave={props.onSave} />}
      />
    </div>
  );
}
