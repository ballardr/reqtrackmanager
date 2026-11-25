/**
 * Module: components/OrgReportsResources
 *
 * The Reports section of Org Resources: the organisation's report layouts and packs, its saved text snippets and its
 * report configuration (file name rule, output retention, footer text, cover page, chapters per component).
 *
 * The layouts, packs and snippets sections show to everyone who reaches the page; each call enforces its own
 * permission (`manage_org_report_layouts`), so this component decides nothing about access. The configuration is
 * loaded and saved through `/orgs/{id}/advanced-settings`, which only organisation administrators may read; where
 * the read is refused (403) the Configuration section is not offered. Its form sends only the five report fields
 * (the endpoint applies only the fields sent), so saving never rewrites the sign-in, email or token settings that
 * share the endpoint. Report branding stays in Organisation Settings, Branding defaults.
 *
 * Dependencies: `reportLayoutApi`, `reportPackApi`, `reportPlacementApi`, `ReportSetupPanel`, `ReportSnippetsPanel`,
 * `FileNameField`, `GET`/`PUT /orgs/{id}/advanced-settings`.
 */
import { useMemo, useState } from "react";

import { ApiError, api } from "../api/client";
import { reportLayoutApi } from "../api/reportLayouts";
import { reportPackApi } from "../api/reportPacks";
import { reportPlacementApi } from "../api/reportPlacements";
import type { OrgAdvancedSettings } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { CollapsibleSection } from "./CollapsibleSection";
import { FileNameField } from "./FileNameField";
import { CheckboxField, TextField } from "./FormFields";
import { InlineMessage } from "./InlineMessage";
import { ReportSetupPanel } from "./ReportSetupPanel";
import { ReportSnippetsPanel } from "./ReportSnippetsPanel";

/**
 * The organisation's Reports resources.
 *
 * @param orgId The organisation whose report layouts, packs, snippets and configuration are shown.
 * @returns The three collapsible sections; the configuration appears once the administrator-only settings load.
 */
export function OrgReportsResources({ orgId }: { orgId: string }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const layoutApi = useMemo(() => reportLayoutApi({ kind: "organization", id: orgId }), [orgId]);
  const packApi = useMemo(() => reportPackApi({ kind: "organization", id: orgId }), [orgId]);
  const placementApi = useMemo(() => reportPlacementApi({ kind: "organization", id: orgId }), [orgId]);
  const snippetScope = useMemo(() => ({ kind: "organization" as const, id: orgId }), [orgId]);

  const [settings, setSettings] = useState<OrgAdvancedSettings | null>(null);
  const [outputRetentionDays, setOutputRetentionDays] = useState("");
  const [fileName, setFileName] = useState("");
  const [footerText, setFooterText] = useState("");
  const [includeCoverPage, setIncludeCoverPage] = useState(false);
  const [chaptersPerComponent, setChaptersPerComponent] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /** Copies the saved settings into the editable fields. */
  function populate(a: OrgAdvancedSettings) {
    setSettings(a);
    setOutputRetentionDays(a.report_output_retention_days ? String(a.report_output_retention_days) : "");
    setFileName(a.report_file_name ?? "");
    setFooterText(a.report_footer_text ?? "");
    setIncludeCoverPage(a.report_include_cover_page);
    setChaptersPerComponent(a.report_chapters_per_component);
  }

  useLoadOnChange(async () => {
    try {
      populate(await api.get<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`));
    } catch (err) {
      // Only administrators can read the settings; for anyone else the section is simply not offered.
      setSettings(null);
      if (!(err instanceof ApiError && err.status === 403)) showToast(toErrorMessage(err, strings.common.error));
    }
  }, [orgId]);

  /** Saves the five report fields; shows the server's message on failure. */
  async function save() {
    setError(null);
    try {
      const saved = await api.put<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`, {
        report_output_retention_days: outputRetentionDays ? Number(outputRetentionDays) : null,
        report_file_name: fileName.trim() || null,
        report_footer_text: footerText.trim() || null,
        report_include_cover_page: includeCoverPage,
        report_chapters_per_component: chaptersPerComponent,
      });
      populate(saved);
      showToast(strings.orgAdmin.advancedSaved);
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  return (
    <div className="stack">
      <CollapsibleSection sectionKey="orgAdmin.reportSetup" title={strings.orgAdmin.reportLayoutsSection} defaultCollapsed={false}>
        <ReportSetupPanel layoutApi={layoutApi} packApi={packApi} placementApi={placementApi} />
      </CollapsibleSection>
      <CollapsibleSection sectionKey="orgAdmin.reportSnippets" title={strings.reportSnippetsPanel.sectionTitle} defaultCollapsed>
        <ReportSnippetsPanel scope={snippetScope} />
      </CollapsibleSection>

      {settings && (
        <CollapsibleSection sectionKey="orgAdmin.reportConfiguration" title={strings.orgAdmin.reportConfigurationTitle} defaultCollapsed>
          <FileNameField
            label={strings.reportFileName.organizationLabel}
            help={strings.help.reportFileNameOrganization}
            value={fileName}
            kind="organization"
            onChange={setFileName}
          />
          <TextField
            label={strings.orgAdmin.reportOutputRetention}
            help={strings.help.reportOutputRetention}
            value={outputRetentionDays}
            onChange={setOutputRetentionDays}
            hint={strings.orgAdmin.reportOutputRetentionHint(
              settings.report_output_default_retention_days, settings.report_output_max_retention_days,
            )}
            inputProps={{ type: "number", min: 1, max: 3650, style: { maxWidth: 160 } }}
          />
          <TextField
            label={strings.orgAdmin.reportFooterText}
            help={strings.help.reportFooterText}
            value={footerText}
            onChange={setFooterText}
            inputProps={{ maxLength: 500 }}
          />
          <CheckboxField
            label={strings.orgAdmin.reportIncludeCoverPage}
            help={strings.help.reportIncludeCoverPage}
            checked={includeCoverPage}
            onChange={setIncludeCoverPage}
          />
          <CheckboxField
            label={strings.orgAdmin.reportChaptersPerComponent}
            help={strings.help.reportChaptersPerComponent}
            checked={chaptersPerComponent}
            onChange={setChaptersPerComponent}
          />
          <InlineMessage>{error}</InlineMessage>
          <button className="btn btn-primary" onClick={() => void save()} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.saveReportConfiguration}
          </button>
        </CollapsibleSection>
      )}
    </div>
  );
}
