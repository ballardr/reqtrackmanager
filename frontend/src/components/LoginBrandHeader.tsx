import { fileUrl } from "../api/client";

/**
 * Logo + centered title shown above a login form (U-C-02-adjacent — the
 * pre-auth equivalent of `Layout.tsx`'s header-bar branding lockup, but a
 * different visual treatment: a centered stacked block on an auth card
 * rather than a small inline horizontal one in a nav bar). Shared between
 * `OrgLoginPage` (org-specific branding) and `LoginPage` (platform-default
 * branding) so the same block isn't duplicated a third time.
 */
export function LoginBrandHeader({ logoFileId, title }: { logoFileId: string | null; title: string }) {
  return (
    <>
      {logoFileId && <img src={fileUrl(logoFileId)} alt="" style={{ height: 40, alignSelf: "center" }} />}
      <h1 style={{ margin: 0, fontSize: "1.4rem", textAlign: "center" }}>{title}</h1>
    </>
  );
}
