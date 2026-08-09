import mermaid from "mermaid";
import { useEffect, useRef } from "react";

import changeRequestsMd from "../help/03-change-requests.md?raw";
import requirementLifecycleMd from "../help/02-requirement-lifecycle.md?raw";
import reportsMd from "../help/05-reports.md?raw";
import rolesMd from "../help/04-roles.md?raw";
import userAccessMd from "../help/06-user-access.md?raw";
import overviewMd from "../help/01-overview.md?raw";
import { renderMarkdown } from "../utils/markdown";

const SECTIONS = [overviewMd, requirementLifecycleMd, changeRequestsMd, rolesMd, reportsMd, userAccessMd];

/**
 * In-app help: how the app is organised, the requirement lifecycle, change
 * requests, roles/permissions, reports, and self-signup/external users —
 * aimed at end users, not developers (a plain-language version of the
 * roles this project's own `docs/decisions.md` describes for implementers).
 *
 * Content lives in `frontend/src/help/*.md` as plain Markdown files, one
 * per section, imported at build time via Vite's `?raw` loader and run
 * through `utils/markdown.ts`'s small renderer — updating the help page is
 * editing or adding a `.md` file, not touching this component or any JSX.
 * A new file needs one added import line and one entry in `SECTIONS` above;
 * everything else (rendering, spacing) is handled generically.
 *
 * A ```mermaid fenced block in any section's Markdown renders as a real
 * diagram: `renderMarkdown` turns it into `<div class="mermaid">`, and the
 * effect below calls `mermaid.run()` once the HTML is in the DOM — the
 * convention mermaid itself expects, rather than this component needing to
 * know anything about mermaid's rendering internals. Matches the app's
 * current light/dark theme so a diagram doesn't look like a different
 * product to the rest of the page.
 */
export function HelpPage() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    mermaid.initialize({ startOnLoad: false, theme: isDark ? "dark" : "default", fontFamily: "inherit" });
    if (containerRef.current) {
      mermaid.run({ nodes: containerRef.current.querySelectorAll(".mermaid") });
    }
  }, []);

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>Help</h1>
      <div ref={containerRef} className="card stack help-content" style={{ gap: "1.5rem" }}>
        {SECTIONS.map((section, i) => (
          // Static, developer-authored Markdown files, not user input — see utils/markdown.ts's docstring.
          <div key={i} dangerouslySetInnerHTML={{ __html: renderMarkdown(section) }} />
        ))}
      </div>
    </div>
  );
}
