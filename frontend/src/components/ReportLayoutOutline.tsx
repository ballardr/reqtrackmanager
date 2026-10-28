/**
 * Module: components/ReportLayoutOutline
 *
 * The block outline: a layout as nested cards, one per block, each with a form drawn from the block type's
 * schema (`BlockType.fields`), controls to add, move, indent, outdent, duplicate and delete it, and the server's
 * problems shown on the card and the field they belong to.
 *
 * Responsibilities:
 * - Edit the layout tree in place through `onChange`; the tree is the designer's, this component holds no copy.
 * - Offer the layout-level settings (page orientation, variables) above the blocks.
 * - Keep keyboard focus on the control the author just used after a block moves.
 * - Work for any block type: the form comes from the schema, child lists from `containers`, and the names a
 *   block brings into scope from `provides`, so a module's block type needs no code here.
 *
 * Design decisions: moves are buttons (up, down, into the block above, out of this block), which are keyboard
 * and screen-reader friendly and need no drag-and-drop dependency. A block of an unknown or undescribed type is
 * shown as JSON rather than hidden, so a tree is never uneditable. Validity is the server's: this component only
 * displays the problems it is given.
 */
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Copy, IndentDecrease, IndentIncrease, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactElement } from "react";

import type { BlockCatalogue, BlockType, LayoutFamily, ReportFieldCatalogue, ReportWidget, TreeProblem } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import {
  cloneNode, duplicateNode, formatPath, indentNode, indentTarget, insertNode, listAt, moveNode, namesInScope, outdentNode,
  parentAddr, problemsForNode, removeNode, setAt, summarise, type NodeAddr, type Seg, type Tree, type TreeNode,
} from "../utils/reportLayoutTree";
import { Badge } from "./Badge";
import { MenuButton } from "./MenuButton";
import { ReportLayoutJsonField } from "./ReportLayoutJsonField";
import { ReportLayoutOutlineField, type OutlineEnv } from "./ReportLayoutOutlineField";
import { ReportLayoutSettings } from "./ReportLayoutSettings";

/** A control the author used on a block, to put focus back on it once the block has moved. */
interface FocusTarget {
  path: string;
  action: string;
}

/** The control to fall back to when the one just used is disabled at its new place. */
const OPPOSITE: Record<string, string> = { up: "down", down: "up", indent: "outdent", outdent: "indent" };

/**
 * @param tree The layout tree.
 * @param onChange Called with the edited tree.
 * @param family The layout's family; only block types for it can be added.
 * @param blocks The block catalogue.
 * @param catalogue The record types and fields.
 * @param widgets The report components a widget block can embed.
 * @param problems The server's problems for the tree.
 * @param readOnly A layout shared from elsewhere: shown, not editable.
 */
export function ReportLayoutOutline({
  tree, onChange, family, blocks, catalogue, widgets, problems, readOnly = false,
}: {
  tree: Tree;
  onChange: (next: Tree) => void;
  family: LayoutFamily;
  blocks: BlockCatalogue;
  catalogue: ReportFieldCatalogue;
  widgets: ReportWidget[];
  problems: TreeProblem[];
  readOnly?: boolean;
}) {
  const text = useStrings().reportOutline;
  const root = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState<FocusTarget | null>(null);

  const declared = Array.isArray(tree.variables) ? (tree.variables as { name?: string }[]).map((v) => String(v.name ?? "")).filter(Boolean) : [];
  const env: OutlineEnv = { blocks, catalogue, widgets, variables: declared, readOnly };
  const types = blocks.blocks;

  // After a move the card is a different element: put focus on the same control of the block's new place.
  useEffect(() => {
    if (!focus) return;
    const head = root.current?.querySelector(`[data-path="${focus.path}"] > .outline-block-head`);
    const control = (action: string) => head?.querySelector<HTMLButtonElement>(`[data-action="${action}"]`);
    // A control that is now disabled (the block reached the end of its list) hands focus to its opposite.
    const order = [focus.action, OPPOSITE[focus.action], "duplicate"];
    order.map((action) => (action ? control(action) : null)).find((button) => button && !button.disabled)?.focus();
  }, [focus]);


  function toggle(path: string) {
    setCollapsed((open) => {
      const next = new Set(open);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  function moved(result: { tree: Tree; addr: NodeAddr } | null, action: string) {
    if (!result) return;
    onChange(result.tree);
    setFocus({ path: formatPath(result.addr), action });
  }

  function addTo(list: Seg[], type: BlockType) {
    onChange(insertNode(tree, list, listAt(tree, list).length, cloneNode(type.template)));
  }

  function renderList(list: Seg[], label: string) {
    const nodes = listAt(tree, list);
    const addable = types.filter((t) => t.families.includes(family));
    return (
      <div className="stack" style={{ gap: "var(--space-3)" }}>
        {nodes.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{list.length === 1 ? text.noBlocks : text.emptyContainer}</p>}
        {nodes.length > 0 && (
          <ol className="outline-list" aria-label={label}>
            {nodes.map((node, index) => renderBlock(node, [...list, index], index, nodes.length))}
          </ol>
        )}
        {!readOnly && (
          <div>
            <MenuButton
              label={list.length === 1 ? text.addBlock : text.addInside(label)}
              menuLabel={list.length === 1 ? text.addBlock : text.addInside(label)}
              items={addable.map((t) => ({ key: t.type, label: t.label, onSelect: () => addTo(list, t) }))}
            />
          </div>
        )}
      </div>
    );
  }

  function renderBlock(node: TreeNode, addr: NodeAddr, index: number, count: number) {
    const path = formatPath(addr);
    const type = types.find((t) => t.type === node.type);
    const found = problemsForNode(problems, path);
    const open = !collapsed.has(path);
    const names = namesInScope(tree, addr, types);
    const label = type?.label ?? String(node.type ?? "?");
    const summary = summarise(node);
    const canIndent = indentTarget(tree, addr, types) !== null;
    const canOutdent = parentAddr(addr) !== null;
    const containerKeys = new Set(type?.containers.map((c) => c.key) ?? []);
    const fieldKeys = new Set(type?.fields.map((f) => f.key) ?? []);
    // Problems about a key the form does not draw (a typo in JSON, a container's own limit) are listed on the block.
    const stray = [...found.byKey.entries()].filter(([key]) => !fieldKeys.has(key) && !containerKeys.has(key)).flatMap(([, msgs]) => msgs);

    const action = (key: string, name: string, icon: ReactElement, run: () => void, disabled = false) => (
      <button type="button" className="btn btn-sm btn-icon" data-action={key} aria-label={name} title={name} disabled={disabled} onClick={run}>
        {icon}
      </button>
    );

    return (
      <li key={path} className="outline-block" data-path={path} data-invalid={found.total > 0} aria-label={text.blockCard(label, index + 1)}>
        <div className="row outline-block-head" style={{ gap: "var(--space-2)", flexWrap: "wrap", justifyContent: "space-between" }}>
          <button
            type="button" className="btn btn-sm btn-icon" aria-expanded={open} aria-label={`${open ? text.collapse : text.expand}: ${label} ${index + 1}`}
            onClick={() => toggle(path)}
          >
            {open ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
          </button>
          <span style={{ flex: 1, minWidth: 0 }}>
            <strong>{label}</strong>
            {summary && <span className="text-muted"> {summary}</span>}
          </span>
          {found.total > 0 && <Badge tone="danger">{text.problemCount(found.total)}</Badge>}
          {!readOnly && (
            <span className="row" role="toolbar" aria-label={`${label} ${index + 1}`} style={{ gap: "var(--space-1)" }}>
              {action("up", text.moveUp, <ArrowUp aria-hidden="true" />, () => moved(moveNode(tree, addr, -1), "up"), index === 0)}
              {action("down", text.moveDown, <ArrowDown aria-hidden="true" />, () => moved(moveNode(tree, addr, 1), "down"), index === count - 1)}
              {action("indent", text.indent, <IndentIncrease aria-hidden="true" />, () => moved(indentNode(tree, addr, types), "indent"), !canIndent)}
              {action("outdent", text.outdent, <IndentDecrease aria-hidden="true" />, () => moved(outdentNode(tree, addr), "outdent"), !canOutdent)}
              {action("duplicate", text.duplicate, <Copy aria-hidden="true" />, () => moved(duplicateNode(tree, addr), "duplicate"))}
              {action("remove", text.remove, <Trash2 aria-hidden="true" />, () => onChange(removeNode(tree, addr)))}
            </span>
          )}
        </div>
        {open && (
          <div className="stack outline-block-body">
            {(found.own.length > 0 || stray.length > 0) && (
              <ul className="outline-field-problems" role="alert">
                {[...found.own, ...stray].map((message, i) => <li key={i}>{message}</li>)}
              </ul>
            )}
            {type && type.described ? (
              type.fields.map((field) => (
                <ReportLayoutOutlineField
                  key={field.key} field={field} node={node} names={names} env={env} problems={found.byKey.get(field.key) ?? []}
                  onChange={(key, value) => onChange(setAt(tree, [...addr, key], value))}
                />
              ))
            ) : (
              <ReportLayoutJsonField
                label={type ? text.unknownBlock(type.type) : text.unknownBlock(String(node.type ?? "?"))} value={node} disabled={readOnly}
                onChange={(next) => {
                  if (next !== null && typeof next === "object" && !Array.isArray(next)) onChange(setAt(tree, addr, next));
                }}
              />
            )}
            {type?.containers.map((container) => (
              <div key={container.key} className="stack outline-container" role="group" aria-label={`${container.label}: ${label} ${index + 1}`}>
                <strong>{container.label}</strong>
                {(found.byKey.get(container.key) ?? []).length > 0 && (
                  <ul className="outline-field-problems" role="alert">
                    {(found.byKey.get(container.key) ?? []).map((message, i) => <li key={i}>{message}</li>)}
                  </ul>
                )}
                {renderList([...addr, container.key], `${container.label}: ${label} ${index + 1}`)}
              </div>
            ))}
          </div>
        )}
      </li>
    );
  }

  return (
    <div className="stack" ref={root} role="region" aria-label={text.outlineLabel}>
      <ReportLayoutSettings tree={tree} onChange={onChange} family={family} blocks={blocks} env={env} problems={problems} />
      {renderList(["nodes"], text.outlineLabel)}
    </div>
  );
}
