import { fileUrl } from "../api/client";
import builtInLogo from "../assets/logo.svg";

/**
 * Logo + centered title shown above a login form (U-C-02-adjacent — the
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
 */
export function LoginBrandHeader({ logoFileId, title }: { logoFileId: string | null; title: string }) {
  return (
    <>
      <img
        src={logoFileId ? fileUrl(logoFileId) : builtInLogo}
        alt=""
        style={{ height: 40, alignSelf: "center" }}
      />
      <h1 style={{ margin: 0, fontSize: "1.4rem", textAlign: "center" }}>{title}</h1>
    </>
  );
}
