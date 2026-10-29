/**
 * Module: components/RequirementReportPanel
 *
 * The requirement report's configuration and generation surface (R-F-01 PDF,
 * Word, R-F-02 CSV), shown in the Reports dialog beside the catalogue reports in the same picker. It
 * carries a chapter-per-component/continuous layout choice and organisation shared resource sections
 * (R-G-04). Branding is never chosen here: a download uses the organisation's default template. Narrowing
 * the requirements (R-G-03) is done on the requirements list, whose Export and Download report carry the
 * list's filters. An introduction, chapters or appendices are written in a report layout (the
 * "Requirements by Component" starter), not here. It has its own request model
 * (`POST /projects/{id}/reports`), which is why it is not a catalogue entry.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ReportDownloadKind } from "../api/reports";
import type { FileAsset, Project } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { downloadBlob } from "../utils/download";
import { CollapsibleSection } from "./CollapsibleSection";
import { ReportExportButton } from "./ReportExportButton";
import { Spinner } from "./Spinner";
import { FormGrid } from "./FormGrid";
import { LabeledSelect } from "./LabeledSelect";

/**
 * @param project The project the report is generated for.
 */
export function RequirementReportPanel({ project }: { project: Project }) {
  const strings = useStrings();
  const projectId = project.id;
  const { showToast } = useToast();
  const [generating, setGenerating] = useState<ReportDownloadKind | null>(null);

  const [resources, setResources] = useState<FileAsset[]>([]);
  const [resourceFileIds, setResourceFileIds] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [chaptersPerComponent, setChaptersPerComponent] = useState<boolean | null>(null);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      setResources(await api.get<FileAsset[]>(`/api/v1/orgs/${project.organization_id}/resources`));
      setLoaded(true);
    })();
  }, [projectId, project.organization_id]);

  function toggleResource(id: string) {
    setResourceFileIds((ids) => (ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id]));
  }

  async function generate(kind: ReportDownloadKind) {
    setGenerating(kind);
    try {
      const blob = await api.postForBlob(`/api/v1/projects/${projectId}/reports`, {
        format: kind,
        resource_file_ids: resourceFileIds,
        chapters_per_component: kind !== "csv" ? chaptersPerComponent : null,
      });
      const projectName = project.name.replace(/[\\/"\r\n\t]/g, "") || "project";
      downloadBlob(blob, `${projectName}-requirements.${kind}`);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    } finally {
      setGenerating(null);
    }
  }

  if (!loaded) return <Spinner />;

  return (
    <div className="stack">
      <div className="row">
        <button className="btn btn-primary" onClick={() => generate("pdf")} disabled={generating !== null}>
          {generating === "pdf" ? "…" : strings.reports.generatePdf}
        </button>
        <ReportExportButton onDownload={generate} kinds={["docx", "csv"]} label={strings.reports.moreFormats} />
      </div>

      <FormGrid minColumn="16rem">
        <LabeledSelect help={strings.help.reportChapterLayout}
          label={strings.reports.chapterLayout}
          value={chaptersPerComponent === null ? "" : String(chaptersPerComponent)}
          onChange={(next) => setChaptersPerComponent(next === "" ? null : next === "true")}
          options={[
            { value: "true", label: strings.reports.chapterLayoutChaptered },
            { value: "false", label: strings.reports.chapterLayoutContinuous },
          ]}
          placeholder={strings.reports.chapterLayoutAuto}
        />
      </FormGrid>

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
