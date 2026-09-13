import { useEffect, useRef, useState } from "react";

import { api, apiUrl } from "../api/client";
import type { ModuleFrameToken } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { ConfirmDialog } from "./ConfirmDialog";

/** The app's `ThemeProvider` (`context/ThemeContext.tsx`) always stamps the
 * *resolved* light/dark theme onto `<html data-theme>` — reading it
 * directly here is equivalent to `resolveEffectiveTheme(useTheme().theme)`
 * without needing a `ThemeContext.Provider` in scope (this is the only
 * shared component below the app shell that needs the current theme at
 * all; everything else resolves purely through CSS custom properties
 * cascading off that same attribute). */
function currentResolvedTheme(): "light" | "dark" {
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit === "dark" || explicit === "light") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const HOST_CSS_TOKEN_NAMES = [
  "--color-bg", "--color-surface", "--color-surface-alt", "--color-border",
  "--color-text", "--color-text-muted", "--color-primary", "--color-primary-hover",
  "--color-primary-contrast", "--color-accent", "--color-danger", "--color-warning",
];

function readHostCssTokens(): Record<string, string> {
  const computed = getComputedStyle(document.documentElement);
  const tokens: Record<string, string> = {};
  for (const name of HOST_CSS_TOKEN_NAMES) {
    const value = computed.getPropertyValue(name).trim();
    if (value) tokens[name] = value;
  }
  return tokens;
}

interface PendingConfirm {
  id: string;
  title: string;
  message: string;
  requireTypedText?: string;
}

interface ModuleFrameProps {
  /** The module this iframe belongs to — used to mint a token scoped to
   * exactly this module (backend `create_module_frame_token`). */
  moduleKey: string;
  /** The full origin+path the sandboxed iframe loads — must already have
   * passed the backend's `MODULE_FRAME_ALLOWED_ORIGINS` allowlist check
   * (`get_frontend_manifest`) for this component to have been rendered at
   * all; not re-validated client-side. */
  frameUrl: string;
  /** Display label, used as the iframe's accessible title. */
  navLabel: string;
  /** Exactly one of `organizationId`/`projectId` must be given — determines
   * which frame-token minting endpoint (org- or project-scoped) is called,
   * and what the resulting token is scoped to. */
  organizationId?: string;
  projectId?: string;
}

/**
 * Tier B host component (compliance-module-plan.md Phase 3): renders a
 * remote, not-installed module in a sandboxed `<iframe>`, relaying shared
 * host chrome (toasts, confirm dialogs) over `postMessage` — the "Host UI
 * Bridge" — so a remote module's UI still feels native for what matters
 * most, without the host ever handing it real DOM access or the current
 * user's actual session token.
 *
 * Message contract (host origin-checked against `frameUrl`'s own origin
 * both ways):
 * - Host → iframe, once on load: `{type: "init", context: {organizationId,
 *   projectId, user, theme, cssTokens, apiBaseUrl, token}}`.
 * - Iframe → host: `{type: "toast", message, variant}` (mapped onto the
 *   host's real `useToast()`), or `{type: "confirm", id, title, message,
 *   requireTypedText?}` (rendered via the host's real `ConfirmDialog`,
 *   `requireTypedText` present selecting its Tier 2 typed-confirmation
 *   variant), replied to with `{type: "confirm_result", id, confirmed}`.
 *
 * `sandbox="allow-scripts allow-same-origin allow-forms"`: the module's own
 * origin (never the host's) may run script, use its own storage/cookies,
 * and submit forms — everything else `sandbox` restricts by default
 * (top-level navigation, popups, pointer lock, etc.) stays off. `allow-
 * same-origin` here scopes to the iframe's *own* distinct origin, not the
 * host's — it does not grant the module access to this page's DOM/storage.
 */
export function ModuleFrame({ moduleKey, frameUrl, navLabel, organizationId, projectId }: ModuleFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { user } = useAuth();
  const { showToast } = useToast();
  const [token, setToken] = useState<string | null>(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);

  const iframeOrigin = new URL(frameUrl).origin;

  useEffect(() => {
    let cancelled = false;
    setToken(null);
    setIframeLoaded(false);
    const mintPath = projectId
      ? `/api/v1/projects/${projectId}/modules/${moduleKey}/frame-token`
      : `/api/v1/orgs/${organizationId}/modules/${moduleKey}/frame-token`;
    api.post<ModuleFrameToken>(mintPath).then((result) => {
      if (!cancelled) setToken(result.token);
    });
    return () => {
      cancelled = true;
    };
  }, [moduleKey, organizationId, projectId]);

  useEffect(() => {
    if (!token || !iframeLoaded || !user) return;
    iframeRef.current?.contentWindow?.postMessage(
      {
        type: "init",
        context: {
          organizationId: organizationId ?? null,
          projectId: projectId ?? null,
          user: { id: user.id, displayName: user.display_name },
          theme: currentResolvedTheme(),
          cssTokens: readHostCssTokens(),
          apiBaseUrl: apiUrl(""),
          token,
        },
      },
      iframeOrigin
    );
  }, [token, iframeLoaded, iframeOrigin, organizationId, projectId, user]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== iframeOrigin) return;
      if (!iframeRef.current || event.source !== iframeRef.current.contentWindow) return;
      const data = event.data as { type?: unknown } | null;
      if (!data || typeof data !== "object") return;

      if (data.type === "toast") {
        const { message, variant } = data as { message?: unknown; variant?: unknown };
        showToast(String(message ?? ""), variant === "error" ? "error" : "success");
        return;
      }
      if (data.type === "confirm") {
        const { id, title, message, requireTypedText } = data as {
          id?: unknown; title?: unknown; message?: unknown; requireTypedText?: unknown;
        };
        setPendingConfirm({
          id: String(id ?? ""),
          title: String(title ?? ""),
          message: String(message ?? ""),
          requireTypedText: typeof requireTypedText === "string" ? requireTypedText : undefined,
        });
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [iframeOrigin, showToast]);

  function replyConfirm(confirmed: boolean) {
    if (!pendingConfirm) return;
    iframeRef.current?.contentWindow?.postMessage(
      { type: "confirm_result", id: pendingConfirm.id, confirmed }, iframeOrigin
    );
    setPendingConfirm(null);
  }

  return (
    <div style={{ height: "100%", width: "100%" }}>
      <iframe
        ref={iframeRef}
        src={frameUrl}
        title={navLabel}
        sandbox="allow-scripts allow-same-origin allow-forms"
        style={{ width: "100%", height: "100%", border: "none" }}
        onLoad={() => setIframeLoaded(true)}
      />
      {pendingConfirm && (
        <ConfirmDialog
          title={pendingConfirm.title}
          message={pendingConfirm.message}
          confirmLabel="Confirm"
          requireTypedText={pendingConfirm.requireTypedText}
          onConfirm={() => replyConfirm(true)}
          onCancel={() => replyConfirm(false)}
        />
      )}
    </div>
  );
}
