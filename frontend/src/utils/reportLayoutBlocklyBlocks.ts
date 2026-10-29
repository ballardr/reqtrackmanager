/**
 * Module: utils/reportLayoutBlocklyBlocks
 *
 * Everything the block editor needs from Blockly itself: the block types generated from the server's block
 * schemas and the theme drawn from the app's colour tokens.
 *
 * Responsibilities:
 * - Register one Blockly block type per layout block type (`BlockType`): a label, its short fields inline with a
 *   small label each, and a statement input per child list. A module's block type therefore needs no code here.
 * - Register the fixed root block and the stand-in for a block type the catalogue does not describe.
 * - Build a Blockly theme from the CSS colour tokens, so the editor follows the light and dark themes.
 *
 * Design decisions: the whole of Blockly is imported here and nowhere else, and this module is only loaded by the
 * lazily loaded editor, so the library stays out of the main bundle. Block colours come from a small fixed set
 * (structure, data, content) rather than per-type colours, with a light and a dark value each, mirroring how a
 * module registers its own accent colour instead of a core map growing an entry. Field values travel as strings in
 * dropdowns; `reportLayoutBlockly` converts them.
 */
import * as Blockly from "blockly/core";
import * as En from "blockly/msg/en";

import type { BlockField, BlockType } from "../api/reportLayouts";
import { ROOT_INPUT, ROOT_TYPE, SUMMARY_FIELD, UNKNOWN_TYPE, UNSET, blockName, dropdownValues, inlineFields, inspectorFields } from "./reportLayoutBlockly";

/** The text the editor puts on its blocks (the app's strings, passed in so this module holds none). */
export interface BlockLabels {
  layout: string;
  unknownBlock: string;
}

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

/** Draws one inline field's control and gives it the key as its name. */
function controlFor(field: BlockField): Blockly.Field {
  const options = dropdownValues(field);
  if (field.kind === "boolean") return new Blockly.FieldCheckbox(false);
  if (options) {
    const labelled: [string, string][] = [[labelOf(field, UNSET), UNSET], ...options.map((o): [string, string] => [labelOf(field, o), o])];
    return new Blockly.FieldDropdown(labelled);
  }
  const max = field.max_length;
  // Blockly's text field has no length limit of its own: cut what is typed or pasted past the schema's limit.
  return new Blockly.FieldTextInput("", max ? (value: string) => (value.length > max ? value.slice(0, max) : value) : undefined);
}

/** What a dropdown option reads as: the value itself, or "default" (with the default when known) for the unset one. */
function labelOf(field: BlockField, value: string): string {
  if (value !== UNSET) return value.charAt(0).toUpperCase() + value.slice(1);
  return field.default !== null && field.default !== undefined ? `(${String(field.default)})` : "—";
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
      this.appendDummyInput().appendField(new Blockly.FieldLabel(labels.layout));
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
        for (const field of inlineFields(type)) {
          // A field named like its block ("Heading" on a Heading) needs no second label.
          if (field.label.toLowerCase() !== type.label.toLowerCase()) head.appendField(new Blockly.FieldLabel(field.label, "rl-field-label"));
          head.appendField(controlFor(field), field.key);
        }
        // What only the inspector edits (a record type, the start of a text) is shown as a read-only summary.
        if (inspectorFields(type).length > 0) head.appendField(new Blockly.FieldLabelSerializable("", "rl-summary"), SUMMARY_FIELD);
        for (const container of type.containers) {
          this.appendStatementInput(container.key).appendField(container.label);
        }
      },
    };
  }
}
