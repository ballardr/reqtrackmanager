/**
 * Module: utils/reportLayoutBlocklyBlocks
 *
 * Everything the block editor needs from Blockly itself: the block types generated from the server's block
 * schemas and the theme drawn from the app's colour tokens.
 *
 * Responsibilities:
 * - Register one Blockly block type per layout block type (`BlockType`): a label, a read-only summary of its key
 *   facts, and a statement input per child list. A module's block type therefore needs no code here.
 * - Register the fixed root block and the stand-in for a block type the catalogue does not describe.
 * - Build a Blockly theme from the CSS colour tokens, so the editor follows the light and dark themes.
 *
 * Design decisions: the whole of Blockly is imported here and nowhere else, and this module is only loaded by the
 * lazily loaded editor, so the library stays out of the main bundle. Block colours come from a small fixed set
 * (structure, data, content) rather than per-type colours, with a light and a dark value each, mirroring how a
 * module registers its own accent colour instead of a core map growing an entry.
 */
import * as Blockly from "blockly/core";
import * as En from "blockly/msg/en";

import type { BlockType } from "../api/reportLayouts";
import { ROOT_INPUT, ROOT_TYPE, SUMMARY_FIELD, UNKNOWN_TYPE, blockName } from "./reportLayoutBlockly";

/** The text the editor puts on its blocks (the app's strings, passed in so this module holds none). */
export interface BlockLabels {
  layout: string;
  unknownBlock: string;
  /** The name of the settings button on the layout block. */
  settings: string;
  /** Called when the settings button is pressed (opens the layout's settings in the block editor). */
  onSettings: () => void;
}

/** The settings button's picture: a gear, drawn in white because the layout block is a dark colour in both themes. */
const GEAR_ICON =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  );

type BlockRole = "structure" | "data" | "content";

/** The look of a block type: ones that hold other blocks, ones that read records, and plain content. */
function roleOf(type: BlockType): BlockRole {
  if (type.containers.length > 0) return "structure";
  if (type.fields.some((f) => f.kind === "source" || f.kind === "columns" || f.kind === "widget_key")) return "data";
  return "content";
}

/** Block colours: dark enough for white text in both themes. */
const ROLE_COLOURS: Record<"light" | "dark", Record<BlockRole, string>> = {
  light: { structure: "#2f5d8a", data: "#2f7a5a", content: "#5b4b8a" },
  dark: { structure: "#3d6fa3", data: "#3a8c68", content: "#6e5da3" },
};

/** Reads a CSS custom property of the document root, falling back when the page does not define it. */
function token(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value === "" ? fallback : value;
}

/** @returns Whether the page is showing its dark theme. */
export function isDarkTheme(): boolean {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

let themeCounter = 0;

/** Builds the Blockly theme for the colours the page shows right now; call again after the theme changes. */
export function buildTheme(): Blockly.Theme {
  const dark = isDarkTheme();
  const colours = ROLE_COLOURS[dark ? "dark" : "light"];
  const surface = token("--color-surface", dark ? "#1c222c" : "#ffffff");
  const alt = token("--color-surface-alt", dark ? "#242b37" : "#eef0f3");
  const text = token("--color-text", dark ? "#e6e9ef" : "#1a202c");
  const border = token("--color-border", dark ? "#333c4a" : "#c3c9d1");
  themeCounter += 1;
  return Blockly.Theme.defineTheme(`reqtrack-${themeCounter}`, {
    name: `reqtrack-${themeCounter}`,
    base: Blockly.Themes?.Classic ?? undefined,
    blockStyles: {
      rl_structure: { colourPrimary: colours.structure },
      rl_data: { colourPrimary: colours.data },
      rl_content: { colourPrimary: colours.content },
    },
    componentStyles: {
      workspaceBackgroundColour: alt,
      toolboxBackgroundColour: surface,
      toolboxForegroundColour: text,
      flyoutBackgroundColour: surface,
      flyoutForegroundColour: text,
      flyoutOpacity: 1,
      scrollbarColour: border,
      scrollbarOpacity: 0.6,
      insertionMarkerColour: text,
      insertionMarkerOpacity: 0.3,
      cursorColour: token("--color-accent", "#2f855a"),
    },
  });
}

/**
 * Registers every block type the editor draws. Safe to call again with a newer catalogue.
 *
 * @param types The server's block types.
 * @param labels The words on the root and stand-in blocks.
 */
export function registerBlocks(types: BlockType[], labels: BlockLabels): void {
  Blockly.setLocale(En as unknown as Record<string, string>);
  const blocks = Blockly.Blocks as Record<string, unknown>;

  blocks[ROOT_TYPE] = {
    init(this: Blockly.Block) {
      this.setStyle("rl_structure");
      this.appendDummyInput()
        .appendField(new Blockly.FieldLabel(labels.layout))
        .appendField(new Blockly.FieldImage(GEAR_ICON, 18, 18, labels.settings, () => labels.onSettings()));
      this.appendStatementInput(ROOT_INPUT);
      this.setDeletable(false);
      this.setMovable(false);
      this.setTooltip(labels.layout);
    },
  };

  blocks[UNKNOWN_TYPE] = {
    init(this: Blockly.Block) {
      this.setStyle("rl_content");
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.appendDummyInput().appendField(new Blockly.FieldLabel(labels.unknownBlock));
    },
  };

  for (const type of types) {
    blocks[blockName(type.type)] = {
      init(this: Blockly.Block) {
        this.setStyle(`rl_${roleOf(type)}`);
        this.setPreviousStatement(true);
        this.setNextStatement(true);
        this.setTooltip(type.description || type.label);
        const head = this.appendDummyInput().appendField(new Blockly.FieldLabel(type.label, "rl-block-title"));
        // The block only reports its key facts; every value is edited in the block editor beside the workspace.
        if (type.described && type.fields.length > 0) head.appendField(new Blockly.FieldLabelSerializable("", "rl-summary"), SUMMARY_FIELD);
        for (const container of type.containers) {
          this.appendStatementInput(container.key).appendField(container.label);
        }
      },
    };
  }
}
