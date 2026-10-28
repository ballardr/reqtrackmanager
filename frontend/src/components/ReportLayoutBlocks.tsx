/**
 * Module: components/ReportLayoutBlocks
 *
 * The block editor: a layout drawn as blocks on a Blockly workspace, with the selected block's full form (every
 * field, including source, columns, condition, widget settings and long text) in an inspector beside it. It is the
 * designer's second view of the layout tree.
 *
 * Responsibilities:
 * - Draw the tree as blocks and write every edit back to the tree through `onChange`; the tree is the designer's,
 *   this component holds no second model (`utils/reportLayoutBlockly` does the conversion without losing a key).
 * - Generate the block types and the palette from the server's block schemas, so a module's block type needs no
 *   code here; show the server's problems as warnings on the blocks and in the inspector.
 * - Keep the inspector's edits and the workspace in step: an edit that changes only values is patched into the
 *   blocks in place (selection and scroll stay), a change in shape rebuilds the workspace.
 * - Offer the same additions without a pointer ("Add block", "Add to <list>") and follow the app's light and dark
 *   themes.
 *
 * Design decisions: Blockly is loaded lazily by the designer (`React.lazy`), keeping its ~1 MB out of the main
 * bundle. Blocks carry short fields inline as a quick edit; the inspector holds every field with the shared field
 * editors, reused as they are, because embedding React inside SVG blocks would give two editing worlds, and a plain
 * form is the route for people who do not use a pointer. A block
 * dropped outside the layout is not part of it and is counted, not silently dropped. Validity is the server's.
 */
import * as Blockly from "blockly/core";
import { useEffect, useRef, useState } from "react";

import type { BlockCatalogue, BlockType, LayoutFamily, ReportFieldCatalogue, ReportWidget, TreeProblem } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import {
  ROOT_INPUT, ROOT_TYPE, SUMMARY_FIELD, blockSummary, chainToNodes, controlValue, inlineFields, layoutType, looseBlockCount,
  nodeData, paletteEntries, shapeOf, treeToWorkspaceState, workspaceStateToTree, type BlockState,
} from "../utils/reportLayoutBlockly";
import { buildTheme, registerBlocks, toolboxFor } from "../utils/reportLayoutBlocklyBlocks";
import {
  cloneNode, formatPath, insertNode, listAt, namesInScope, nodeAt, parsePath, problemsForNode, setAt, stableJson, type Tree, type TreeNode,
} from "../utils/reportLayoutTree";
import { MenuButton } from "./MenuButton";
import { ReportLayoutJsonField } from "./ReportLayoutJsonField";
import { ReportLayoutBlockField, type BlockEnv } from "./ReportLayoutBlockField";
import { ReportLayoutSettings } from "./ReportLayoutSettings";

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

/**
 * @param tree The layout tree.
 * @param onChange Called with the edited tree.
 * @param family The layout's family; only block types for it are in the palette.
 * @param blocks The block catalogue.
 * @param catalogue The record types and fields.
 * @param widgets The report components a widget block can embed.
 * @param problems The server's problems for the tree.
 * @param readOnly A layout shared from elsewhere: shown, not editable.
 */
export function ReportLayoutBlocks({
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
  /** The path of a block just added: it is selected once the workspace has it, so its settings are at hand. */
  const pendingSelect = useRef<string | null>(null);

  const types = blocks.blocks;
  const layoutLabel = text.layoutBlock;
  const unknownLabel = text.unknownBlockOnCanvas;
  const declared = Array.isArray(tree.variables) ? (tree.variables as { name?: string }[]).map((v) => String(v.name ?? "")).filter(Boolean) : [];
  const env: BlockEnv = { blocks, catalogue, widgets, variables: declared, readOnly };

  // The workspace lives as long as the catalogue, family and mode it was built for.
  useEffect(() => {
    if (!host.current) return undefined;
    registerBlocks(types, { layout: layoutLabel, unknownBlock: unknownLabel });
    const ws = Blockly.inject(host.current, {
      readOnly,
      theme: buildTheme(),
      toolbox: readOnly ? undefined : toolboxFor(paletteEntries(types, family), types),
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
  }, [types, family, readOnly, layoutLabel, unknownLabel]);

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
    const pending = pendingSelect.current;
    pendingSelect.current = null;
    if (pending) {
      const id = [...indexPaths(ws)].find(([, path]) => path === pending)?.[0];
      const block = id ? ws.getBlockById(id) : null;
      if (block) Blockly.common.setSelected(block);
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

  function addTo(list: (string | number)[], template: TreeNode) {
    const index = listAt(tree, list).length;
    pendingSelect.current = formatPath([...list, index]);
    onChange(insertNode(tree, list, index, cloneNode(template)));
  }

  const addable = paletteEntries(types, family);
  const addEntries = (list: (string | number)[], label: string) => (
    <MenuButton
      label={label} menuLabel={label}
      items={addable.map((entry) => ({
        key: entry.key,
        label: entry.template.level !== undefined ? `${entry.type.label} ${String(entry.template.level)}` : entry.type.label,
        onSelect: () => addTo(list, entry.template),
      }))}
    />
  );

  const addr = selected ? parsePath(selected) : null;
  const node = addr ? nodeAt(tree, addr) : undefined;
  const type = node ? types.find((t) => t.type === node.type) : undefined;

  return (
    <div className="stack" role="region" aria-label={text.blocksLabel}>
      <ReportLayoutSettings tree={tree} onChange={onChange} family={family} blocks={blocks} env={env} problems={problems} />
      <p className="text-muted" style={{ margin: 0 }}>{readOnly ? text.blocksReadOnlyHint : text.blocksHint}</p>
      <div className="blocks-layout">
        <div className="blocks-stage">
          <div ref={host} className="blocks-workspace" aria-label={text.workspaceLabel} />
        </div>
        <aside className="stack blocks-inspector" aria-label={text.inspectorLabel}>
          {!readOnly && <div>{addEntries([ROOT_INPUT], text.addBlock)}</div>}
          {loose > 0 && <p role="status" className="text-muted" style={{ margin: 0 }}>{text.looseBlocks(loose)}</p>}
          {node && addr && selected ? (
            <div className="stack" data-testid="block-inspector">
              <strong>{type?.label ?? String(node.type ?? "?")}</strong>
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
                <div key={container.key}>{addEntries([...addr, container.key], text.addInside(container.label))}</div>
              ))}
              {type && type.fields.length === 0 && type.containers.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{text.noSettings}</p>}
            </div>
          ) : (
            <p className="text-muted" style={{ margin: 0 }}>{text.selectBlock}</p>
          )}
        </aside>
      </div>
    </div>
  );
}
