/**
 * Module: components/ReportLayoutBlocks
 *
 * The block editor: a layout drawn as blocks on a Blockly workspace, with the selected block's full form (every
 * field, including source, columns, condition, widget settings and long text) in an inspector beside it. It is the
 * designer's second view of the layout tree. The canvas takes the page's width; the inspector sits beside it when
 * there is room and under it when there is not.
 *
 * Responsibilities:
 * - Draw the tree as blocks and write every edit back to the tree through `onChange`; the tree is the designer's,
 *   this component holds no second model (`utils/reportLayoutBlockly` does the conversion without losing a key).
 * - Generate the block types and the Add block list from the server's block schemas, so a module's block type needs
 *   no code here; show the server's problems as warnings on the blocks and in the inspector.
 * - Keep the inspector's edits and the workspace in step: an edit that changes only values is patched into the
 *   blocks in place (selection and scroll stay), a change in shape rebuilds the workspace.
 * - Add blocks from one dropdown ("Add block") at a place it names: after the selected block, inside it, or at the
 *   end of the layout. The block is created in the workspace itself, so Ctrl+Z undoes the addition like a drag.
 * - Save the selected block, with everything inside it, as a snippet ("Save as snippet"; the designer owns the dialog).
 * - Insert a snippet at the same place, or at the start of the layout ("Insert snippet", `ReportSnippetPicker`): the server returns the new tree; its
 *   root-level changes (page styles, variables) are taken as they are and its blocks are created in the workspace in one
 *   undo group, so Ctrl+Z removes them together.
 * - Follow the app's light and dark themes.
 *
 * Design decisions: there is no Blockly toolbox (flyout palette): it took a column of the canvas and listed the least
 * used blocks first; the dropdown is the one way to add and says where the block will land. Blockly is loaded lazily by the designer (`React.lazy`), keeping its ~1 MB out of the main
 * bundle. Blocks carry short fields inline as a quick edit; the inspector holds every field with the shared field
 * editors, reused as they are, because embedding React inside SVG blocks would give two editing worlds, and a plain
 * form is the route for people who do not use a pointer. A block
 * dropped outside the layout is not part of it and is counted, not silently dropped. Validity is the server's.
 */
import * as Blockly from "blockly/core";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type {
  BlockCatalogue, BlockType, LayoutFamily, ReportFieldCatalogue, ReportImageLibrary, ReportLayoutApi, ReportSnippet, ReportWidget, SnippetApplyResult,
  TreeProblem,
} from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import {
  ROOT_INPUT, ROOT_TYPE, SUMMARY_FIELD, blockSummary, chainToNodes, controlValue, inlineFields, layoutType, looseBlockCount,
  nodeData, nodeToBlockState, paletteEntries, shapeOf, treeToWorkspaceState, workspaceStateToTree, type BlockState,
} from "../utils/reportLayoutBlockly";
import { buildTheme, registerBlocks } from "../utils/reportLayoutBlocklyBlocks";
import {
  cloneNode, formatPath, listAt, namesInScope, nodeAt, parsePath, problemsForNode, setAt, stableJson, summarise, type Seg, type Tree, type TreeNode,
} from "../utils/reportLayoutTree";
import type { SnippetSelection } from "../api/reportSnippets";
import { insertedBlocks, withBlocksOf } from "../utils/reportSnippets";
import { selectionOfBlock } from "../utils/reportSnippetSelection";
import { MenuButton } from "./MenuButton";
import { ReportLayoutJsonField } from "./ReportLayoutJsonField";
import { ReportLayoutBlockField, type BlockEnv } from "./ReportLayoutBlockField";
import { ReportLayoutSettings } from "./ReportLayoutSettings";
import { ReportSnippetPicker, type SnippetPlace } from "./ReportSnippetPicker";
import type { SnippetNoticeData } from "./ReportSnippetNotice";

/** Maps each block of the workspace to its tree path (`nodes[1].children[0]`). */
function indexPaths(ws: Blockly.WorkspaceSvg): Map<string, string> {
  const paths = new Map<string, string>();
  const walk = (first: Blockly.Block | null, list: string) => {
    let index = 0;
    for (let block = first; block; block = block.getNextBlock(), index += 1) {
      const path = `${list}[${index}]`;
      paths.set(block.id, path);
      for (const input of block.inputList) {
        if (input.type === Blockly.inputs.inputTypes.STATEMENT && input.connection) walk(input.connection.targetBlock(), `${path}.${input.name}`);
      }
    }
  };
  const root = ws.getTopBlocks(false).find((b) => b.type === ROOT_TYPE);
  if (root) walk(root.getInputTargetBlock(ROOT_INPUT), ROOT_INPUT);
  return paths;
}

/** The layout's blocks in the workspace as nodes (what a save of the workspace would write), for comparing shapes. */
function workspaceNodes(ws: Blockly.WorkspaceSvg, types: BlockType[]): TreeNode[] {
  const state = Blockly.serialization.workspaces.save(ws) as { blocks?: { blocks?: BlockState[] } };
  const root = state.blocks?.blocks?.find((b) => b.type === ROOT_TYPE);
  return chainToNodes(root?.inputs?.[ROOT_INPUT]?.block, types);
}

/** What an inline control holds when its key is not set. */
function emptyControl(kind: string): string | boolean {
  return kind === "boolean" ? false : "";
}

/**
 * Writes `nodes` into the blocks of `first`'s chain, in place: each block's data and inline fields. The shapes must
 * match (checked by the caller).
 */
function patchChain(first: Blockly.Block | null, nodes: unknown, types: BlockType[]): void {
  if (!Array.isArray(nodes)) return;
  let next = first;
  for (const raw of nodes) {
    const block = next;
    if (!block) return;
    next = block.getNextBlock();
    const node = raw as TreeNode;
    const type = types.find((t) => t.type === layoutType(block.type));
    block.data = nodeData(node, types);
    for (const field of type ? inlineFields(type) : []) {
      const want = controlValue(field, node) ?? emptyControl(field.kind);
      if (block.getFieldValue(field.key) !== want && !(field.kind === "boolean" && block.getFieldValue(field.key) === (want ? "TRUE" : "FALSE"))) {
        block.setFieldValue(want, field.key);
      }
    }
    const summary = blockSummary(node, type);
    if (summary !== undefined && block.getFieldValue(SUMMARY_FIELD) !== summary) block.setFieldValue(summary, SUMMARY_FIELD);
    for (const container of type?.containers ?? []) patchChain(block.getInputTargetBlock(container.key), node[container.key], types);
  }
}

/** Where Add block would put a block: a child list of the tree, the index in it and the words that say so. */
interface AddTarget {
  list: Seg[];
  index: number;
  label: string;
}

/** Names a block for the "Adding after: …" line: its type and the start of its text ("Heading – Requirements"). */
function describeBlock(node: TreeNode, type: BlockType | undefined): string {
  const label = type?.label ?? String(node.type ?? "?");
  const start = summarise(node, 30);
  return start === "" ? label : `${label} – ${start}`;
}

/**
 * @param tree The layout tree.
 * @param onChange Called with the edited tree.
 * @param family The layout's family; only block types for it can be added.
 * @param blocks The block catalogue.
 * @param catalogue The record types and fields.
 * @param widgets The report components a widget block can embed.
 * @param problems The server's problems for the tree.
 * @param readOnly A layout shared from elsewhere: shown, not editable.
 * @param toolbarEnd Controls the designer puts at the end of the toolbar above the canvas (the preview buttons).
 * @param images The picture library an image block chooses from (absent where the layout has none).
 * @param snippets The snippet calls, and what to tell the designer after an insertion; with `images` (a snippet may need a
 *   picture), else no Insert snippet button. `onSave`, when given, adds Save as snippet for the selected block.
 */
export function ReportLayoutBlocks({
  tree, onChange, family, blocks, catalogue, widgets, problems, readOnly = false, toolbarEnd, images, snippets,
}: {
  tree: Tree;
  onChange: (next: Tree) => void;
  family: LayoutFamily;
  blocks: BlockCatalogue;
  catalogue: ReportFieldCatalogue;
  widgets: ReportWidget[];
  problems: TreeProblem[];
  readOnly?: boolean;
  toolbarEnd?: ReactNode;
  images?: { library: ReportImageLibrary; scope: "organization" | "project" };
  snippets?: {
    api: Pick<ReportLayoutApi, "snippets" | "applySnippet">;
    onInserted: (notice: SnippetNoticeData) => void;
    /** Saves the selected block (with everything inside it) as a snippet: the run of blocks and words that name it. */
    onSave?: (selection: SnippetSelection, label: string) => void;
  };
}) {
  const text = useStrings().reportOutline;
  const snippetText = useStrings().reportSnippets;
  const [pickerOpen, setPickerOpen] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const workspace = useRef<Blockly.WorkspaceSvg | null>(null);
  /** The tree the workspace shows; an incoming tree equal to it needs no redraw. */
  const shown = useRef({ tree, json: stableJson(tree) });
  const latest = useRef({ onChange, types: blocks.blocks });
  useEffect(() => {
    latest.current = { onChange, types: blocks.blocks };
  }, [onChange, blocks.blocks]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loose, setLoose] = useState(0);
  const [ready, setReady] = useState(false);
  /** The place chosen in the Add block dropdown (an index into `targets`) and the block it was chosen for. */
  const [chosenTarget, setChosenTarget] = useState({ selected: null as string | null, index: 0 });

  const types = blocks.blocks;
  const layoutLabel = text.layoutBlock;
  const unknownLabel = text.unknownBlockOnCanvas;
  const declared = Array.isArray(tree.variables) ? (tree.variables as { name?: string }[]).map((v) => String(v.name ?? "")).filter(Boolean) : [];
  const pageStyles = Array.isArray(tree.page_styles) ? (tree.page_styles as { name?: string }[]).map((s) => String(s.name ?? "")).filter(Boolean) : [];
  const env: BlockEnv = { blocks, catalogue, widgets, variables: declared, pageStyles, images, readOnly };

  // The workspace lives as long as the catalogue, family and mode it was built for.
  useEffect(() => {
    if (!host.current) return undefined;
    registerBlocks(types, { layout: layoutLabel, unknownBlock: unknownLabel });
    const ws = Blockly.inject(host.current, {
      readOnly,
      theme: buildTheme(),
      renderer: "zelos",
      sounds: false,
      trashcan: !readOnly,
      zoom: { controls: true, wheel: false, startScale: 1, minScale: 0.5, maxScale: 1.5, scaleSpeed: 1.1 },
      move: { scrollbars: true, drag: true, wheel: true },
    });
    workspace.current = ws;
    Blockly.serialization.workspaces.load(treeToWorkspaceState(shown.current.tree, types), ws);
    ws.addChangeListener(Blockly.Events.disableOrphans);

    const onEvent = (event: Blockly.Events.Abstract) => {
      if (event.type === Blockly.Events.SELECTED) {
        // Blockly deselects when focus leaves the workspace, which is exactly what typing in the inspector does, so only
        // a newly selected block changes the inspector: it keeps showing the last block until another is chosen.
        const id = (event as Blockly.Events.Selected).newElementId;
        if (id) setSelected(indexPaths(ws).get(id) ?? null);
        return;
      }
      if (event.isUiEvent || event.type === Blockly.Events.FINISHED_LOADING) return;
      const state = Blockly.serialization.workspaces.save(ws) as { blocks?: { blocks?: BlockState[] } };
      setLoose(looseBlockCount(state));
      const next = workspaceStateToTree(shown.current.tree, state, latest.current.types);
      const json = stableJson(next);
      if (json === shown.current.json) return;
      shown.current = { tree: next, json };
      latest.current.onChange(next);
    };
    ws.addChangeListener(onEvent);

    const resize = new ResizeObserver(() => Blockly.svgResize(ws));
    resize.observe(host.current);
    const retheme = new MutationObserver(() => ws.setTheme(buildTheme()));
    retheme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    setReady(true);

    return () => {
      resize.disconnect();
      retheme.disconnect();
      workspace.current = null;
      setReady(false);
      ws.dispose();
    };
    // The tree is read through `shown`, so a keystroke never rebuilds the workspace.
  }, [types, readOnly, layoutLabel, unknownLabel]);

  // A tree that did not come from the workspace (the inspector, the settings) is patched in, or redrawn if its shape changed.
  useEffect(() => {
    const json = stableJson(tree);
    if (json === shown.current.json) return;
    shown.current = { tree, json };
    const ws = workspace.current;
    if (!ws) return;
    Blockly.Events.disable();
    try {
      if (shapeOf(tree.nodes, types) === shapeOf(workspaceNodes(ws, types), types)) {
        const root = ws.getTopBlocks(false).find((b) => b.type === ROOT_TYPE);
        patchChain(root?.getInputTargetBlock(ROOT_INPUT) ?? null, tree.nodes, types);
      } else {
        const { scrollX, scrollY } = ws;
        Blockly.serialization.workspaces.load(treeToWorkspaceState(tree, types), ws);
        ws.scroll(scrollX, scrollY);
        setSelected(null);
      }
    } finally {
      Blockly.Events.enable();
    }
  }, [tree, types]);

  // The server's problems appear as warnings on the blocks they belong to.
  useEffect(() => {
    const ws = workspace.current;
    if (!ws || !ready) return;
    Blockly.Events.disable();
    try {
      for (const [id, path] of indexPaths(ws)) {
        const messages = problemsForNode(problems, path);
        const all = [...messages.own, ...[...messages.byKey.values()].flat()];
        ws.getBlockById(id)?.setWarningText(all.length > 0 ? all.join("\n") : null);
      }
    } finally {
      Blockly.Events.enable();
    }
  }, [problems, tree, ready]);

  const addable = useMemo(() => paletteEntries(types, family), [types, family]);
  const addr = selected ? parsePath(selected) : null;
  const node = addr ? nodeAt(tree, addr) : undefined;
  const type = node ? types.find((t) => t.type === node.type) : undefined;

  /** Where a block can be added: the end of the layout, and, for the selected block, after it or inside each child list. */
  const layoutLength = listAt(tree, [ROOT_INPUT]).length;
  const targets = useMemo((): AddTarget[] => {
    const end: AddTarget = { list: [ROOT_INPUT], index: layoutLength, label: text.addingAtEnd };
    if (!addr || !node) return [end];
    const name = describeBlock(node, type);
    const parent = addr.slice(0, -1);
    const at = addr[addr.length - 1];
    const inside = (type?.containers ?? []).map((container): AddTarget => {
      const children = node[container.key];
      return { list: [...addr, container.key], index: Array.isArray(children) ? children.length : 0, label: text.addingInside(name, container.label) };
    });
    const after: AddTarget = { list: parent, index: typeof at === "number" ? at + 1 : layoutLength, label: text.addingAfter(name) };
    // A container takes the new block inside by default; any other block, after it.
    return [...inside, after, end];
  }, [addr, node, type, layoutLength, text]);
  // A different selected block starts again from its default place.
  const target = targets[chosenTarget.selected === selected ? Math.min(chosenTarget.index, targets.length - 1) : 0];

  /**
   * Adds blocks made from `templates` to the child list `list` from `index`, as one undoable step, and selects the first
   * so its settings open in the inspector. The blocks are made in the workspace and reach the tree through its change
   * events, like blocks dragged in.
   */
  function addAll(list: Seg[], index: number, templates: TreeNode[]) {
    const ws = workspace.current;
    if (!ws || templates.length === 0) return;
    const paths = indexPaths(ws);
    const containerKey = String(list[list.length - 1]);
    const owner = list.length === 1 ? ws.getTopBlocks(false).find((b) => b.type === ROOT_TYPE) : ws.getBlockById([...paths].find(([, p]) => p === formatPath(list.slice(0, -1)))?.[0] ?? "");
    const connection = owner?.getInput(containerKey)?.connection;
    if (!owner || !connection) return;
    Blockly.Events.setGroup(true);
    try {
      let first: Blockly.BlockSvg | null = null;
      templates.forEach((template, offset) => {
        const block = Blockly.serialization.blocks.append(nodeToBlockState(cloneNode(template), types), ws, { recordUndo: true }) as Blockly.BlockSvg;
        let before: Blockly.Block | null = null;
        for (let at = connection.targetBlock(), i = 0; at && i < index + offset; at = at.getNextBlock(), i += 1) before = at;
        if (before?.nextConnection && block.previousConnection) before.nextConnection.connect(block.previousConnection);
        else if (block.previousConnection) connection.connect(block.previousConnection);
        first ??= block;
      });
      const toSelect = first as Blockly.BlockSvg | null;
      // The menu that was clicked gives focus back to its button as it closes, which would deselect the block, so wait for that.
      setTimeout(() => {
        if (toSelect && !toSelect.isDeadOrDying()) Blockly.common.setSelected(toSelect);
      }, 0);
    } finally {
      Blockly.Events.setGroup(false);
    }
  }

  /** The selected block as the run Save as snippet saves, or `null` with nothing selected. */
  const savable = addr && node ? selectionOfBlock(addr) : null;

  /** Where a snippet can go: the place Add block states, and the start of the layout (a cover page or a logo belongs there). */
  const snippetPlaces: SnippetPlace[] = [
    { container: formatPath(target.list), index: target.index, label: target.label },
    ...(target.list.length === 1 && target.index === 0 ? [] : [{ container: ROOT_INPUT, index: 0, label: snippetText.atStart }]),
  ];

  /** Adds one block made from `template`. */
  const addAt = (list: Seg[], index: number, template: TreeNode) => addAll(list, index, [template]);

  /**
   * Puts an applied snippet in the layout: the server's root-level changes (page styles, variables) are taken as they are,
   * then its blocks are created in the workspace in one undo group.
   */
  function insertSnippet(result: SnippetApplyResult, snippet: ReportSnippet) {
    const placed = insertedBlocks(result);
    if (!placed || result.tree === null) return;
    const merged = withBlocksOf(result.tree, shown.current.tree);
    const json = stableJson(merged);
    // The workspace's own events build the next tree from `shown`, so it must hold the root changes before the blocks arrive.
    if (json !== shown.current.json) {
      shown.current = { tree: merged, json };
      onChange(merged);
    }
    addAll(placed.list, placed.index, placed.nodes);
    setPickerOpen(false);
    snippets?.onInserted({ name: snippet.name, changes: result.changes, problemsElsewhere: result.problems_elsewhere });
  }

  /** A dropdown listing every block that can be added, which adds the chosen one at `place`. */
  const addMenu = (label: string, place: () => { list: Seg[]; index: number }) => (
    <MenuButton
      label={label} menuLabel={label}
      items={addable.map((entry) => ({
        key: entry.key,
        label: entry.template.level !== undefined ? `${entry.type.label} ${String(entry.template.level)}` : entry.type.label,
        group: entry.common ? text.commonBlocks : text.otherBlocks,
        onSelect: () => {
          const at = place();
          addAt(at.list, at.index, entry.template);
        },
      }))}
    />
  );

  return (
    <div className="stack" role="region" aria-label={text.blocksLabel}>
      <ReportLayoutSettings tree={tree} onChange={onChange} family={family} blocks={blocks} env={env} problems={problems} />
      <p className="text-muted" style={{ margin: 0 }}>{readOnly ? text.blocksReadOnlyHint : text.blocksHint}</p>
      <div className="row blocks-toolbar">
        {!readOnly && (
          <>
            {addMenu(text.addBlock, () => target)}
            {snippets && images && (
              <button type="button" className="btn" aria-haspopup="dialog" onClick={() => setPickerOpen(true)}>{snippetText.insertButton}</button>
            )}
            {snippets?.onSave && (
              <button
                type="button" className="btn" aria-haspopup="dialog" disabled={savable === null}
                title={savable === null ? snippetText.saveButtonHint : undefined}
                onClick={() => { if (savable) snippets.onSave?.(savable, snippetText.saveSelected(describeBlock(node ?? {}, type))); }}
              >
                {snippetText.saveButton}
              </button>
            )}
            {targets.length > 1 ? (
              <select
                className="input blocks-target" aria-label={text.addWhere} value={targets.indexOf(target)}
                onChange={(e) => setChosenTarget({ selected, index: Number(e.target.value) })}
              >
                {targets.map((option, index) => <option key={index} value={index}>{option.label}</option>)}
              </select>
            ) : (
              <span className="text-muted" role="status">{target.label}</span>
            )}
          </>
        )}
        {toolbarEnd && <span className="blocks-toolbar-end">{toolbarEnd}</span>}
      </div>
      {pickerOpen && snippets && images && (
        <ReportSnippetPicker
          api={snippets.api} family={family} blockTypes={types} tree={tree} images={images}
          places={snippetPlaces}
          onClose={() => setPickerOpen(false)} onInserted={insertSnippet}
        />
      )}
      <div className="blocks-host">
        <div className="blocks-layout">
          <div className="blocks-stage">
            <div ref={host} className="blocks-workspace" aria-label={text.workspaceLabel} />
          </div>
          <aside className="stack blocks-inspector" aria-label={text.inspectorLabel}>
            {loose > 0 && <p role="status" className="text-muted" style={{ margin: 0 }}>{text.looseBlocks(loose)}</p>}
            {node && addr && selected ? (
              <div className="stack" data-testid="block-inspector">
                <strong>{text.inspectorTitle(type?.label ?? String(node.type ?? "?"))}</strong>
                {(() => {
                  // Problems about the block as a whole, or a key no field is drawn for (a typo in JSON, a child list's own limit).
                  const found = problemsForNode(problems, selected);
                  const drawn = new Set(type?.described ? type.fields.map((f) => f.key) : []);
                  const stray = [...found.byKey.entries()].filter(([key]) => !drawn.has(key)).flatMap(([, list]) => list);
                  const messages = [...found.own, ...stray];
                  return messages.length > 0 ? (
                    <ul className="outline-field-problems" role="alert">{messages.map((m, i) => <li key={i}>{m}</li>)}</ul>
                  ) : null;
                })()}
                {type && type.described ? (
                  type.fields.map((field) => (
                    <ReportLayoutBlockField
                      key={field.key} field={field} node={node} names={namesInScope(tree, addr, types)} env={env}
                      problems={problemsForNode(problems, selected).byKey.get(field.key) ?? []}
                      onChange={(key, value) => onChange(setAt(tree, [...addr, key], value))}
                    />
                  ))
                ) : (
                  <ReportLayoutJsonField
                    label={text.unknownBlock(String(node.type ?? "?"))} value={node} disabled={readOnly}
                    onChange={(next) => {
                      if (next !== null && typeof next === "object" && !Array.isArray(next)) onChange(setAt(tree, addr, next));
                    }}
                  />
                )}
                {!readOnly && type?.containers.map((container) => (
                  <div key={container.key}>
                    {addMenu(text.addInside(container.label), () => ({
                      list: [...addr, container.key], index: Array.isArray(node[container.key]) ? (node[container.key] as unknown[]).length : 0,
                    }))}
                  </div>
                ))}
                {type && type.fields.length === 0 && type.containers.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{text.noSettings}</p>}
              </div>
            ) : (
              <p className="text-muted" style={{ margin: 0 }}>{text.selectBlock}</p>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
