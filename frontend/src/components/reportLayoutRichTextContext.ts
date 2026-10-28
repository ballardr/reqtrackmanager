/**
 * Module: components/reportLayoutRichTextContext
 *
 * What the rich-text editor's node views share with the editor that hosts them: the catalogues the settings forms
 * need, the server's problems, and the calls that read and change the whole tree.
 *
 * Responsibilities: carry the values (a React context), and nothing else, so a node view can reach them without
 * the editor having to thread props through ProseMirror.
 */
import { createContext, useContext } from "react";

import type { BlockType, TreeProblem } from "../api/reportLayouts";
import type { Tree } from "../utils/reportLayoutTree";
import type { OutlineEnv } from "./ReportLayoutOutlineField";

/** The shared values of one rich-text editor. */
export interface RichTextContextValue {
  env: OutlineEnv;
  types: BlockType[];
  problems: TreeProblem[];
  readOnly: boolean;
  /** The tree as the editor's document stands now. */
  currentTree: () => Tree;
  /** Replaces the whole document with the one for `tree` (a structural edit: move, add, delete). */
  applyTree: (tree: Tree) => void;
}

export const RichTextContext = createContext<RichTextContextValue | null>(null);

/** The editor's shared values; a node view is only ever drawn inside an editor, so a missing one is a bug. */
export function useRichText(): RichTextContextValue {
  const value = useContext(RichTextContext);
  if (value === null) throw new Error("A rich-text node view was drawn outside its editor.");
  return value;
}
