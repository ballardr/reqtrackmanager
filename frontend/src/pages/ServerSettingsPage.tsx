import { useEffect, useRef, useState } from "react";

import { api, fileUrl } from "../api/client";
import type { ServerSettings } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Server-admin console for platform-wide branding defaults — the accent
 * colour, logo, and header title used on any page without a single
 * organisation to brand it, and the fallback for any org that hasn't set
 * its own override (see `frontend/src/context/BrandingContext.tsx` for the
 * full resolution rules).
 */
export function ServerSettingsPage() {
  const [settings, setSettings] = useState<ServerSettings | null>(null);
  const [accentColor, setAccentColor] = useState("#475569");
  const [headerTitle, setHeaderTitle] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logoInputRef = useRef<HTMLInputElement>(null);

  async function reload() {
    const s = await api.get<ServerSettings>("/api/v1/system/branding");
    setSettings(s);
    setAccentColor(s.accent_color_hex);
    setHeaderTitle(s.default_header_title ?? "");
  }

  useEffect(() => {
    reload();
  }, []);

  async function save() {
    setError(null);
    setSaved(false);
    try {
      await api.put("/api/v1/system/branding", {
        accent_color_hex: accentColor,
        default_header_title: headerTitle || null,
      });
      setSaved(true);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function uploadLogo(file: File) {
    await api.postFile("/api/v1/system/branding/logo", file);
    reload();
  }

  if (!settings) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.serverSettings.title}</h1>
      <p className="text-muted" style={{ marginTop: 0 }}>{strings.serverSettings.hint}</p>

      <div className="card stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.serverSettings.logo}
          <input
            ref={logoInputRef}
            type="file"
            accept="image/*"
            onChange={(e) => e.target.files?.[0] && uploadLogo(e.target.files[0])}
          />
        </label>
        {settings.default_logo_file_id && (
          <img src={fileUrl(settings.default_logo_file_id)} alt="" style={{ height: 40 }} />
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.serverSettings.headerTitle}
          <input
            className="input" placeholder={strings.appName}
            value={headerTitle} onChange={(e) => setHeaderTitle(e.target.value)}
          />
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.headerTitleHint}</span>
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.serverSettings.accentColor}
          <input
            type="color" value={accentColor} onChange={(e) => setAccentColor(e.target.value)}
            style={{ width: 60, height: 36, padding: 2 }}
          />
        </label>
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
          {strings.serverSettings.save}
        </button>
        {saved && <div style={{ color: "var(--color-accent)" }}>{strings.serverSettings.saved}</div>}
      </div>
    </div>
  );
}
