import { useEffect, useRef, useState } from "react";

import { api, apiUrl } from "../api/client";
import type { ModuleFrameToken } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { ConfirmDialog } from "./ConfirmDialog";
import { useResetOnChange } from "../hooks/useResetOnChange";

/** `ThemeProvider` stamps the resolved light/dark theme onto `<html data-theme>`, so reading it directly equals
 * `resolveEffectiveTheme(useTheme().theme)` without a `ThemeContext.Provider` in scope. */
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
  /** The full origin and path the sandboxed iframe loads; it must already have passed the backend's
   * `MODULE_FRAME_ALLOWED_ORIGINS` allowlist (`get_frontend_manifest`) and is not re-validated client-side. */
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
 * Tier B host component: renders a remote, not-installed module in a sandboxed `<iframe>`, relaying shared host
 * chrome (toasts, confirm dialogs) over `postMessage` (the "Host UI Bridge") without handing the module real DOM
 * access or the user's session token.
 *
 * Message contract (origin-checked against `frameUrl`'s origin both ways):
 * - Host to iframe, once on load: `{type: "init", context: {organizationId, projectId, user, theme, cssTokens,
 *   apiBaseUrl, token}}`.
 * - Iframe to host: `{type: "toast", message, variant}` (mapped onto `useToast()`), or `{type: "confirm", id,
 *   title, message, requireTypedText?}` (rendered via `ConfirmDialog`; `requireTypedText` selects the Tier 2
 *   typed confirmation), replied to with `{type: "confirm_result", id, confirmed}`.
 *
 * `sandbox="allow-scripts allow-same-origin allow-forms"`: the module's own origin (never the host's) may run
 * script, use its own storage and cookies and submit forms; top-level navigation, popups and pointer lock stay
 * off. `allow-same-origin` scopes to the iframe's distinct origin and grants no access to this page's DOM.
 */
export function ModuleFrame({ moduleKey, frameUrl, navLabel, organizationId, projectId }: ModuleFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { user } = useAuth();
  const { showToast } = useToast();
  const [token, setToken] = useState<string | null>(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);

  const iframeOrigin = new URL(frameUrl).origin;

  useResetOnChange([moduleKey, organizationId, projectId], () => {
    setToken(null);
    setIframeLoaded(false);
  });

  useEffect(() => {
    let cancelled = false;
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
