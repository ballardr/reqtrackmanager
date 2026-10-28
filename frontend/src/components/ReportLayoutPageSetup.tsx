/**
 * Module: components/ReportLayoutPageSetup
 *
 * The text view's page setup: a settings button beside the block toolbar that opens a popover with the layout's page
 * orientation and page size, and writes them into the first line of the text (`@layout document landscape A3`).
 *
 * Responsibilities: read the setup from the text's first line (`readPageSetup`), offer the sizes the server accepts
 * (`PAGE_SIZES`) and rewrite the line on a change (`writePageSetup`). The server's parser stays the judge of the text.
 * A table layout has no pages, so it renders nothing.
 */
import { useStrings } from "../context/TerminologyContext";
import { PAGE_ORIENTATIONS, PAGE_SIZES, readPageSetup, writePageSetup, type PageSetup } from "../utils/reportLayoutText";
import { LabeledSelect } from "./LabeledSelect";
import { SettingsPopoverButton } from "./SettingsPopoverButton";

/**
 * @param text The layout text; its first line is rewritten on a change.
 * @param onChange Called with the new text.
 */
export function ReportLayoutPageSetup({ text, onChange }: { text: string; onChange: (text: string) => void }) {
  const strings = useStrings();
  const labels = strings.reportLayouts;
  const setup = readPageSetup(text);
  if (setup === null) return null;
  const set = (patch: Partial<PageSetup>) => onChange(writePageSetup(text, { ...setup, ...patch }));
  return (
    <SettingsPopoverButton
      label={labels.pageSetupLabel(labels.orientationLabels[setup.orientation], setup.size)}
      title={labels.pageSetupTitle}
      marked={setup.orientation !== "portrait" || setup.size !== "A4"}
    >
      <div className="stack">
        <LabeledSelect
          label={labels.pageSizeLabel} help={strings.help.layoutPageSize} value={setup.size} placeholder={null}
          onChange={(size) => set({ size: size as PageSetup["size"] })}
          options={PAGE_SIZES.map((size) => ({ value: size, label: size }))}
        />
        <LabeledSelect
          label={labels.orientationLabel} help={strings.help.layoutOrientation} value={setup.orientation} placeholder={null}
          onChange={(orientation) => set({ orientation: orientation as PageSetup["orientation"] })}
          options={PAGE_ORIENTATIONS.map((value) => ({ value, label: labels.orientationLabels[value] }))}
        />
      </div>
    </SettingsPopoverButton>
  );
}
