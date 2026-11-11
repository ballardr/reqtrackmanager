import { LogoBand } from "./LogoBand";

/**
 * Logo and title on one band shown above a login form (U-C-02-adjacent — the
 * pre-auth equivalent of `Layout.tsx`'s header-bar branding lockup, but a
 * different visual treatment: a centered stacked block on an auth card
 * rather than a small inline horizontal one in a nav bar). Shared between
 * `OrgLoginPage` (org-specific branding) and `LoginPage` (platform-default
 * branding) so the same block isn't duplicated a third time.
 *
 * Mirrors `Layout.tsx`'s fallback: an org/platform-uploaded logo takes
 * priority, falling back to the built-in logo mark rather than rendering
 * nothing — a login page with no logo at all (the previous behaviour when
 * `logoFileId` was null, i.e. the default/unset-branding case) reads as
 * broken, not "no branding configured".
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
