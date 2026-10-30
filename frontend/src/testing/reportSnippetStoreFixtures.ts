/**
 * Module: testing/reportSnippetStoreFixtures
 *
 * Storybook-only fake `ReportSnippetStoreApi`: answers the save dialog's check and save, and the snippets panel's list, edit,
 * copy, delete, hide and restore the way the server would (what a selection carries, a project picture refused at the
 * organisation level, a taken name), so the dialog and the panel can be driven without a server.
 */
import { fn } from "storybook/test";

import { ApiError } from "../api/client";
import type { LayoutScope, ReportLayoutTree } from "../api/reportLayouts";
import type { ReportSnippetStoreApi, SavedSnippet, SnippetCheck, SnippetLevel, SnippetSelection } from "../api/reportSnippets";

/** A saved snippet; the fields not given are those of a project's own plain heading block. */
export function buildSavedSnippet(overrides: Partial<SavedSnippet> = {}): SavedSnippet {
  return {
    id: "snippet-1", key: "saved-snippet-1", organization_id: "org-1", project_id: "project-1", name: "House risk table",
    description: "Heading and a table of risks in the house style.", category: "House style", family: "document", origin: "project",
    hidden: false, editable: true, blocks: 2, page_styles: [], variables: [], updated_at: "2026-10-30T09:00:00Z", ...overrides,
  };
}

/** Three snippets as a project sees them: its own, the organisation's, and a parent project's that it has hidden. */
export function buildSavedSnippets(): SavedSnippet[] {
  return [
    buildSavedSnippet(),
    buildSavedSnippet({
      id: "snippet-2", key: "saved-snippet-2", project_id: null, name: "Approval footer", description: "", category: "House style", origin: "organization",
      editable: false, blocks: 1, page_styles: ["Wide"],
    }),
    buildSavedSnippet({
      id: "snippet-3", key: "saved-snippet-3", name: "Audience note", category: "Notes", origin: "ancestor", editable: false, hidden: true, blocks: 1,
      variables: ["audience"],
    }),
  ];
}

/** Whether a tree has a picture block anywhere in its blocks. */
function hasImage(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(hasImage);
  if (value !== null && typeof value === "object") {
    const node = value as Record<string, unknown>;
    return node.type === "image" || Object.values(node).some(hasImage);
  }
  return false;
}

/**
 * @param snippets The saved snippets the scope reaches.
 * @param scope The scope the API is bound to (a project by default).
 * @param carries What every check says the selection carries.
 * @param taken Lower-cased names a save or rename is refused for (409).
 * @param projectPictureBlocksUp Whether a selection holding a picture is refused at the organisation level, as a project picture is.
 * @param copyUpRefused Ids of snippets whose copy up to the organisation is refused because they hold a project picture.
 */
export function buildSnippetStoreApi(
  snippets: SavedSnippet[] = buildSavedSnippets(),
  { scope = { kind: "project", id: "project-1" }, carries = {}, taken = [], projectPictureBlocksUp = true, copyUpRefused = [] }:
    {
      scope?: LayoutScope; carries?: Partial<Pick<SnippetCheck, "page_styles" | "variables">>; taken?: string[]; projectPictureBlocksUp?: boolean;
      copyUpRefused?: string[];
    } = {},
): ReportSnippetStoreApi {
  const store = snippets.map((s) => ({ ...s }));
  const check = (tree: ReportLayoutTree, selection: SnippetSelection, level: SnippetLevel): SnippetCheck => {
    if (level === "organization" && projectPictureBlocksUp && hasImage(tree.nodes)) {
      return {
        ok: false, blocks: 0, page_styles: [], variables: [],
        errors: [{ path: "nodes[0].file", message: '"site-logo.png" is not in the organisation\'s library. An organisation layout can only use organisation images.' }],
      };
    }
    return { ok: selection.count > 0, errors: [], blocks: selection.count, page_styles: carries.page_styles ?? [], variables: carries.variables ?? [] };
  };
  const fake: ReportSnippetStoreApi = {
    scope,
    list: fn(async () => store.map((s) => ({ ...s }))),
    check: fn(async (tree: ReportLayoutTree, selection: SnippetSelection, level: SnippetLevel) => check(tree, selection, level)),
    save: fn(async (body, level) => {
      if (taken.includes(body.name.trim().toLowerCase())) throw new ApiError(409, `A saved snippet called "${body.name}" already exists here.`);
      const made = buildSavedSnippet({
        id: `snippet-${store.length + 1}`, key: `saved-snippet-${store.length + 1}`, name: body.name, description: body.description,
        category: body.category || "Saved", project_id: level === "project" && scope.kind === "project" ? scope.id : null,
        origin: level === "project" && scope.kind === "project" ? "project" : "organization",
      });
      store.push(made);
      return made;
    }),
    update: fn(async (id, body) => {
      const found = store.find((s) => s.id === id) ?? store[0];
      if (body.name && taken.includes(body.name.trim().toLowerCase())) throw new ApiError(409, "A saved snippet with this name already exists here.");
      Object.assign(found, body);
      return { ...found };
    }),
    remove: fn(async (id: string) => {
      const at = store.findIndex((s) => s.id === id);
      if (at >= 0) store.splice(at, 1);
    }),
    copy: fn(async (id, body) => {
      const source = store.find((s) => s.id === id) ?? store[0];
      if (body.target === "organization" && copyUpRefused.includes(id)) {
        throw new ApiError(422, "The snippet cannot be saved.", {
          message: "The snippet cannot be saved.", errors: [{ path: "nodes[0].file", message: '"site-logo.png" is not in the organisation\'s library.' }],
        });
      }
      const made = { ...source, id: `snippet-${store.length + 1}`, key: `saved-snippet-${store.length + 1}`, name: `${source.name} (copy)`, editable: true, hidden: false };
      store.push(made);
      return made;
    }),
  };
  if (scope.kind === "project") {
    fake.setHidden = fn(async (id: string, hidden: boolean) => {
      const found = store.find((s) => s.id === id) ?? store[0];
      found.hidden = hidden;
      return { ...found };
    });
    fake.restore = fn(async (ids: string[]) => {
      for (const s of store) if (ids.includes(s.id)) s.hidden = false;
    });
  }
  return fake;
}
