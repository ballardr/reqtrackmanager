/**
 * Module: testing/licenceFixtures
 *
 * A small third-party inventory and a `fetch` stand-in for the stories of the Licences group (Policies page), so they
 * read the same static assets the application does without the 2 MB generated files.
 */
import { spyOn } from "storybook/test";

import type { ThirdPartyNotices } from "../hooks/useThirdPartyNotices";

export const MIT_TEXT = "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software.";
export const OFL_TEXT = "SIL OPEN FONT LICENSE Version 1.1\n\nPERMISSION & CONDITIONS";

/** An inventory with an npm library, a Python library under library copyleft, a program, a base image and two fonts. */
export function buildThirdPartyNotices(overrides: Partial<ThirdPartyNotices> = {}): ThirdPartyNotices {
  return {
    schema: 1,
    components: [{ id: "backend", title: "Backend API image" }, { id: "frontend", title: "Front-end application (bundled)" }],
    packages: [
      { ecosystem: "npm", name: "react", version: "19.2.0", components: ["frontend"], direct: true, licence: "MIT", licence_source: "metadata", review: "none", texts: ["mit"], link: "https://www.npmjs.com/package/react/v/19.2.0" },
      { ecosystem: "python", name: "svglib", version: "1.6.0", components: ["backend"], direct: true, licence: "LGPL-3.0-or-later", licence_source: "override", review: "notice", texts: [], link: "https://pypi.org/project/svglib/1.6.0/" },
      { ecosystem: "npm", name: "zod", version: "4.1.0", components: ["frontend"], direct: false, licence: "MIT", licence_source: "metadata", review: "none", texts: ["mit"], link: "https://www.npmjs.com/package/zod/v/4.1.0" },
    ],
    system_components: [
      {
        name: "Ghostscript", licence: "AGPL-3.0-or-later", images: ["converter"], role: "Converts uploaded EPS logos to SVG.",
        reason: "Runs as a separate process inside the converter container; never linked into this product's code.",
        source: "https://ghostscript.com/releases/", use: "separate-program", packages: ["ghostscript"],
      },
    ],
    base_images: { "python:3.15-slim": { licence: "Mixed (Debian packages)", images: ["backend"], note: "Debian slim." } },
    fonts: [
      { name: "Liberation Sans", licence: "OFL-1.1", where: "backend: report fonts", files: "backend/app/assets/report_fonts/", note: "Default report fonts.", texts: ["ofl"] },
      { name: "KaTeX fonts", licence: "OFL-1.1", where: "frontend: mathematics", files: "bundled by the katex package", note: "Mathematics.", texts: [] },
    ],
    library_copyleft_reasons: { "python:svglib": "Used unmodified and replaceable by the operator." },
    notes: ["Grafana, Loki, Tempo and Alloy are optional services that Compose pulls from their publishers."],
    ...overrides,
  };
}

/**
 * Replaces `window.fetch` for the two licence assets; any other request fails the story.
 *
 * @param notices The inventory to serve; `null` makes the inventory request fail with a 500.
 */
export function mockLicenceFetch(notices: ThirdPartyNotices | null = buildThirdPartyNotices()): void {
  spyOn(window, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/licences/third-party-notices.json")) {
      return notices ? new Response(JSON.stringify(notices), { status: 200 }) : new Response("", { status: 500 });
    }
    if (url.endsWith("/licences/third-party-texts.json")) return new Response(JSON.stringify({ mit: MIT_TEXT, ofl: OFL_TEXT }), { status: 200 });
    throw new Error(`unmocked fetch in a licence story: ${url}`);
  });
}
