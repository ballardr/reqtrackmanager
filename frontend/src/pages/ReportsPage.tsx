import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  Category,
  Component,
  FileAsset,
  Project,
  ProjectReportConfig,
  ReportChapter,
  ReportTemplate,
  RequirementStatus,
} from "../api/types";
import { REQUIREMENT_STATUS_LABEL } from "../api/types";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ReportChapterListEditor } from "../components/ReportChapterListEditor";
import { RichTextEditor } from "../components/RichTextEditor";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";

const strings = t();

/** Same joining `services/reports.py::_chapters_markdown` does server-side
 * — kept in sync deliberately: this page sends whatever's currently in the
 * intro/chapters/appendices editors as an explicit `pre_markdown`/
 * `post_markdown` override, rather than leaving them blank and relying on
 * the backend to re-resolve the same content, so what's on screen is
 * exactly what generates. */
function chaptersToMarkdown(chapters: ReportChapter[]): string {
  return chapters
    .filter((c) => c.title)
    .map((c) => `# ${c.title}\n\n${c.body}`)
    .join("\n\n");
}

/**
 * Report generation (R-F-01 PDF, R-F-02 CSV) with the project's effective
 * introduction/body chapters/appendices (R-G-01, R-G-02) editable directly
 * on this page, a report-template picker that previews the template's own
 * content when selected (R-G-05), a chapter-per-component/continuous
 * layout toggle, requirement filters (R-G-03), and organisation shared
 * resource sections (R-G-04).
 */
export function ReportsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [includeArchived, setIncludeArchived] = useState(false);
  const [generating, setGenerating] = useState<"pdf" | "csv" | null>(null);

  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [resources, setResources] = useState<FileAsset[]>([]);
  const [componentId, setComponentId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [statusFilter, setStatusFilter] = useState<RequirementStatus | "">("");
  const [keyword, setKeyword] = useState("");
  const [resourceFileIds, setResourceFileIds] = useState<string[]>([]);
  const [reportTemplates, setReportTemplates] = useState<ReportTemplate[]>([]);
  const [reportTemplateId, setReportTemplateId] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [reportConfig, setReportConfig] = useState<ProjectReportConfig | null>(null);
  const [chaptersPerComponent, setChaptersPerComponent] = useState<boolean | null>(null);

  const [reportIntro, setReportIntro] = useState("");
  const [reportChapters, setReportChapters] = useState<ReportChapter[]>([]);
  const [reportAppendices, setReportAppendices] = useState<ReportChapter[]>([]);

  // The intro/chapters/appendices actually used for a given template
  // selection: the template's own content per field where it set any,
  // otherwise the project's effective (already org-fallback-resolved)
  // content — the same per-field precedence
  // `services/reports.py::resolve_report_config_with_template` applies
  // server-side, computed here just for on-page preview/editing.
  function effectiveContentFor(templateId: string, base: ProjectReportConfig, templates: ReportTemplate[]) {
    const tpl = templates.find((t) => t.id === templateId);
    return {
      intro: tpl?.intro || base.intro,
      chapters: tpl && tpl.chapters.length > 0 ? tpl.chapters : base.chapters,
      appendices: tpl && tpl.appendices.length > 0 ? tpl.appendices : base.appendices,
    };
  }

  function selectTemplate(templateId: string) {
    setReportTemplateId(templateId);
    if (!reportConfig) return;
    const effective = effectiveContentFor(templateId, reportConfig, reportTemplates);
    setReportIntro(effective.intro);
    setReportChapters(effective.chapters);
    setReportAppendices(effective.appendices);
  }

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      const [comps, cats, proj] = await Promise.all([
        api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
        api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
        api.get<Project>(`/api/v1/projects/${projectId}`),
      ]);
      setComponents(comps);
      setCategories(cats);
      setProject(proj);
      const [orgResources, templates, rc] = await Promise.all([
        api.get<FileAsset[]>(`/api/v1/orgs/${proj.organization_id}/resources`),
        api.get<ReportTemplate[]>(`/api/v1/orgs/${proj.organization_id}/report-templates`),
        api.get<ProjectReportConfig>(`/api/v1/projects/${projectId}/report-config`),
      ]);
      setResources(orgResources);
      setReportTemplates(templates);
      setReportConfig(rc);
      const initialTemplateId = rc.default_report_template_id ?? "";
      setReportTemplateId(initialTemplateId);
      const effective = effectiveContentFor(initialTemplateId, rc, templates);
      setReportIntro(effective.intro);
      setReportChapters(effective.chapters);
      setReportAppendices(effective.appendices);
    })();
  }, [projectId]);

  function toggleResource(id: string) {
    setResourceFileIds((ids) => (ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id]));
  }

  async function generate(kind: "pdf" | "csv") {
    setGenerating(kind);
    try {
      const preMarkdown = [reportIntro, chaptersToMarkdown(reportChapters)].filter(Boolean).join("\n\n");
      const postMarkdown = chaptersToMarkdown(reportAppendices);
      const blob = await api.postForBlob(`/api/v1/projects/${projectId}/reports/${kind}`, {
        pre_markdown: preMarkdown,
        post_markdown: postMarkdown,
        include_archived: includeArchived,
        component_id: componentId || null,
        category_id: categoryId || null,
        status: statusFilter || null,
        keyword: keyword || null,
        resource_file_ids: resourceFileIds,
        report_template_id: kind === "pdf" ? reportTemplateId || null : null,
        chapters_per_component: kind === "pdf" ? chaptersPerComponent : null,
      });
      const projectName = project?.name.replace(/[\\/"\r\n\t]/g, "") || "project";
      downloadBlob(blob, `${projectName}-requirements.${kind}`);
    } finally {
      setGenerating(null);
    }
  }

  if (!project || !reportConfig) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.reports.title}</h1>

      <div className="row">
        <button className="btn btn-primary" onClick={() => generate("pdf")} disabled={generating !== null}>
          {generating === "pdf" ? "…" : strings.reports.generatePdf}
        </button>
        <button className="btn" onClick={() => generate("csv")} disabled={generating !== null}>
          {generating === "csv" ? "…" : strings.reports.generateCsv}
        </button>
      </div>

      <CollapsibleSection sectionKey="reports.templateAndLayout" title={strings.reports.templateAndLayout} defaultCollapsed>
        {reportTemplates.length > 0 && (
          <label className="stack" style={{ gap: "0.25rem", maxWidth: 280 }}>
            {strings.reports.reportTemplate}
            <select className="input" value={reportTemplateId} onChange={(e) => selectTemplate(e.target.value)}>
              <option value="">{strings.reports.noTemplate}</option>
              {reportTemplates.map((tpl) => (
                <option key={tpl.id} value={tpl.id}>
                  {tpl.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="stack" style={{ gap: "0.25rem", maxWidth: 280 }}>
          {strings.reports.chapterLayout}
          <select
            className="input"
            value={chaptersPerComponent === null ? "" : String(chaptersPerComponent)}
            onChange={(e) => setChaptersPerComponent(e.target.value === "" ? null : e.target.value === "true")}
          >
            <option value="">{strings.reports.chapterLayoutAuto}</option>
            <option value="true">{strings.reports.chapterLayoutChaptered}</option>
            <option value="false">{strings.reports.chapterLayoutContinuous}</option>
          </select>
        </label>
      </CollapsibleSection>

      <CollapsibleSection sectionKey="reports.filters" title={strings.reports.filters} defaultCollapsed>
        <div className="row">
          <select className="input" value={componentId} onChange={(e) => setComponentId(e.target.value)}>
            <option value="">{strings.reports.allComponents}</option>
            {components.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select className="input" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="">{strings.reports.allCategories}</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as RequirementStatus | "")}>
            <option value="">{strings.reports.allStatuses}</option>
            <option value="draft">{REQUIREMENT_STATUS_LABEL.draft}</option>
            <option value="reviewed">{REQUIREMENT_STATUS_LABEL.reviewed}</option>
            <option value="approved">{REQUIREMENT_STATUS_LABEL.approved}</option>
            <option value="completed">{REQUIREMENT_STATUS_LABEL.completed}</option>
            <option value="archived">{REQUIREMENT_STATUS_LABEL.archived}</option>
          </select>
          <input className="input" placeholder={strings.reports.keywordFilter} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        </div>
        <label className="row">
          <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />
          {strings.reports.includeArchived}
        </label>
      </CollapsibleSection>

      <CollapsibleSection sectionKey="reports.introduction" title={strings.reports.introduction} defaultCollapsed>
        <RichTextEditor rows={4} value={reportIntro} onChange={setReportIntro} organizationId={project?.organization_id} />
      </CollapsibleSection>

      <CollapsibleSection sectionKey="reports.bodyChapters" title={strings.reports.bodyChapters} defaultCollapsed>
        <ReportChapterListEditor
          label={strings.reports.bodyChapters} list={reportChapters} setList={setReportChapters}
          organizationId={project?.organization_id}
        />
      </CollapsibleSection>

      <CollapsibleSection sectionKey="reports.appendices" title={strings.reports.appendices} defaultCollapsed>
        <ReportChapterListEditor
          label={strings.reports.appendices} list={reportAppendices} setList={setReportAppendices}
          organizationId={project?.organization_id}
        />
      </CollapsibleSection>

      {resources.length > 0 && (
        <CollapsibleSection sectionKey="reports.resourceSections" title={strings.reports.resourceSections} defaultCollapsed>
          {resources.map((r) => (
            <label key={r.id} className="row">
              <input type="checkbox" checked={resourceFileIds.includes(r.id)} onChange={() => toggleResource(r.id)} />
              {r.filename}
            </label>
          ))}
        </CollapsibleSection>
      )}
    </div>
  );
}
