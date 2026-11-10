/**
 * Module: components/LogoBand
 *
 * The coloured band behind a logo and the platform or organisation name, so a light logo stays visible on a light
 * surface and the name reads as part of the logo.
 *
 * Responsibilities: draws the logo and the title, stacked and centred, on a full-width band whose colour is the chosen
 * logo band colour, or the application top bar colour when none is chosen (`var(--color-header-bg)`, so the default
 * tracks the stylesheet). The title colour is the chosen one, else black or white by contrast with the band.
 * Used at the top of the sign-in card and in the preview beside the logo band setting.
 */
import { fileUrl } from "../api/client";
import builtInLogo from "../assets/logo.svg";
import { contrastTextHex } from "../utils/color";

/** Colour of the application top bar (`--color-header-bg`), for the contrast choice while the default band is in use. */
export const TOP_BAR_HEX = "#14161c";

/**
 * @param colorHex The band colour (`#rrggbb`), or null for the top bar colour.
 * @param textColorHex The title colour (`#rrggbb`), or null for black or white by contrast with the band.
 * @param logoFileId The logo file, or null for the built-in logo mark.
 * @param title The name drawn under the logo, or undefined for a logo alone.
 * @param heading Draws the title as the page's `h1` (the sign-in card) instead of plain text (a preview).
 * @param bleed Extends the band over the padding of the card it sits in, so it runs edge to edge across its top.
 * @param height Logo height in pixels.
 * @param label Accessible name of the band when it is a preview image.
 */
export function LogoBand({
  colorHex, textColorHex = null, logoFileId, title, heading = false, bleed = false, height = 48, label,
}: {
  colorHex: string | null; textColorHex?: string | null; logoFileId: string | null; title?: string;
  heading?: boolean; bleed?: boolean; height?: number; label?: string;
}) {
  const textColour = textColorHex ?? contrastTextHex(colorHex ?? TOP_BAR_HEX);
  return (
    <div
      className="logo-band"
      role={label ? "img" : undefined}
      aria-label={label}
      data-bleed={bleed || undefined}
      style={{
        background: colorHex ?? "var(--color-header-bg)",
        color: textColour,
        display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center",
        gap: "var(--space-3)",
        padding: "var(--space-5) var(--space-4)",
        ...(bleed
          ? {
              margin: "calc(-1 * var(--space-5)) calc(-1 * var(--space-5)) 0",
              borderRadius: "var(--radius-lg) var(--radius-lg) 0 0",
            }
          : { borderRadius: "var(--radius-md)" }),
      }}
    >
      <img src={logoFileId ? fileUrl(logoFileId) : builtInLogo} alt="" style={{ height }} />
      {title && (heading
        ? <h1 style={{ margin: 0, fontSize: "1.4rem", textAlign: "center", color: "inherit" }}>{title}</h1>
        : <span style={{ fontSize: "1.4rem", fontWeight: 700, textAlign: "center" }}>{title}</span>)}
    </div>
  );
}
