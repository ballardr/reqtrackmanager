/**
 * Module: testing/reportFolderFixtures
 *
 * Storybook-only fake `ReportFolderApi` that keeps the folders a story adds, renames and deletes, answering as the
 * server does for one scope (a duplicate is refused, a rename keeps the parent, a delete drops the folder and the
 * folders inside it are re-rooted one level up).
 */
import { fn, screen, userEvent, within } from "storybook/test";

import type { ReportFolder, ReportFolderApi, ReportFolderChange } from "../api/reportFolders";
import { followFolder, isInsideFolder, parentFolder, tidyFolder } from "../utils/reportFolders";

/** Folders a story starts from: two the scope owns (one nested) and one it inherits. */
export function buildFolders(): ReportFolder[] {
  return [
    { path: "Handover", own: true },
    { path: "Handover/Quarterly", own: true },
    { path: "Shared", own: false },
  ];
}

/**
 * @param initial The folders to start from.
 * @param kind Which tier the fake is bound to.
 * @param moved How many filed items a rename or delete reports moving (the fake files nothing itself).
 */
export function buildFolderApi(
  initial: ReportFolder[] = buildFolders(), kind: "project" | "organization" = "organization", moved = 0,
): ReportFolderApi {
  let store = initial.map((folder) => ({ ...folder }));
  const sorted = () => [...store].sort((a, b) => a.path.localeCompare(b.path)).map((folder) => ({ ...folder }));
  const find = (path: string) => store.find((folder) => folder.path.toLowerCase() === path.toLowerCase());
  const change = (path: string | null): ReportFolderChange => ({ folders: sorted(), path, layouts: moved, packs: 0, placements: 0 });
  return {
    scope: { kind, id: kind === "project" ? "project-1" : "org-1" },
    list: fn(async () => sorted()),
    add: fn(async (path: string) => {
      const tidy = tidyFolder(path);
      if (find(tidy)) throw new Error("A folder with that name already exists here.");
      store = [...store, { path: tidy, own: true }];
      return sorted();
    }),
    rename: fn(async (path: string, name: string) => {
      const folder = find(path);
      if (!folder?.own) throw new Error("That folder is not one this scope can change.");
      const next = tidyFolder([parentFolder(folder.path), name].filter(Boolean).join("/"));
      if (next.toLowerCase() !== folder.path.toLowerCase() && find(next)) throw new Error("A folder with that name already exists here.");
      const from = folder.path;
      store = store.map((f) => (isInsideFolder(f.path, from) ? { ...f, path: followFolder(f.path, from, next) } : f));
      return change(next);
    }),
    remove: fn(async (path: string) => {
      const folder = find(path);
      if (!folder?.own) throw new Error("That folder is not one this scope can change.");
      const from = folder.path;
      store = store
        .filter((f) => f.path.toLowerCase() !== from.toLowerCase())
        .map((f) => (isInsideFolder(f.path, from) ? { ...f, path: followFolder(f.path, from, parentFolder(from)) } : f));
      return change(null);
    }),
  };
}

/**
 * Presses a form's Folder field and returns the popover that holds the chooser (it is portalled to the body, so it is
 * found on `screen`, not inside the dialog).
 *
 * @param dialog The dialog the Folder field sits in.
 * @param shown What the field currently shows: "No folder" or the folder path.
 */
export async function openFolderPopover(dialog: ReturnType<typeof within>, shown = "No folder") {
  await userEvent.click(await dialog.findByRole("button", { name: `Folder: ${shown}` }));
  return within(await screen.findByRole("dialog", { name: "Move to a folder" }));
}
