/**
 * Parses each file named on the command line with the real Mermaid parser and prints `OK <file>` or `FAIL <file>: <why>`.
 *
 * Used by `backend/app/modules/architecture/tests/test_architecture_state_machine_export.py` to prove the exported text is
 * valid Mermaid. It borrows `mermaid` from `docs/website/node_modules` and `jsdom` from `frontend/node_modules` (run `npm ci`
 * in both); exits with status 2 when either is missing so a caller can skip rather than fail.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const jsdom = join(root, "frontend", "node_modules", "jsdom", "lib", "api.js");
const mermaidModule = join(root, "docs", "website", "node_modules", "mermaid", "dist", "mermaid.core.mjs");
if (!existsSync(jsdom) || !existsSync(mermaidModule)) {
  console.log("UNAVAILABLE");
  process.exit(2);
}

const { JSDOM } = await import(pathToFileURL(jsdom).href);
const dom = new JSDOM("<!doctype html><body></body>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;
const mermaid = (await import(pathToFileURL(mermaidModule).href)).default;

let failed = false;
for (const file of process.argv.slice(2)) {
  try {
    await mermaid.parse(readFileSync(file, "utf8"));
    console.log(`OK ${file}`);
  } catch (error) {
    failed = true;
    console.log(`FAIL ${file}: ${error.message}`);
  }
}
process.exit(failed ? 1 : 0);
