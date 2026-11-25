/**
 * Script: generate-diagram-reference
 *
 * Draws every diagram of the shared corpus in a real browser, with the application's Mermaid version, font and
 * settings, and writes what each drawing is made of: its size and the words it prints. The server's renderer is held to
 * the same file (`converter/tests/test_diagram.py`), and so is the application's own renderer
 * (`src/utils/mermaidReference.stories.tsx`), so the screen and a report cannot drift apart unseen.
 *
 * Run from `frontend/` (Node 26, `npm ci` done, Playwright's Chromium installed):
 *   node scripts/generate-diagram-reference.mjs
 * It rewrites `converter/tests/diagram_reference.json` and the two copies the stories read
 * (`src/utils/diagramCorpus.json`, `src/utils/diagramReference.json`).
 *
 * Design decisions:
 * - The page is 1000 px wide: a few diagram types (Gantt, C4) take the width of their container, and the server draws
 *   them at 1000. Their size is therefore recorded but not compared (`size: "container"` in the corpus).
 * - The words are compared as a multiset after dropping what is random or an artefact of serialising (a Git graph's
 *   commit identifier, a trailing `/` on a self-closed tag), the same rule as `converter/tests/test_diagram.py`.
 *
 * Dependencies: `playwright` (a dev dependency), `mermaid/dist/mermaid.min.js`, the font in `src/assets/fonts/`.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const corpusPath = path.resolve(root, "../converter/tests/diagram_corpus.json");
const referencePath = path.resolve(root, "../converter/tests/diagram_reference.json");
const config = JSON.parse(fs.readFileSync(path.join(root, "src/utils/mermaidRenderConfig.json"), "utf8"));
const corpus = JSON.parse(fs.readFileSync(corpusPath, "utf8"));
const font = fs.readFileSync(path.join(root, "src/assets/fonts/DejaVuSans-diagram.woff2")).toString("base64");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
await page.setContent("<html><body></body></html>");
await page.addScriptTag({ path: path.join(root, "node_modules/mermaid/dist/mermaid.min.js") });
await page.evaluate(async ({ font, family }) => {
  const bytes = Uint8Array.from(atob(font), (c) => c.charCodeAt(0));
  const face = new FontFace(family, bytes.buffer);
  document.fonts.add(await face.load());
}, { font, family: config.fontFamily });

const reference = [];
let counter = 0;
for (const entry of corpus) {
  const drawn = await page.evaluate(async ({ source, id, config }) => {
    mermaid.initialize({
      startOnLoad: false, securityLevel: "strict", theme: "default", fontFamily: `"${config.fontFamily}"`, htmlLabels: false,
      flowchart: { htmlLabels: false }, maxTextSize: config.limits.sourceChars, maxEdges: config.limits.edges, suppressErrorRendering: true,
    });
    try {
      const { svg } = await mermaid.render(id, source);
      const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
      const box = (doc.documentElement.getAttribute("viewBox") ?? "0 0 0 0").trim().split(/[ ,]+/).map(Number);
      const words = {};
      for (const element of doc.querySelectorAll("text, tspan, title, desc")) {
        for (const node of element.childNodes) {
          if (node.nodeType !== Node.TEXT_NODE) continue;
          for (let word of (node.textContent ?? "").split(/\s+/)) {
            word = word.replace(/\/$/, "");
            if (word === "" || /^\d+-[0-9a-f]{7}$/.test(word)) continue;
            words[word] = (words[word] ?? 0) + 1;
          }
        }
      }
      return { width: box[2], height: box[3], words };
    } catch (error) {
      return { error: String((error && error.message) || error).split("\n")[0] };
    }
  }, { source: entry.source, id: `d${++counter}`, config });
  if (drawn.error) throw new Error(`${entry.name}: ${drawn.error}`);
  reference.push({ name: entry.name, size: entry.size, ...drawn });
}
await browser.close();

const text = `${JSON.stringify(reference, null, 1)}\n`;
fs.writeFileSync(referencePath, text);
fs.writeFileSync(path.join(root, "src/utils/diagramReference.json"), text);
fs.copyFileSync(corpusPath, path.join(root, "src/utils/diagramCorpus.json"));
console.log(`${reference.length} diagrams written`);
