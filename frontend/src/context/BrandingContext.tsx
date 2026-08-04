import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { Organization, Project, ServerSettings } from "../api/types";
import { t } from "../i18n/strings";
import { contrastTextHex, ensureContrast } from "../utils/color";
import { resolveEffectiveTheme, useTheme } from "./ThemeContext";

const strings = t();

const LIGHT_BG_HEX = "#eef1f5";
const DARK_BG_HEX = "#14181f";
const DEFAULT_ACCENT_HEX = "#475569";

export interface Branding {
  logoFileId: string | null;
  headerTitle: string;
  accentColorHex: string;
}

const DEFAULT_BRANDING: Branding = { logoFileId: null, headerTitle: strings.appName, accentColorHex: DEFAULT_ACCENT_HEX };

const BrandingContext = createContext<Branding>(DEFAULT_BRANDING);

function fromOrg(org: Organization, serverDefault: Branding): Branding {
  return {
    logoFileId: org.logo_file_id ?? serverDefault.logoFileId,
    headerTitle: org.header_title || serverDefault.headerTitle,
    accentColorHex: org.accent_color_hex ?? serverDefault.accentColorHex,
  };
}

/**
 * Resolves which organisation's branding (logo, header wordmark, accent
 * colour) applies to the current page, and applies the accent colour to
 * `--color-primary`/`--color-primary-contrast` live.
 *
 * Resolution order:
 * - Inside a project's URL space: that project's own organisation,
 *   falling back field-by-field to the platform default (`ServerSettings`)
 *   for whichever of logo/title/colour that org hasn't set.
 * - Everywhere else (org list, global projects list, Preferences,
 *   server-management pages — no single org is "the" context): if the
 *   viewer belongs to exactly one organisation, that org's branding is
 *   used there too; otherwise (no orgs, or more than one) the platform
 *   default applies, since there's no single right answer to whose
 *   branding should show.
 *
 * One accent colour is stored, not two — `ensureContrast` derives a
 * lightened variant for dark theme and a darkened variant for light theme
 * on demand, so the same brand colour reads correctly as link/accent text
 * against either page background, and the effect re-applies whenever the
 * resolved light/dark theme changes, not just when the colour itself does.
 */
export function BrandingProvider({ projectId, children }: { projectId: string | null; children: ReactNode }) {
  const [branding, setBranding] = useState<Branding>(DEFAULT_BRANDING);
  const { theme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const serverSettings = await api.get<ServerSettings>("/api/v1/system/branding");
      const serverDefault: Branding = {
        logoFileId: serverSettings.default_logo_file_id,
        headerTitle: serverSettings.default_header_title || strings.appName,
        accentColorHex: serverSettings.accent_color_hex,
      };

      if (projectId) {
        const project = await api.get<Project>(`/api/v1/projects/${projectId}`);
        const org = await api.get<Organization>(`/api/v1/orgs/${project.organization_id}`);
        if (!cancelled) setBranding(fromOrg(org, serverDefault));
        return;
      }

      const orgs = await api.get<Organization[]>("/api/v1/orgs");
      if (cancelled) return;
      setBranding(orgs.length === 1 ? fromOrg(orgs[0], serverDefault) : serverDefault);
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    const effectiveTheme = resolveEffectiveTheme(theme);
    const backgroundHex = effectiveTheme === "dark" ? DARK_BG_HEX : LIGHT_BG_HEX;
    const primary = ensureContrast(branding.accentColorHex, backgroundHex, 4.5, effectiveTheme === "dark");
    document.documentElement.style.setProperty("--color-primary", primary);
    document.documentElement.style.setProperty("--color-primary-contrast", contrastTextHex(primary));
  }, [branding.accentColorHex, theme]);

  return <BrandingContext.Provider value={branding}>{children}</BrandingContext.Provider>;
}

/** The resolved branding (logo/title/accent colour) for the current page —
 * see `BrandingProvider`'s docstring for the resolution rules. */
export function useBranding(): Branding {
  return useContext(BrandingContext);
}
