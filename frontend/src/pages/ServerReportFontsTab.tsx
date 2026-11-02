/**
 * Module: pages/ServerReportFontsTab
 *
 * The "Report fonts" group of Server Management: the fonts report authors can choose, and the extra families the
 * server administrator provides from the mounted font directory.
 *
 * Responsibilities:
 * - List the four bundled families and each provided family with its real faces and the name Word and OpenDocument are told.
 * - Per provided family: offer it to authors or hide it, and set its name for Word and OpenDocument and its generic fallback.
 * - Rescan the directory, and say which files were skipped and why.
 *
 * Design decisions:
 * - Rows are the shared `ItemRowList` with the gear (`SettingsPopoverButton`) for the rarely used settings, as for columns.
 * - Every change saves at once and ends in a toast. Hiding is reversible, so it needs no confirmation (style guide, tier 1).
 * - Bundled families are listed for completeness and carry no controls: they are always offered and are not configurable.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ReportFont, ReportFontGeneric, ReportFontsPage } from "../api/types";
import { REPORT_FONT_GENERIC_LABEL, REPORT_FONT_STYLE_LABEL } from "../api/types";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { TextField } from "../components/FormFields";
import { ItemRowList } from "../components/ItemRowList";
import { LabeledSelect } from "../components/LabeledSelect";
import { SettingsPopoverButton } from "../components/SettingsPopoverButton";
import { Spinner } from "../components/Spinner";
import { ToggleSwitch } from "../components/ToggleSwitch";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";

const strings = t();

const GENERIC_OPTIONS = (Object.keys(REPORT_FONT_GENERIC_LABEL) as ReportFontGeneric[]).map((value) => ({
  value,
  label: REPORT_FONT_GENERIC_LABEL[value],
}));

/** The settings of one provided family: its name for Word and OpenDocument, and its generic fallback. */
function FontSettings({ font, onSave }: { font: ReportFont; onSave: (font: ReportFont, change: Partial<ReportFont>) => void }) {
  const [name, setName] = useState(font.word_name);
  return (
    <div className="stack">
      <TextField
        label={strings.reportFonts.wordNameLabel}
        value={name}
        onChange={setName}
        hint={strings.reportFonts.wordNameHint}
        help={strings.help.reportFontWordName}
        inputProps={{
          maxLength: 100,
          onBlur: () => {
            if (name.trim() !== font.word_name) onSave(font, { word_name: name.trim() });
          },
        }}
      />
      <LabeledSelect
        label={strings.reportFonts.genericLabel}
        value={font.generic}
        onChange={(next) => onSave(font, { generic: next as ReportFontGeneric })}
        options={GENERIC_OPTIONS}
        placeholder={null}
        help={strings.help.reportFontGeneric}
      />
    </div>
  );
}

/** The Server Management "Report fonts" group. */
export function ServerReportFontsTab() {
  const { showToast } = useToast();
  const [page, setPage] = useState<ReportFontsPage | null>(null);

  useEffect(() => {
    api
      .get<ReportFontsPage>("/api/v1/system/report-fonts")
      .then(setPage)
      .catch((err) => showToast(toErrorMessage(err, strings.reportFonts.loadError), "error"));
  }, [showToast]);

  async function save(font: ReportFont, change: Partial<ReportFont>) {
    const next = { word_name: font.word_name, generic: font.generic, enabled: font.enabled, ...change };
    try {
      setPage(await api.put<ReportFontsPage>(`/api/v1/system/report-fonts/${font.key}`, next));
      showToast(strings.reportFonts.saved(font.label));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function rescan() {
    try {
      const result = await api.post<ReportFontsPage>("/api/v1/system/report-fonts/rescan", {});
      setPage(result);
      showToast(strings.reportFonts.rescanned(result.families.filter((f) => !f.bundled && !f.missing).length));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (page === null) return <Spinner />;
  const provided = page.families.filter((f) => !f.bundled);
  return (
    <div className="stack">
      <CollapsibleSection sectionKey="serverManagement.reportFonts" title={strings.reportFonts.title}>
        <p className="text-muted">{strings.reportFonts.intro}</p>
        <p className="text-muted">{strings.reportFonts.pdfNote}</p>
        <p className="text-muted">{strings.reportFonts.licenceNote}</p>
        {!page.directory_configured && <p>{strings.reportFonts.notConfigured}</p>}
        {page.directory_configured && provided.length === 0 && <p>{strings.reportFonts.noneFound}</p>}
        <ItemRowList
          label={strings.reportFonts.listLabel}
          emptyName={strings.reportFonts.emptyName}
          items={page.families.map((font) => ({
            id: font.key,
            name: font.label,
            detail: [
              font.bundled ? strings.reportFonts.bundled : font.missing ? strings.reportFonts.missing : strings.reportFonts.provided,
              font.bundled ? "" : strings.reportFonts.faces(font.faces.map((f) => `${REPORT_FONT_STYLE_LABEL[f.style]} (${f.permission})`).join(", ")),
              strings.reportFonts.wordNameDetail(font.word_name, REPORT_FONT_GENERIC_LABEL[font.generic]),
            ].filter(Boolean).join(" · "),
            actions: font.bundled ? undefined : (
              <>
                <ToggleSwitch
                  checked={font.enabled}
                  label={strings.reportFonts.offeredLabel(font.label)}
                  onChange={(next) => save(font, { enabled: next })}
                />
                <SettingsPopoverButton label={strings.reportFonts.settingsLabel(font.label)} title={strings.reportFonts.settingsTitle}>
                  <FontSettings key={font.word_name} font={font} onSave={save} />
                </SettingsPopoverButton>
              </>
            ),
          }))}
        />
        <div>
          <button type="button" className="btn" onClick={rescan}>
            {strings.reportFonts.rescan}
          </button>
        </div>
      </CollapsibleSection>
      {page.skipped.length > 0 && (
        <CollapsibleSection sectionKey="serverManagement.reportFontsSkipped" title={strings.reportFonts.skippedTitle}>
          <p className="text-muted">{strings.reportFonts.skippedHint}</p>
          <ItemRowList
            label={strings.reportFonts.skippedTitle}
            emptyName={strings.reportFonts.emptyName}
            items={page.skipped.map((s) => ({ id: s.file_name, name: s.file_name, detail: s.reason }))}
          />
        </CollapsibleSection>
      )}
    </div>
  );
}
