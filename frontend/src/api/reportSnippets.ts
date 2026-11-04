/**
 * Module: api/reportSnippets
 *
 * Types and calls for author-saved report snippets: a named fragment of a layout that an organisation or project keeps and
 * inserts into other layouts. Inserting one is `ReportLayoutApi.snippets` / `applySnippet` (saved snippets are listed
 * beside the built-in set); this module is saving a selection of a draft or a whole edited tree, managing the saved ones, copying them between
 * tiers and hiding or restoring an inherited one. Two tiers with one shape (`/orgs/{id}/report-snippets`,
 * `/projects/{id}/report-snippets`), so {@link ReportSnippetStoreApi} is one injectable interface bound to a scope by
 * {@link reportSnippetStoreApi}; the project tier adds hiding and restoring.
 */
import { api } from "./client";
import type { LayoutFamily, LayoutOrigin, LayoutScope, ReportLayoutTree } from "./reportLayouts";

/** A saved snippet as one scope sees it (`SavedReportSnippetOut`). */
export interface SavedSnippet {
  id: string;
  /** The key `applySnippet` takes. */
  key: string;
  organization_id: string;
  project_id: string | null;
  name: string;
  description: string;
  category: string;
  family: LayoutFamily;
  origin: LayoutOrigin;
  hidden: boolean;
  /** Whether the asking scope owns it (it can rename and delete it). */
  editable: boolean;
  /** How many blocks it inserts, counting those inside containers. */
  blocks: number;
  page_styles: string[];
  variables: string[];
  updated_at: string;
}

/** A saved snippet with its fragment (`SavedReportSnippetDetailOut`): the blocks it inserts and the page styles and variables they use. */
export interface SavedSnippetDetail extends SavedSnippet {
  nodes: ReportLayoutTree[];
  root: Record<string, unknown>;
}

/** A run of blocks of a draft: `count` blocks from `start` in the list `container` (`nodes`, `nodes[2].children`). */
export interface SnippetSelection {
  container: string;
  start: number;
  count: number;
}

/** Where a snippet is saved: the project asking, or up to the organisation. */
export type SnippetLevel = "project" | "organization";

/** What saving a selection would store, or why it cannot (`ReportSnippetCheckOut`). */
export interface SnippetCheck {
  ok: boolean;
  errors: { path: string; message: string }[];
  blocks: number;
  page_styles: string[];
  variables: string[];
}

/** The details a snippet is saved with. */
export interface SnippetDetails {
  name: string;
  description: string;
  category: string;
}

/** The calls the save dialog and the snippets panel make, bound to one scope (injectable so stories stay off the network). */
export interface ReportSnippetStoreApi {
  scope: LayoutScope;
  /** The saved snippets the scope can reach (a project's includes hidden ones, flagged). */
  list(): Promise<SavedSnippet[]>;
  /** What saving the selection at `level` would store (nothing is stored). */
  check(tree: ReportLayoutTree, selection: SnippetSelection, level: SnippetLevel): Promise<SnippetCheck>;
  /** Saves the selection as a snippet at `level`. */
  save(body: SnippetDetails & { tree: ReportLayoutTree; selection: SnippetSelection }, level: SnippetLevel): Promise<SavedSnippet>;
  /** One snippet with its blocks. */
  get(id: string): Promise<SavedSnippetDetail>;
  /** Changes the details and, when `tree` is given, replaces the blocks with all the blocks of that tree. */
  update(id: string, body: Partial<SnippetDetails> & { tree?: ReportLayoutTree }): Promise<SavedSnippet>;
  remove(id: string): Promise<void>;
  /** Copies a snippet into the scope's own tier (`project`), or up to the organisation. */
  copy(id: string, body: { target: SnippetLevel; name?: string }): Promise<SavedSnippet>;
  /** Project scope only: hides or shows an inherited snippet. */
  setHidden?(id: string, hidden: boolean): Promise<SavedSnippet>;
  /** Project scope only: shows the named hidden snippets again. */
  restore?(ids: string[]): Promise<void>;
}

/** What a person calls each place a snippet can be saved. */
export const SNIPPET_LEVEL_LABEL: Record<SnippetLevel, string> = { project: "This project", organization: "The organisation" };

/** The URL prefix of a scope's saved snippets. */
export function reportSnippetsBase(scope: LayoutScope): string {
  return `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-snippets`;
}

/** The live implementation of {@link ReportSnippetStoreApi} for an organisation or a project. */
export function reportSnippetStoreApi(scope: LayoutScope): ReportSnippetStoreApi {
  const base = reportSnippetsBase(scope);
  const store: ReportSnippetStoreApi = {
    scope,
    list: () => api.get<SavedSnippet[]>(base),
    check: (tree, selection, level) =>
      api.post<SnippetCheck>(`${base}${level === "organization" && scope.kind === "project" ? "/check-organization" : "/check"}`, { tree, selection }),
    save: (body, level) => api.post<SavedSnippet>(`${base}${level === "organization" && scope.kind === "project" ? "/organization" : ""}`, body),
    get: (id) => api.get<SavedSnippetDetail>(`${base}/${id}`),
    update: (id, body) => api.patch<SavedSnippet>(`${base}/${id}`, body),
    remove: (id) => api.delete<void>(`${base}/${id}`),
    copy: (id, body) => api.post<SavedSnippet>(`${base}/${id}/copy`, body),
  };
  if (scope.kind === "project") {
    store.setHidden = (id, hidden) => api.put<SavedSnippet>(`${base}/${id}/visibility`, { hidden });
    store.restore = async (ids) => {
      await api.post(`${base}/restore`, { snippet_ids: ids });
    };
  }
  return store;
}
