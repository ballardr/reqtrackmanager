import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Category, Component, FileAsset, Project, ReportTemplate, RequirementStatus } from "../api/types";
import { REQUIREMENT_STATUS_LABEL } from "../api/types";
import { t } from "../i18n/strings";

const strings = t();

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // Some browsers ignore `download` (falling back to a generic,
  // extension-less blob id as the saved filename) for an anchor that was
  // never actually attached to the document before `.click()` — appending
  // it is what makes the filename (and its .pdf/.csv suffix) reliably
  // apply rather than only working in browsers lenient enough not to need
  // this.
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Report generation (R-F-01 PDF, R-F-02 CSV) with custom Markdown
 * introduction/appendix sections (R-G-01, R-G-02), requirement filters
 * (R-G-03), and organisation shared resource sections (R-G-04).
 */
export function ReportsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [preMarkdown, setPreMarkdown] = useState("");
  const [postMarkdown, setPostMarkdown] = useState("");
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
      const [orgResources, templates] = await Promise.all([
        api.get<FileAsset[]>(`/api/v1/orgs/${proj.organization_id}/resources`),
        api.get<ReportTemplate[]>(`/api/v1/orgs/${proj.organization_id}/report-templates`),
      ]);
      setResources(orgResources);
      setReportTemplates(templates);
    })();
  }, [projectId]);

  function toggleResource(id: string) {
    setResourceFileIds((ids) => (ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id]));
  }

  async function generate(kind: "pdf" | "csv") {
    setGenerating(kind);
    try {
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
      });
      const projectName = project?.name.replace(/[\\/"\r\n\t]/g, "") || "project";
      downloadBlob(blob, `${projectName}-requirements.${kind}`);
    } finally {
      setGenerating(null);
    }
  }

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.reports.title}</h1>
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.reports.filters}</h2>
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
      </div>

      <div className="card stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.reports.preMarkdown}
          <textarea className="input" rows={4} value={preMarkdown} onChange={(e) => setPreMarkdown(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.reports.postMarkdown}
          <textarea className="input" rows={4} value={postMarkdown} onChange={(e) => setPostMarkdown(e.target.value)} />
        </label>

        {resources.length > 0 && (
          <div className="stack">
            <strong>{strings.reports.resourceSections}</strong>
            {resources.map((r) => (
              <label key={r.id} className="row">
                <input type="checkbox" checked={resourceFileIds.includes(r.id)} onChange={() => toggleResource(r.id)} />
                {r.filename}
              </label>
            ))}
          </div>
        )}

        {reportTemplates.length > 0 && (
          <label className="stack" style={{ gap: "0.25rem", maxWidth: 280 }}>
            {strings.reports.reportTemplate}
            <select className="input" value={reportTemplateId} onChange={(e) => setReportTemplateId(e.target.value)}>
              <option value="">{strings.reports.noTemplate}</option>
              {reportTemplates.map((tpl) => (
                <option key={tpl.id} value={tpl.id}>
                  {tpl.name}
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="row">
          <button className="btn btn-primary" onClick={() => generate("pdf")} disabled={generating !== null}>
            {generating === "pdf" ? "…" : strings.reports.downloadPdf}
          </button>
          <button className="btn" onClick={() => generate("csv")} disabled={generating !== null}>
            {generating === "csv" ? "…" : strings.reports.downloadCsv}
          </button>
        </div>
      </div>
    </div>
  );
}
