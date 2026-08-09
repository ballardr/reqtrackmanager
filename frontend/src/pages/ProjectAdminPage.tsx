import { ArrowDown, ArrowUp, Check, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type {
  AssignByEmailOutcome,
  Category,
  Component,
  CustomFieldDefinition,
  CustomFieldEntityKind,
  CustomFieldType,
  OrgUser,
  Project,
  ProjectGroup,
  ProjectReportConfig,
  ProjectStage,
  ReportChapter,
} from "../api/types";
import { CUSTOM_FIELD_ENTITY_KIND_LABEL, CUSTOM_FIELD_TYPE_LABEL, PROJECT_ROLE_LABEL, STAGE_STATUS_LABEL } from "../api/types";
import { ReportChapterListEditor } from "../components/ReportChapterListEditor";
import { RichTextEditor } from "../components/RichTextEditor";
import { Spinner } from "../components/Spinner";
import { UserAutocomplete } from "../components/UserAutocomplete";
import { t } from "../i18n/strings";

const strings = t();

const TERMINOLOGY_KEYS = ["project", "stage", "component", "category", "requirement", "change_request"] as const;

/**
 * Project administration: settings (C-U-13, C-C-03, C-P-01), stages/approval
 * (C-G-08, C-G-10), components and categories with ordering (C-G-07,
 * C-E-01/C-E-02), and project groups (C-U-11).
 */
export function ProjectAdminPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [stages, setStages] = useState<ProjectStage[] | null>(null);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [groups, setGroups] = useState<ProjectGroup[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [newComponentName, setNewComponentName] = useState("");
  const [newComponentPrefix, setNewComponentPrefix] = useState("");
  // Keyed by component id: each component's own inline "add category" form,
  // since a category is now created nested under one specific component
  // (the tree) rather than at project level.
  const [newCategoryInputs, setNewCategoryInputs] = useState<Record<string, { name: string; prefix: string }>>({});
  const [deadlineInputs, setDeadlineInputs] = useState<Record<string, string>>({});
  const [cascadeInputs, setCascadeInputs] = useState<Record<string, boolean>>({});

  const [settingsName, setSettingsName] = useState("");
  const [settingsSummary, setSettingsSummary] = useState("");
  const [allowMemberCr, setAllowMemberCr] = useState(true);
  const [isTemplate, setIsTemplate] = useState(false);
  const [terminology, setTerminology] = useState<Record<string, string>>({});

  const [reportIntro, setReportIntro] = useState("");
  const [reportChapters, setReportChapters] = useState<ReportChapter[]>([]);
  const [reportAppendices, setReportAppendices] = useState<ReportChapter[]>([]);
  const [reportConfigDefaults, setReportConfigDefaults] = useState({
    intro: false,
    chapters: false,
    appendices: false,
  });

  const [customFields, setCustomFields] = useState<CustomFieldDefinition[]>([]);
  const [newFieldKind, setNewFieldKind] = useState<CustomFieldEntityKind>("requirement");
  const [newFieldName, setNewFieldName] = useState("");
  const [newFieldType, setNewFieldType] = useState<CustomFieldType>("short_text");
  const [newFieldOptions, setNewFieldOptions] = useState("");
  const [newFieldRequired, setNewFieldRequired] = useState(false);

  async function reload() {
    if (!projectId) return;
    const [p, s, c, cat, g, cf, rc] = await Promise.all([
      api.get<Project>(`/api/v1/projects/${projectId}`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<ProjectGroup[]>(`/api/v1/projects/${projectId}/groups`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields`),
      api.get<ProjectReportConfig>(`/api/v1/projects/${projectId}/report-config`),
    ]);
    setProject(p);
    setSettingsName(p.name);
    setSettingsSummary(p.summary);
    setAllowMemberCr(p.allow_member_change_requests);
    setIsTemplate(p.is_template);
    setTerminology(p.terminology);
    setStages(s);
    setComponents(c);
    setCategories(cat);
    setGroups(g);
    setCustomFields(cf);
    // Group membership (below) only stores user ids — resolving those to
    // an email/display name needs the org's member directory. Any org
    // role (including plain "member") can call this endpoint unfiltered
    // (see `routers/orgs.py::list_org_users`), and project access already
    // implies org membership, so this is safe for whoever can reach this
    // page at all.
    setOrgUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${p.organization_id}/users`));
    setReportIntro(rc.intro);
    setReportChapters(rc.chapters);
    setReportAppendices(rc.appendices);
    setReportConfigDefaults({
      intro: rc.intro_is_organisation_default,
      chapters: rc.chapters_is_organisation_default,
      appendices: rc.appendices_is_organisation_default,
    });
  }

  async function saveReportConfig() {
    await api.put(`/api/v1/projects/${projectId}/report-config`, {
      intro: reportIntro, chapters: reportChapters, appendices: reportAppendices,
    });
    reload();
  }

  async function addCustomField() {
    await api.post(`/api/v1/projects/${projectId}/custom-fields`, {
      entity_kind: newFieldKind,
      name: newFieldName,
      field_type: newFieldType,
      options: newFieldType === "list" ? newFieldOptions.split(",").map((s) => s.trim()).filter(Boolean) : null,
      required: newFieldRequired,
    });
    setNewFieldName("");
    setNewFieldOptions("");
    setNewFieldRequired(false);
    reload();
  }

  async function deleteCustomField(fieldId: string) {
    await api.delete(`/api/v1/projects/${projectId}/custom-fields/${fieldId}`);
    reload();
  }

  async function saveSettings() {
    await api.patch(`/api/v1/projects/${projectId}`, {
      name: settingsName, summary: settingsSummary,
      allow_member_change_requests: allowMemberCr, is_template: isTemplate,
    });
    reload();
  }

  async function saveTerminology() {
    await api.put(`/api/v1/projects/${projectId}/terminology`, { terminology });
    reload();
  }

  async function toggleArchive() {
    const action = project?.is_archived ? "unarchive" : "archive";
    await api.post(`/api/v1/projects/${projectId}/${action}`);
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function approveStage(stageId: string) {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/transition?new_status=approved`);
    reload();
  }

  async function setReviewDeadline(stageId: string, isoDeadline: string) {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/review-deadline`, {
      review_deadline: isoDeadline || null,
    });
    reload();
  }

  async function respondToStageReview(stageId: string, response: "approved" | "rejected") {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/review-response`, { response });
    reload();
  }

  async function completeStage(stageId: string, cascade: boolean) {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/complete`, { cascade_to_requirements: cascade });
    reload();
  }

  async function addComponent() {
    await api.post(`/api/v1/projects/${projectId}/components`, { name: newComponentName, prefix: newComponentPrefix });
    setNewComponentName("");
    setNewComponentPrefix("");
    reload();
  }

  async function addCategory(componentId: string) {
    const input = newCategoryInputs[componentId];
    if (!input?.name || !input?.prefix) return;
    await api.post(`/api/v1/projects/${projectId}/categories`, {
      name: input.name, prefix: input.prefix, component_id: componentId,
    });
    setNewCategoryInputs((m) => ({ ...m, [componentId]: { name: "", prefix: "" } }));
    reload();
  }

  async function moveComponent(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/projects/${projectId}/components/${id}/move`, { direction });
    reload();
  }

  async function moveCategory(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/projects/${projectId}/categories/${id}/move`, { direction });
    reload();
  }

  async function addGroupMember(groupId: string, userId: string) {
    await api.post(`/api/v1/projects/${projectId}/groups/${groupId}/members`, { user_id: userId });
    reload();
  }

  const [externalAddResult, setExternalAddResult] = useState<{ message: string; isError: boolean } | null>(null);

  /** Adds someone found via UserAutocomplete's external-search result (not
   * yet a member of this project's organisation, possibly no account at
   * all) directly to the project with `role` — the by-email counterpart to
   * `addGroupMember`. Grants a *direct* project role rather than group
   * membership (the group's own `role` is used so the effective access
   * matches what joining the group would have granted), since the by-email
   * endpoint has no notion of "this specific group" — see
   * `routers/projects.py::assign_project_role_by_email`. */
  async function addExternalMember(email: string, role: string) {
    setExternalAddResult(null);
    try {
      const result = await api.post<{ outcome: AssignByEmailOutcome }>(
        `/api/v1/projects/${projectId}/roles/by-email`,
        { email, role },
      );
      const messages: Record<AssignByEmailOutcome, string> = {
        added: strings.admin.externalAddedDirectly,
        invited: strings.admin.externalInvited,
        sso_provisioned: strings.admin.externalSsoProvisioned,
      };
      setExternalAddResult({
        message: messages[result.outcome].replace("{email}", email).replace("{role}", role),
        isError: false,
      });
      reload();
    } catch (err) {
      setExternalAddResult({
        message: err instanceof ApiError ? err.message : strings.admin.externalAddError,
        isError: true,
      });
    }
  }

  async function removeGroupMember(groupId: string, userId: string) {
    await api.delete(`/api/v1/projects/${projectId}/groups/${groupId}/members/${userId}`);
    reload();
  }

  const [tab, setTab] = useState<
    "overview" | "stages" | "categories" | "customFields" | "groups" | "terminology" | "reportSetup"
  >("overview");

  if (!stages || !project) return <Spinner />;

  const tabs: { key: typeof tab; label: string }[] = [
    { key: "overview", label: strings.admin.settings },
    { key: "stages", label: strings.admin.stages },
    { key: "categories", label: strings.admin.categories },
    { key: "customFields", label: strings.admin.customFields },
    { key: "groups", label: strings.admin.groups },
    { key: "terminology", label: strings.admin.terminology },
    { key: "reportSetup", label: "Report Setup" },
  ];

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.nav.admin}</h1>

      <div className="row" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
        {tabs.map((tb) => (
          <button
            key={tb.key}
            className={`btn ${tab === tb.key ? "btn-primary" : ""}`}
            onClick={() => setTab(tb.key)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.settings}</h2>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.admin.name}
          <input className="input" value={settingsName} onChange={(e) => setSettingsName(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.admin.summary}
          <textarea className="input" rows={2} value={settingsSummary} onChange={(e) => setSettingsSummary(e.target.value)} />
        </label>
        <label className="row">
          <input type="checkbox" checked={allowMemberCr} onChange={(e) => setAllowMemberCr(e.target.checked)} />
          {strings.admin.allowMemberChangeRequests}
        </label>
        <label className="row">
          <input type="checkbox" checked={isTemplate} onChange={(e) => setIsTemplate(e.target.checked)} />
          {strings.admin.isTemplate}
        </label>

        <div className="row" style={{ justifyContent: "space-between" }}>
          <button className="btn btn-primary" onClick={saveSettings}>
            {strings.admin.saveSettings}
          </button>
          <button className="btn btn-danger" onClick={toggleArchive}>
            {project.is_archived ? strings.admin.unarchiveProject : strings.admin.archiveProject}
          </button>
        </div>
      </div>
      )}

      {tab === "terminology" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.terminology}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.admin.terminologyHint}</p>
        {TERMINOLOGY_KEYS.map((key) => (
          <div key={key} className="row">
            <span style={{ minWidth: 140, textTransform: "capitalize" }}>{key.replace("_", " ")}</span>
            <input
              className="input"
              placeholder={key}
              value={terminology[key] ?? ""}
              onChange={(e) => setTerminology((t2) => ({ ...t2, [key]: e.target.value }))}
            />
          </div>
        ))}
        <button className="btn btn-primary" onClick={saveTerminology} style={{ alignSelf: "flex-start" }}>
          {strings.admin.saveSettings}
        </button>
      </div>
      )}

      {tab === "stages" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.stages}</h2>
        {stages.map((s) => (
          <div key={s.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span>
                {s.name} <span className="badge">{STAGE_STATUS_LABEL[s.status]}</span>
                {s.review_deadline && <span className="badge">{strings.admin.reviewDeadline}: {new Date(s.review_deadline).toLocaleString()}</span>}
                {s.completed_at && <span className="badge">{strings.admin.stageCompletedAt}: {new Date(s.completed_at).toLocaleDateString()}</span>}
              </span>
              {s.status !== "approved" && s.status !== "completed" && (
                <button className="btn" onClick={() => approveStage(s.id)}>
                  <Check size={14} /> {strings.admin.approveStage}
                </button>
              )}
              {s.status === "approved" && (
                <div className="row">
                  <label className="row" style={{ gap: "0.25rem" }}>
                    <input
                      type="checkbox" checked={cascadeInputs[s.id] ?? false}
                      onChange={(e) => setCascadeInputs((c) => ({ ...c, [s.id]: e.target.checked }))}
                    />
                    {strings.admin.cascadeToRequirements}
                  </label>
                  <button className="btn" onClick={() => completeStage(s.id, cascadeInputs[s.id] ?? false)}>
                    {strings.admin.completeStage}
                  </button>
                </div>
              )}
            </div>
            {s.status === "review" && (
              <div className="row">
                <input
                  className="input" type="datetime-local" style={{ maxWidth: 220 }}
                  value={deadlineInputs[s.id] ?? ""}
                  onChange={(e) => setDeadlineInputs((d) => ({ ...d, [s.id]: e.target.value }))}
                />
                <button
                  className="btn"
                  onClick={() => setReviewDeadline(s.id, deadlineInputs[s.id] ? new Date(deadlineInputs[s.id]).toISOString() : "")}
                >
                  {strings.admin.setReviewDeadline}
                </button>
                {s.review_deadline && (
                  <>
                    <button className="btn" onClick={() => respondToStageReview(s.id, "approved")}>
                      {strings.admin.respondApprove}
                    </button>
                    <button className="btn btn-danger" onClick={() => respondToStageReview(s.id, "rejected")}>
                      {strings.admin.respondReject}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
      )}

      {tab === "categories" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.components}</h2>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{strings.admin.componentTreeHint}</p>
        {components.map((c, idx) => {
          const ownCategories = categories.filter((cat) => cat.component_id === c.id);
          const categoryInput = newCategoryInputs[c.id] ?? { name: "", prefix: "" };
          return (
            <div key={c.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.75rem" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>
                  {c.name} <span className="badge">{c.prefix}</span>
                </span>
                <div className="row">
                  <button className="btn" disabled={idx === 0} onClick={() => moveComponent(c.id, "up")}>
                    <ArrowUp size={14} />
                  </button>
                  <button className="btn" disabled={idx === components.length - 1} onClick={() => moveComponent(c.id, "down")}>
                    <ArrowDown size={14} />
                  </button>
                </div>
              </div>
              <div className="stack" style={{ paddingLeft: "1.5rem", gap: "0.4rem" }}>
                {ownCategories.map((cat, catIdx) => (
                  <div key={cat.id} className="row" style={{ justifyContent: "space-between" }}>
                    <span>
                      {cat.name} <span className="badge">{cat.prefix}</span>
                    </span>
                    <div className="row">
                      <button className="btn" disabled={catIdx === 0} onClick={() => moveCategory(cat.id, "up")}>
                        <ArrowUp size={14} />
                      </button>
                      <button
                        className="btn"
                        disabled={catIdx === ownCategories.length - 1}
                        onClick={() => moveCategory(cat.id, "down")}
                      >
                        <ArrowDown size={14} />
                      </button>
                    </div>
                  </div>
                ))}
                <div className="row">
                  <input
                    className="input"
                    placeholder={strings.admin.name}
                    value={categoryInput.name}
                    onChange={(e) => setNewCategoryInputs((m) => ({ ...m, [c.id]: { ...categoryInput, name: e.target.value } }))}
                  />
                  <input
                    className="input"
                    style={{ maxWidth: 100 }}
                    placeholder={strings.admin.prefix}
                    value={categoryInput.prefix}
                    onChange={(e) =>
                      setNewCategoryInputs((m) => ({ ...m, [c.id]: { ...categoryInput, prefix: e.target.value.toUpperCase() } }))
                    }
                  />
                  <button
                    className="btn"
                    onClick={() => addCategory(c.id)}
                    disabled={!categoryInput.name || !categoryInput.prefix}
                  >
                    <Plus size={14} /> {strings.admin.newCategory}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
        <div className="row">
          <input className="input" placeholder={strings.admin.name} value={newComponentName} onChange={(e) => setNewComponentName(e.target.value)} />
          <input
            className="input"
            style={{ maxWidth: 100 }}
            placeholder={strings.admin.prefix}
            value={newComponentPrefix}
            onChange={(e) => setNewComponentPrefix(e.target.value.toUpperCase())}
          />
          <button className="btn btn-primary" onClick={addComponent} disabled={!newComponentName || !newComponentPrefix}>
            <Plus size={14} /> {strings.admin.newComponent}
          </button>
        </div>
      </div>
      )}

      {tab === "customFields" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.customFields}</h2>
        {customFields.map((f) => (
          <div key={f.id} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              {f.name} <span className="badge">{CUSTOM_FIELD_ENTITY_KIND_LABEL[f.entity_kind]}</span> <span className="badge">{CUSTOM_FIELD_TYPE_LABEL[f.field_type]}</span>
              {f.required && <span className="badge">{strings.admin.required}</span>}
            </span>
            <button className="btn btn-danger" onClick={() => deleteCustomField(f.id)}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <div className="row">
          <select className="input" value={newFieldKind} onChange={(e) => setNewFieldKind(e.target.value as CustomFieldEntityKind)}>
            <option value="requirement">{strings.admin.entityKindRequirement}</option>
            <option value="change_request">{strings.admin.entityKindChangeRequest}</option>
          </select>
          <input className="input" placeholder={strings.admin.fieldName} value={newFieldName} onChange={(e) => setNewFieldName(e.target.value)} />
          <select className="input" value={newFieldType} onChange={(e) => setNewFieldType(e.target.value as CustomFieldType)}>
            <option value="short_text">{strings.admin.fieldTypeShortText}</option>
            <option value="long_text">{strings.admin.fieldTypeLongText}</option>
            <option value="checkbox">{strings.admin.fieldTypeCheckbox}</option>
            <option value="list">{strings.admin.fieldTypeList}</option>
          </select>
          {newFieldType === "list" && (
            <input
              className="input"
              placeholder={strings.admin.optionsCommaSeparated}
              value={newFieldOptions}
              onChange={(e) => setNewFieldOptions(e.target.value)}
            />
          )}
          <label className="row">
            <input type="checkbox" checked={newFieldRequired} onChange={(e) => setNewFieldRequired(e.target.checked)} />
            {strings.admin.required}
          </label>
          <button className="btn btn-primary" onClick={addCustomField} disabled={!newFieldName}>
            <Plus size={14} /> {strings.admin.newCustomField}
          </button>
        </div>
      </div>
      )}

      {tab === "groups" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.groups}</h2>
        {externalAddResult && (
          <div style={{ color: externalAddResult.isError ? "var(--color-danger)" : "var(--color-accent)" }}>
            {externalAddResult.message}
          </div>
        )}
        {groups.map((g) => {
          const availableUsers = orgUsers.filter((u) => !g.member_user_ids.includes(u.user_id));
          return (
            <div key={g.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.75rem" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>
                  {g.name} <span className="badge">{PROJECT_ROLE_LABEL[g.role]}</span>
                </span>
                <span className="text-muted">
                  {strings.admin.memberCount.replace("{n}", String(g.member_user_ids.length))}
                  {g.member_org_group_ids.length > 0 &&
                    ` + ${strings.admin.viaOrgGroups.replace("{n}", String(g.member_org_group_ids.length))}`}
                </span>
              </div>
              {g.member_user_ids.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                  {g.member_user_ids.map((userId) => {
                    const u = orgUsers.find((ou) => ou.user_id === userId);
                    return (
                      <li key={userId} className="row" style={{ justifyContent: "space-between", listStyle: "disc" }}>
                        <span>{u ? `${u.display_name} (${u.email})` : userId}</span>
                        <button className="btn btn-danger" onClick={() => removeGroupMember(g.id, userId)}>
                          <Trash2 size={14} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
              <UserAutocomplete
                users={availableUsers}
                placeholder={strings.admin.addMemberPlaceholder}
                onSelect={(userId) => addGroupMember(g.id, userId)}
                organizationId={project?.organization_id}
                projectId={project?.id}
                onSelectExternal={(email) => addExternalMember(email, g.role)}
              />
            </div>
          );
        })}
      </div>
      )}

      {tab === "reportSetup" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Report Setup</h2>
        <p className="text-muted" style={{ margin: 0 }}>
          This intro, these chapters, and these appendices are used as the default content when a report is
          generated for this project, unless overridden at generation time.
        </p>
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span>
            Project intro
            {reportConfigDefaults.intro && <span className="text-muted"> (organisation default)</span>}
          </span>
          <RichTextEditor rows={3} value={reportIntro} onChange={setReportIntro} organizationId={project?.organization_id} />
        </div>
        <div className="stack" style={{ gap: "0.25rem" }}>
          {reportConfigDefaults.chapters && (
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>Using the organisation default body chapters.</span>
          )}
          <ReportChapterListEditor
            label="Body chapters" list={reportChapters} setList={setReportChapters}
            organizationId={project?.organization_id}
          />
        </div>
        <div className="stack" style={{ gap: "0.25rem" }}>
          {reportConfigDefaults.appendices && (
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>Using the organisation default appendices.</span>
          )}
          <ReportChapterListEditor
            label="Appendices" list={reportAppendices} setList={setReportAppendices}
            organizationId={project?.organization_id}
          />
        </div>
        <button className="btn btn-primary" onClick={saveReportConfig} style={{ alignSelf: "flex-start" }}>
          {strings.admin.saveSettings}
        </button>
      </div>
      )}
    </div>
  );
}
