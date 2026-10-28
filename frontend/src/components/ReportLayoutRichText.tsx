/**
 * Module: components/ReportLayoutRichText
 *
 * The document view of a layout: the layout's blocks as an editable document, so headings and text are typed in
 * place and every other block is a framed card with the same controls and settings forms as the outline.
 *
 * Responsibilities:
 * - Show a document layout as a TipTap editor whose content is `treeToDoc(tree)`, and report every edit as the
 *   tree `docToTree` makes of it (`onChange`), so the designer holds one tree whichever view is open.
 * - Refuse, with the reason, a tree the document cannot show without changing it.
 * - Offer **Add block** at the top level; the nested lists have their own, and the structural buttons on each
 *   block apply the same tree edits as the outline and then redraw the document.
 * - Show the server's problems on the block they belong to, and layout-level ones with the settings.
 *
 * Design decisions: the editor never holds a copy of the layout the designer does not: when the tree changes from
 * outside it redraws, when the change is its own echo it does nothing. A table layout has no document, so it gets
 * a note, not an editor.
 */
import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useRef, useState } from "react";

import type { BlockCatalogue, LayoutFamily, ReportFieldCatalogue, ReportWidget, TreeProblem } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { docToTree, NotRepresentableError, treeToDoc, type DocNode } from "../utils/reportLayoutDoc";
import { cloneNode, insertNode, listAt, stableJson, type Tree } from "../utils/reportLayoutTree";
import { MenuButton } from "./MenuButton";
import type { OutlineEnv } from "./ReportLayoutOutlineField";
import { layoutExtensions } from "./reportLayoutRichTextExtensions";
import { RichTextContext, type RichTextContextValue } from "./reportLayoutRichTextContext";
import { ReportLayoutRichTextToolbar } from "./ReportLayoutRichTextToolbar";
import { ReportLayoutSettings } from "./ReportLayoutSettings";

interface Shared {
  tree: Tree;
  onChange: (next: Tree) => void;
  blocks: BlockCatalogue;
  catalogue: ReportFieldCatalogue;
  widgets: ReportWidget[];
  problems: TreeProblem[];
  readOnly: boolean;
}

function Editor({ tree, onChange, blocks, catalogue, widgets, problems, readOnly }: Shared) {
  const text = useStrings().reportOutline;
  const types = blocks.blocks;
  const latest = useRef({ tree, onChange });
  useEffect(() => {
    latest.current = { tree, onChange };
  });

  // The document is read from the tree once, here; later tree changes from outside are applied by the effect below.
  const [initial] = useState(() => treeToDoc(tree, types));

  const editor = useEditor({
    extensions: layoutExtensions,
    content: initial,
    editable: !readOnly,
    onUpdate: ({ editor: updated }) => {
      latest.current.onChange(docToTree(updated.getJSON() as DocNode, latest.current.tree));
    },
  });

  useEffect(() => {
    editor?.setEditable(!readOnly);
  }, [editor, readOnly]);

  // A tree that changed somewhere else (not this editor's own echo) redraws the document.
  useEffect(() => {
    if (!editor) return;
    const shown = docToTree(editor.getJSON() as DocNode, tree);
    if (stableJson(shown) !== stableJson(tree)) editor.commands.setContent(treeToDoc(tree, types), { emitUpdate: false });
  }, [editor, tree, types]);

  const env: OutlineEnv = {
    blocks, catalogue, widgets, readOnly,
    variables: Array.isArray(tree.variables) ? (tree.variables as { name?: string }[]).map((v) => String(v.name ?? "")).filter(Boolean) : [],
  };
  const shared: RichTextContextValue = {
    env, types, problems, readOnly,
    currentTree: () => docToTree((editor?.getJSON() ?? initial) as DocNode, latest.current.tree),
    applyTree: (next) => { editor?.commands.setContent(treeToDoc(next, types), { emitUpdate: true }); },
  };

  return (
    <RichTextContext.Provider value={shared}>
      <div className="stack" role="region" aria-label={text.documentLabel}>
        <ReportLayoutSettings tree={tree} onChange={onChange} family="document" blocks={blocks} env={env} problems={problems} />
        {!readOnly && (
          <div>
            <MenuButton
              label={text.addBlock} menuLabel={text.addBlock}
              items={types.filter((t) => t.families.includes("document")).map((t) => ({
                key: t.type, label: t.label,
                onSelect: () => shared.applyTree(insertNode(shared.currentTree(), ["nodes"], listAt(shared.currentTree(), ["nodes"]).length, cloneNode(t.template))),
              }))}
            />
          </div>
        )}
        {editor && <ReportLayoutRichTextToolbar editor={editor} disabled={readOnly} />}
        <EditorContent editor={editor} className="rich-editor" aria-label={text.documentLabel} />
      </div>
    </RichTextContext.Provider>
  );
}

/**
 * @param tree The layout tree.
 * @param onChange Called with the tree for every edit made in the document.
 * @param family The layout's family; a table layout has no document.
 * @param blocks The block catalogue.
 * @param catalogue The record types and fields.
 * @param widgets The report components a widget block can embed.
 * @param problems The server's problems for the tree.
 * @param readOnly A layout shared from elsewhere: shown, not editable.
 */
export function ReportLayoutRichText({
  tree, onChange, family, blocks, catalogue, widgets, problems, readOnly = false,
}: Omit<Shared, "readOnly"> & { family: LayoutFamily; readOnly?: boolean }) {
  const text = useStrings().reportOutline;
  if (family !== "document") return <p className="text-muted" role="note">{text.richTableOnly}</p>;
  try {
    treeToDoc(tree, blocks.blocks);
  } catch (err) {
    if (err instanceof NotRepresentableError) {
      return <p role="alert" style={{ color: "var(--color-danger)" }}>{text.richNotShown(`${err.path}: ${err.message}`)}</p>;
    }
    throw err;
  }
  return <Editor tree={tree} onChange={onChange} blocks={blocks} catalogue={catalogue} widgets={widgets} problems={problems} readOnly={readOnly} />;
}
