import { LogoBand } from "./LogoBand";

/**
 * Logo and title on one band above a login form: the pre-auth equivalent of `Layout.tsx`'s header branding, drawn
 * as a centred stacked block on an auth card. Shared by `OrgLoginPage` (organisation branding) and `LoginPage`
 * (platform branding).
 *
 * An uploaded logo takes priority and falls back to the built-in logo mark, because a login page with no logo
 * reads as broken, not as "no branding configured".
 *
 * @param logoFileId The logo file, or null for the built-in mark.
 * @param title The name drawn on the band under the logo (the page's heading).
 * @param bandColorHex The resolved band colour, or null for the top bar colour.
 * @param bandTextColorHex The title colour, or null for black or white by contrast with the band.
 */
export function LoginBrandHeader({
  logoFileId, title, bandColorHex, bandTextColorHex = null,
}: { logoFileId: string | null; title: string; bandColorHex: string | null; bandTextColorHex?: string | null }) {
  return <LogoBand colorHex={bandColorHex} textColorHex={bandTextColorHex} logoFileId={logoFileId} title={title} heading bleed />;
}
