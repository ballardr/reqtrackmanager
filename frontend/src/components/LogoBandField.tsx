/**
 * Module: components/LogoBandField
 *
 * The settings for the band behind the logo and the name on it, shared by the platform Branding page and the
 * organisation Branding & defaults page.
 *
 * Responsibilities: a band colour field and a title colour field, each showing the colour in use with a Remove button
 * while a colour is chosen (the way back to the default; a colour cannot be empty), a live preview of the band with
 * the current logo and name, and warnings while the band is light or the title is hard to read on it. The warnings
 * never block saving: a dark logo on a light band is legitimate.
 * The band default is the application top bar colour, or the platform colour on an organisation page that has one;
 * the title default is black or white by contrast with the band.
 */
import { t } from "../i18n/strings";
import { contrastRatio, contrastTextHex } from "../utils/color";
import { ColorField } from "./FormFields";
import { InlineMessage } from "./InlineMessage";
import { LogoBand, TOP_BAR_HEX } from "./LogoBand";

const strings = t();

/** The least contrast against white below which a band is warned about as light. */
const LIGHT_BAND_CONTRAST = 3;
/** The least contrast between the title and the band below which the title is warned about as hard to read. */
const READABLE_TEXT_CONTRAST = 3;

/**
 * @param value The chosen band colour, or "" when none is chosen.
 * @param onChange Called with a `#rrggbb` colour, or "" when the colour is removed.
 * @param textValue The chosen title colour, or "" when none is chosen.
 * @param onTextChange Called with a `#rrggbb` colour, or "" when the colour is removed.
 * @param logoFileId The logo drawn in the preview, or null for the built-in mark.
 * @param title The name drawn under the logo in the preview.
 * @param platformHex The platform band colour an organisation falls back to, or null for the top bar colour.
 * @param platformTextHex The platform title colour an organisation falls back to, or null for automatic.
 */
export function LogoBandField({
  value, onChange, textValue, onTextChange, logoFileId, title, platformHex = null, platformTextHex = null,
}: {
  value: string; onChange: (hex: string) => void; textValue: string; onTextChange: (hex: string) => void;
  logoFileId: string | null; title: string; platformHex?: string | null; platformTextHex?: string | null;
}) {
  const band = value || platformHex || TOP_BAR_HEX;
  const text = textValue || platformTextHex || contrastTextHex(band);
  const light = contrastRatio(band, "#ffffff") < LIGHT_BAND_CONTRAST;
  const hardToRead = contrastRatio(band, text) < READABLE_TEXT_CONTRAST;
  return (
    <div className="stack">
      <ColorField help={strings.help.logoBand} label={strings.logoBand.label} value={band} onChange={onChange} />
      {value && (
        <div className="row">
          <button type="button" className="btn btn-sm" onClick={() => onChange("")}>{strings.common.remove}</button>
        </div>
      )}
      <ColorField help={strings.help.logoBandText} label={strings.logoBand.textLabel} value={text} onChange={onTextChange} />
      {textValue && (
        <div className="row">
          <button type="button" className="btn btn-sm" onClick={() => onTextChange("")}>{strings.common.remove}</button>
        </div>
      )}
      <LogoBand colorHex={band} textColorHex={text} logoFileId={logoFileId} title={title} label={strings.logoBand.previewLabel} />
      {light && <InlineMessage tone="warning">{strings.logoBand.lightWarning}</InlineMessage>}
      {hardToRead && <InlineMessage tone="warning">{strings.logoBand.textWarning}</InlineMessage>}
    </div>
  );
}
