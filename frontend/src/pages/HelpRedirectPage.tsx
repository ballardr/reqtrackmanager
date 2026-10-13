/**
 * Module: HelpRedirectPage
 *
 * The old in-app `/help` route. Help now lives on the documentation site (the
 * operator-set `HELP_URL`), so this page only keeps old bookmarks working: it
 * replaces the current history entry with the configured URL, or, when the
 * operator has turned Help off (`HELP_ENABLED=false`), says it is not configured.
 */
import { useEffect } from "react";

import { useClientConfig } from "../hooks/useClientConfig";

/**
 * Redirects to the configured help URL.
 *
 * @param replace - Navigation function; defaults to `window.location.replace`. Injectable so
 *   stories can assert the target without leaving the page.
 */
export function HelpRedirectPage({ replace = (url: string) => window.location.replace(url) }: { replace?: (url: string) => void }) {
  const config = useClientConfig();
  const target = config?.help_enabled ? config.help_url : null;

  useEffect(() => {
    if (target) replace(target);
  }, [target, replace]);

  if (!config || target) return null;
  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>Help</h1>
      <p className="muted">Help is not configured for this deployment.</p>
    </div>
  );
}
