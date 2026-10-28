/**
 * Module: components/ReportLayoutRichTextViews
 *
 * The drawing of the rich-text editor's blocks: a React node view for each editor node (heading, text, raw text,
 * whole-node block, container, slot), each framed with the same controls and settings forms as the block outline.
 *
 * Responsibilities:
 * - Draw a block's frame: its name, a summary, the server's problems for it, move / indent / outdent / duplicate /
 *   delete buttons, and a settings area using `ReportLayoutOutlineField` for every key that is not prose.
 * - Make structural edits (move, indent, add) through the tree helpers and replace the document, so the editor and
 *   the outline apply one set of rules; prose edits are made in place by the editor.
 *
 * Design decisions: prose (heading text, paragraphs, bullet items) is the editor's own content; everything else is
 * data in node attributes edited with the shared forms, so a block type needs no node of its own. Node views read
 * the shared values from `RichTextContext` and compute their place in the tree when they act, because a sibling
 * moving does not re-draw them.
 */
import { NodeViewContent, NodeViewWrapper, type NodeViewProps } from "@tiptap/react";
import { ArrowDown, ArrowUp, Copy, IndentDecrease, IndentIncrease, Settings, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { BlockType } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { addrAt } from "../utils/reportLayoutDoc";
import {
  cloneNode, duplicateNode, formatPath, indentNode, indentTarget, insertNode, listAt, moveNode, namesInScope, outdentNode, parentAddr,
  problemsForNode, removeNode, summarise, type NodeAddr, type Tree, type TreeNode,
} from "../utils/reportLayoutTree";
import { Badge } from "./Badge";
import { TextAreaField } from "./FormFields";
import { MenuButton } from "./MenuButton";
import { ReportLayoutOutlineField } from "./ReportLayoutOutlineField";
import { useRichText } from "./reportLayoutRichTextContext";

type Props = Record<string, unknown>;

// ---- the frame every block shares ---------------------------------------------------------------------------------

/**
 * The block's frame.
 *
 * @param view The node view's props.
 * @param type The block's tree type (`heading`, `each`, …).
 * @param node The block as the settings forms see it (its non-prose keys).
 * @param onNode Stores the block's edited keys back into the editor node.
 * @param excluded Keys drawn by the editor itself, not in the settings (`text`).
 * @param children The block's body (its prose, or its slots).
 */
function BlockFrame({
  view, type, node, onNode, excluded, children,
}: { view: NodeViewProps; type: string; node: TreeNode; onNode: (next: TreeNode) => void; excluded: string[]; children?: ReactNode }) {
  const text = useStrings().reportOutline;
  const ctx = useRichText();
  const [open, setOpen] = useState(false);
  const spec = ctx.types.find((t) => t.type === type);
  const label = spec?.label ?? type;
  const pos = view.getPos();
  const addr: NodeAddr = typeof pos === "number" ? addrAt(view.editor.state.doc, pos) : [];
  const found = problemsForNode(ctx.problems, formatPath(addr));
  const fields = (spec?.fields ?? []).filter((f) => !excluded.includes(f.key));
  const messages = [...found.own, ...[...found.byKey.values()].flat()];

  /** Runs a tree edit for this block and redraws the document from the result. */
  function edit(change: (tree: Tree, here: NodeAddr, types: BlockType[]) => { tree: Tree } | null) {
    const here = addrAt(view.editor.state.doc, view.getPos() ?? 0);
    const result = change(ctx.currentTree(), here, ctx.types);
    if (result) ctx.applyTree(result.tree);
  }

  const here = addr;
  const tree = ctx.readOnly ? null : ctx.currentTree();
  const canIndent = tree !== null && here.length > 0 && indentTarget(tree, here, ctx.types) !== null;
  const names = tree !== null && open ? namesInScope(tree, here, ctx.types) : [];
  const button = (name: string, icon: ReactNode, run: () => void, disabled = false) => (
    <button type="button" className="btn btn-sm btn-icon" aria-label={name} title={name} disabled={disabled} onClick={run}>{icon}</button>
  );

  return (
    <NodeViewWrapper className="rich-block" data-invalid={found.total > 0} data-block-type={type}>
      <div className="row rich-block-head" contentEditable={false} style={{ gap: "var(--space-2)", flexWrap: "wrap", justifyContent: "space-between" }}>
        <span style={{ flex: 1, minWidth: 0 }}>
          <strong>{label}</strong>
          {type !== "heading" && type !== "text" && summarise(node) && <span className="text-muted"> {summarise(node)}</span>}
        </span>
        {found.total > 0 && <Badge tone="danger">{text.problemCount(found.total)}</Badge>}
        {!ctx.readOnly && (
          <span className="row" role="toolbar" aria-label={label} style={{ gap: "var(--space-1)" }}>
            {fields.length > 0 && (
              <button
                type="button" className="btn btn-sm btn-icon" aria-expanded={open} aria-label={open ? text.richSettingsHide : text.richSettingsFor(label)}
                title={open ? text.richSettingsHide : text.richSettingsFor(label)} onClick={() => setOpen(!open)}
              >
                <Settings aria-hidden="true" />
              </button>
            )}
            {button(text.moveUp, <ArrowUp aria-hidden="true" />, () => edit((t, a) => moveNode(t, a, -1)))}
            {button(text.moveDown, <ArrowDown aria-hidden="true" />, () => edit((t, a) => moveNode(t, a, 1)))}
            {button(text.indent, <IndentIncrease aria-hidden="true" />, () => edit((t, a, types) => indentNode(t, a, types)), !canIndent)}
            {button(text.outdent, <IndentDecrease aria-hidden="true" />, () => edit((t, a) => outdentNode(t, a)), parentAddr(here) === null)}
            {button(text.duplicate, <Copy aria-hidden="true" />, () => edit((t, a) => duplicateNode(t, a)))}
            {button(text.remove, <Trash2 aria-hidden="true" />, () => edit((t, a) => ({ tree: removeNode(t, a) })))}
          </span>
        )}
      </div>
      {messages.length > 0 && (
        <ul className="outline-field-problems" role="alert" contentEditable={false}>
          {messages.map((message, i) => <li key={i}>{message}</li>)}
        </ul>
      )}
      {open && !ctx.readOnly && (
        <div className="stack rich-block-settings" contentEditable={false}>
          {fields.map((field) => (
            <ReportLayoutOutlineField
              key={field.key} field={field} node={node} names={names} env={ctx.env} problems={found.byKey.get(field.key) ?? []}
              onChange={(key, value) => {
                const next = { ...node, [key]: value };
                if (value === undefined) delete next[key];
                onNode(next);
              }}
            />
          ))}
        </div>
      )}
      {children}
    </NodeViewWrapper>
  );
}

/** A block's non-prose keys as the forms see them: its type plus its stored props. */
const withType = (type: string, props: unknown): TreeNode => ({ type, ...(props as Props) });
/** The keys of a node other than its type. */
const propsOf = (node: TreeNode): Props => {
  const { type: _type, ...rest } = node;
  void _type;
  return rest;
};

// ---- node views ---------------------------------------------------------------------------------------------------

export function HeadingView(view: NodeViewProps) {
  const level = Number((view.node.attrs.props as Props).level ?? 1);
  return (
    <BlockFrame
      view={view} type="heading" node={withType("heading", view.node.attrs.props)} excluded={["text"]}
      onNode={(next) => view.updateAttributes({ props: propsOf(next) })}
    >
      <NodeViewContent className={`rich-heading rich-heading-${Math.min(Math.max(level, 1), 4)}`} />
    </BlockFrame>
  );
}

export function TextView(view: NodeViewProps) {
  return (
    <BlockFrame
      view={view} type="text" node={withType("text", view.node.attrs.props)} excluded={["text"]}
      onNode={(next) => view.updateAttributes({ props: propsOf(next) })}
    >
      <NodeViewContent className="rich-prose" />
    </BlockFrame>
  );
}

export function RawTextView(view: NodeViewProps) {
  const text = useStrings().reportOutline;
  const ctx = useRichText();
  return (
    <BlockFrame
      view={view} type="text" node={withType("text", view.node.attrs.props)} excluded={["text"]}
      onNode={(next) => view.updateAttributes({ props: propsOf(next) })}
    >
      <div contentEditable={false}>
        <TextAreaField helpNotNeeded
          label={text.richRawText} hint={text.richRawHint} rows={4} disabled={ctx.readOnly}
          value={String(view.node.attrs.markdown ?? "")} onChange={(markdown) => view.updateAttributes({ markdown })}
          inputProps={{ spellCheck: false }}
        />
      </div>
    </BlockFrame>
  );
}

export function LeafView(view: NodeViewProps) {
  const node = view.node.attrs.node as TreeNode;
  return <BlockFrame view={view} type={String(node.type)} node={node} excluded={[]} onNode={(next) => view.updateAttributes({ node: next })} />;
}

export function ContainerView(view: NodeViewProps) {
  const type = String(view.node.attrs.type);
  return (
    <BlockFrame
      view={view} type={type} node={withType(type, view.node.attrs.props)} excluded={[]}
      onNode={(next) => view.updateAttributes({ props: propsOf(next) })}
    >
      <NodeViewContent className="stack rich-slots" />
    </BlockFrame>
  );
}

export function SlotView(view: NodeViewProps) {
  const text = useStrings().reportOutline;
  const ctx = useRichText();
  const key = String(view.node.attrs.key);
  const pos = view.getPos();
  const owner = typeof pos === "number" ? ctx.types.find((t) => t.type === view.editor.state.doc.resolve(pos).parent.attrs.type) : undefined;
  const label = owner?.containers.find((c) => c.key === key)?.label ?? key;
  const addable = ctx.types.filter((t) => t.families.includes("document"));

  function add(type: BlockType) {
    const here = addrAt(view.editor.state.doc, view.getPos() ?? 0);
    const tree = ctx.currentTree();
    const list = [...here, key];
    ctx.applyTree(insertNode(tree, list, listAt(tree, list).length, cloneNode(type.template)));
  }

  return (
    <NodeViewWrapper className="rich-slot" role="group" aria-label={text.richContentLabel(label)}>
      <strong contentEditable={false}>{label}</strong>
      <NodeViewContent className="stack" />
      {!ctx.readOnly && (
        <div contentEditable={false}>
          <MenuButton
            label={text.addInside(label)} menuLabel={text.addInside(label)}
            items={addable.map((t) => ({ key: t.type, label: t.label, onSelect: () => add(t) }))}
          />
        </div>
      )}
    </NodeViewWrapper>
  );
}

