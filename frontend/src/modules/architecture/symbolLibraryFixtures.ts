/**
 * Module: modules/architecture/symbolLibraryFixtures
 *
 * Story fixtures for the symbol library page: library rows, and a read mock that answers the page's requests the way the
 * server does (filter, sort, page, usage, folders, capabilities), so a story exercises the page and asserts the query it sent.
 */
import { spyOn } from "storybook/test";

import { api, ApiError } from "../../api/client";
import { SYMBOL_SVG } from "./architectureFixtures";
import type {
  ArchitectureFolder, SymbolLibraryFolder, SymbolLibraryPage, SymbolLibraryRow, SymbolUsage,
} from "./types";

/** A library row; each field defaults to an uploaded organisation symbol used by nothing. */
export function buildSymbolRow(overrides: Partial<SymbolLibraryRow> = {}): SymbolLibraryRow {
  return {
    id: "sym-x", project_id: null, organization_id: "org-1", name: "Router", builtin_key: null, is_builtin: false, sort_order: 0,
    tier: "organization", folder_id: null, folder_path: null, file_type: "svg", can_file: true, usage_count: 0, used_by: [],
    usage_owner_count: 0, ...overrides,
  };
}

/** A built-in organisation symbol (not filed, not renamed). */
export function buildBuiltinRow(overrides: Partial<SymbolLibraryRow> = {}): SymbolLibraryRow {
  return buildSymbolRow({ id: "sym-b", name: "Server", builtin_key: "server", is_builtin: true, file_type: "builtin", can_file: false, ...overrides });
}

/** A symbol folder. */
export function buildSymbolFolder(overrides: Partial<ArchitectureFolder> = {}): ArchitectureFolder {
  const name = overrides.name ?? "Network";
  return {
    id: "sf-1", project_id: null, organization_id: "org-1", kind: "symbol", name, parent_id: null, sort_order: 0, path: name,
    record_count: 0, ...overrides,
  };
}

/** What `mockSymbolLibrary` answers with. */
export interface SymbolLibraryReads {
  rows: SymbolLibraryRow[];
  folders?: ArchitectureFolder[];
  organizationFolders?: SymbolLibraryFolder[];
  usage?: Record<string, SymbolUsage>;
  hidden?: { id: string; name: string }[];
  canManage?: boolean;
  converter?: boolean;
  /** Rows to answer per scope id, for a story that renders two libraries side by side (the long-text stress). */
  rowsByScope?: Record<string, SymbolLibraryRow[]>;
}

/**
 * Answers the GET requests of the symbol library page like the server does. Returns the spy so a story can read the
 * requests it saw (`libraryQueries`).
 *
 * @param reads The rows and the rest of what the server holds.
 */
export function mockSymbolLibrary(reads: SymbolLibraryReads) {
  spyOn(api, "getForBlob").mockResolvedValue(SYMBOL_SVG);
  return spyOn(api, "get").mockImplementation(async (path: string) => {
    const [base, query = ""] = path.split("?");
    const params = new URLSearchParams(query);
    if (base.endsWith("/modules/architecture/capabilities")) return { manage_types: reads.canManage ?? true };
    if (base.endsWith("/symbols/library")) {
      const scopeId = /\/(?:orgs|projects)\/([^/]+)\//.exec(base)?.[1] ?? "";
      return answerLibrary(reads.rowsByScope?.[scopeId] ?? reads.rows, params, reads);
    }
    const usage = /\/symbols\/([^/]+)\/usage$/.exec(base);
    if (usage) return reads.usage?.[usage[1]] ?? { owners: [] };
    if (base.endsWith("/symbols/hidden")) return reads.hidden ?? [];
    if (base.endsWith("/symbol-folders")) return reads.folders ?? [];
    throw new ApiError(404, "Not found.");
  });
}

/** The library requests (query strings) a `mockSymbolLibrary` spy has seen, oldest first. */
export function libraryQueries(spy: ReturnType<typeof mockSymbolLibrary>): URLSearchParams[] {
  return spy.mock.calls
    .map((call) => String(call[0]))
    .filter((path) => path.includes("/symbols/library"))
    .map((path) => new URLSearchParams(path.split("?")[1] ?? ""));
}

function answerLibrary(all: SymbolLibraryRow[], params: URLSearchParams, reads: SymbolLibraryReads): SymbolLibraryPage {
  const search = (params.get("search") ?? "").toLowerCase();
  let rows = all.filter((r) => {
    if (search && !r.name.toLowerCase().includes(search)) return false;
    if (params.get("source") === "builtin" && !r.is_builtin) return false;
    if (params.get("source") === "uploaded" && r.is_builtin) return false;
    if (params.get("used") === "used" && r.usage_count === 0) return false;
    if (params.get("used") === "unused" && r.usage_count > 0) return false;
    if (params.get("file_type") && r.file_type !== params.get("file_type")) return false;
    const folder = params.get("folder");
    if (folder) {
      const path = r.folder_path ?? "";
      const inside = path === folder || (params.get("subfolders") !== "false" && path.startsWith(`${folder}/`));
      if (!inside) return false;
    }
    return true;
  });
  const sort = params.get("sort");
  if (sort) {
    const key = (r: SymbolLibraryRow) => (sort === "folder" ? (r.folder_path ?? "") : sort === "source" ? (r.is_builtin ? "0" : "1") : r.name).toLowerCase();
    rows = [...rows].sort((a, b) => key(a).localeCompare(key(b)) * (params.get("order") === "desc" ? -1 : 1));
  }
  const offset = Number(params.get("offset") ?? 0);
  const limit = Number(params.get("limit") ?? 100);
  return {
    items: rows.slice(offset, offset + limit), total: rows.length, library_total: all.length, offset, limit,
    converter_available: reads.converter ?? false, organization_folders: reads.organizationFolders ?? [],
  };
}
